"""Characterization tests for the factory-only application."""

from __future__ import annotations

import ast
import importlib
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import pytest
import pandas as pd
from flask import render_template_string

from app import create_app
from app.config import Config


REPO_ROOT = Path(__file__).resolve().parents[1]
AUTOMATIC_METHODS = {"HEAD", "OPTIONS"}


class FactoryTestConfig(Config):
    TESTING = True
    DEBUG = False
    SECRET_KEY = "factory-refactor-test-key"
    USE_MOCK_SCHEDULE = True
    ENSURE_DEFAULT_ADMIN = False

    @classmethod
    def ensure_directories(cls):
        """Keep application creation side-effect free in route tests."""


@pytest.fixture(scope="module")
def factory_app():
    return create_app(FactoryTestConfig)


def _factory_method_routes(app):
    routes = defaultdict(list)
    for rule in app.url_map.iter_rules():
        for method in sorted(set(rule.methods) - AUTOMATIC_METHODS):
            routes[(rule.rule, method)].append(rule.endpoint)
    return routes


def _legacy_method_routes():
    """Read the known-good app.py route decorators without importing it."""
    tree = ast.parse((REPO_ROOT / "app.py").read_text(encoding="utf-8"))
    routes = set()

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            target = decorator.func
            if not (
                isinstance(target, ast.Attribute)
                and target.attr == "route"
                and isinstance(target.value, ast.Name)
                and target.value.id == "app"
                and decorator.args
            ):
                continue

            path = ast.literal_eval(decorator.args[0])
            methods = ["GET"]
            for keyword in decorator.keywords:
                if keyword.arg == "methods":
                    methods = ast.literal_eval(keyword.value)
                    break
            routes.update((path, method.upper()) for method in methods)

    return routes


def _authenticate(client, *, is_admin=False):
    now = time.time()
    user = {
        "id": 1,
        "email": "admin@example.com" if is_admin else "player@example.com",
        "first_name": "Factory",
        "last_name": "Test",
        "is_admin": is_admin,
        "is_active": True,
    }
    with client.session_transaction() as session:
        session["user_id"] = user["id"]
        session["is_admin"] = is_admin
        session["_cached_user"] = user
        session["_user_cache_timestamp"] = now
        session["_session_check_at"] = now


def test_factory_preserves_every_legacy_route_and_method(factory_app):
    factory_routes = set(_factory_method_routes(factory_app))
    missing = sorted(_legacy_method_routes() - factory_routes)
    assert missing == []


def test_factory_has_no_ambiguous_method_routes(factory_app):
    ambiguous = {
        route: endpoints
        for route, endpoints in _factory_method_routes(factory_app).items()
        if len(endpoints) > 1
    }
    assert ambiguous == {}


@pytest.mark.parametrize(
    ("path", "endpoint"),
    [
        ("/api/visuals/pitch-mix-analysis", "visuals.api_visuals_pitch_mix_analysis"),
        ("/api/visuals/count-performance", "visuals.api_visuals_count_performance"),
        ("/api/visuals/swing-decision-matrix", "visuals.api_visuals_swing_decision_matrix"),
        ("/api/visuals/plate-discipline-matrix", "visuals.api_visuals_plate_discipline_matrix"),
        ("/api/visuals/velocity-trends", "visuals.api_visuals_velocity_trends"),
        ("/api/visuals/zone-contact-rates", "visuals.api_visuals_zone_contact_rates"),
        ("/api/visuals/expected-stats-comparison", "visuals.api_visuals_expected_stats_comparison"),
    ],
)
def test_visualization_routes_have_one_canonical_handler(factory_app, path, endpoint):
    routes = _factory_method_routes(factory_app)
    assert routes[(path, "GET")] == [endpoint]


def test_templates_do_not_depend_on_legacy_endpoint_names():
    unqualified = []
    pattern = re.compile(r"url_for\(\s*(['\"])([^'\"]+)\1")

    for template in sorted((REPO_ROOT / "templates").rglob("*.html")):
        for match in pattern.finditer(template.read_text(encoding="utf-8")):
            endpoint = match.group(2)
            if endpoint != "static" and "." not in endpoint:
                unqualified.append((str(template.relative_to(REPO_ROOT)), endpoint))

    assert unqualified == []


def test_template_endpoints_are_registered_by_factory(factory_app):
    referenced = set()
    pattern = re.compile(r"url_for\(\s*(['\"])([^'\"]+)\1")

    for template in sorted((REPO_ROOT / "templates").rglob("*.html")):
        referenced.update(
            match.group(2)
            for match in pattern.finditer(template.read_text(encoding="utf-8"))
        )

    missing = sorted(referenced - set(factory_app.view_functions))
    assert missing == []


def test_factory_smoke_and_auth_boundary(factory_app):
    with factory_app.test_client() as client:
        login = client.get("/login")
        assert login.status_code == 200

        protected = client.get("/", follow_redirects=False)
        assert protected.status_code == 302
        assert "/login" in protected.headers["Location"]

        upload = client.post("/api/upload-report")
        assert upload.status_code == 401
        assert upload.get_json()["error"] == "Invalid or missing API key"


def test_factory_registers_legacy_template_helpers(factory_app):
    with factory_app.test_request_context("/"):
        rendered = render_template_string(
            "{{ get_team_color_global(team_abbr='NYM') }}"
        )
    assert rendered == "#002D72"
    assert "team_abbr_from_id" in factory_app.jinja_env.filters


def test_gameday_shell_does_not_build_schedule_context(factory_app, monkeypatch):
    from app.routes import pages

    monkeypatch.setattr(pages, "PlayerDB", None)
    monkeypatch.setattr(pages, "determine_user_team", lambda _user: "NYM")
    monkeypatch.setattr(pages, "get_cached_team_metadata", lambda _team: {"team_id": 121})
    monkeypatch.setattr(pages, "get_cached_gameday_context", lambda _user: {})
    monkeypatch.setattr(
        pages,
        "build_gameday_context",
        lambda _user: pytest.fail("initial Gameday render performed external schedule work"),
    )

    with factory_app.test_client() as client:
        _authenticate(client)
        response = client.get("/gameday")

    assert response.status_code == 200
    assert b"Loading schedule" in response.data


def test_gameday_schedule_returns_structured_async_payload(factory_app, monkeypatch):
    from app.routes import pages

    game = {
        "status": "Scheduled",
        "category": "current",
        "date": "Aug 18",
        "opponent": "New York Mets",
        "opponent_abbr": "NYM",
        "opponent_id": 121,
        "home": True,
        "series": "Three-game series",
        "time": "7:10 PM",
        "venue": "Test Park",
        "game_datetime_iso": "2026-08-18T23:10:00Z",
        "probable_pitchers": [],
        "reports": [],
        "games_list": [],
    }
    context = {
        "next_series": {"first_game_datetime_iso": "2026-08-18T23:10:00Z"},
        "schedule_calendar": [{"date": "2026-08-18", "opponent_id": 121}],
    }
    monkeypatch.setattr(pages, "PlayerDB", None)
    monkeypatch.setattr(pages, "persistent_cache", None)
    monkeypatch.setattr(pages, "collect_series_for_gameday", lambda *_args, **_kwargs: [game])
    monkeypatch.setattr(pages, "build_gameday_context", lambda _user: context)

    with factory_app.test_client() as client:
        _authenticate(client)
        response = client.get("/api/gameday/schedule")

    assert response.status_code == 200
    payload = response.get_json()
    assert "New York Mets" in payload["schedule_html"]
    assert payload["next_series"] == context["next_series"]
    assert payload["schedule_calendar"] == context["schedule_calendar"]
    assert payload["stale"] is False


def test_matchups_accepts_ids_and_batches_seasons(factory_app, monkeypatch):
    from app.routes.api import players
    from app.services import persistent_cache
    import scrape_savant

    rows = []
    for year, game_pk in ((2021, 1001), (2022, 1002)):
        rows.append({
            "pitch_type": "FF",
            "game_date": f"{year}-06-01",
            "game_year": year,
            "batter": 222,
            "pitcher": 111,
            "events": "single",
            "description": "hit_into_play",
            "game_type": "R",
            "balls": 0,
            "strikes": 0,
            "type": "X",
            "pfx_x": 0.5,
            "pfx_z": 1.0,
            "plate_x": 0.1,
            "plate_z": 2.5,
            "release_speed": 95.0,
            "release_spin_rate": 2300,
            "spin_axis": 180,
            "launch_speed": 100.0,
            "launch_angle": 12.0,
            "hit_distance_sc": 250,
            "game_pk": game_pk,
            "at_bat_number": 1,
            "pitch_number": 1,
        })
    matchup_df = pd.DataFrame(rows)

    monkeypatch.setattr(scrape_savant, "lookup_batter_id", lambda _name: pytest.fail("remote name lookup used"))
    monkeypatch.setattr(scrape_savant, "fetch_matchup_statcast", lambda *_args: matchup_df.copy())
    monkeypatch.setattr(players, "get_all_play_ids_from_game", lambda _game_pk: {})
    monkeypatch.setattr(persistent_cache, "get_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(persistent_cache, "set_json", lambda *_args, **_kwargs: None)

    with factory_app.test_client() as client:
        _authenticate(client)
        response = client.get(
            "/api/matchups",
            query_string=[
                ("player", "Test Pitcher"),
                ("opponent", "Test Hitter"),
                ("role", "pitcher"),
                ("player_id", "111"),
                ("opponent_id", "222"),
                ("seasons", "2021"),
                ("seasons", "2022"),
            ],
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload["matchups"]) == 2
    assert {item["game_date"][:4] for item in payload["matchups"]} == {"2021", "2022"}


@pytest.mark.parametrize(
    "path",
    [
        "/visuals",
        "/heatmaps",
        "/spraychart",
        "/timeline",
        "/pitchplots",
        "/velocity_trends",
        "/pitch-mix-analysis",
        "/count-performance",
        "/zone-contact-rates",
        "/plate-discipline-matrix",
        "/expected-stats-comparison",
        "/pitch-tunnel",
        "/barrel-quality-contact",
        "/swing-decision-matrix",
        "/pitch-arsenal-effectiveness",
    ],
)
def test_factory_renders_visualization_pages(factory_app, path):
    with factory_app.test_client() as client:
        _authenticate(client)
        response = client.get(path)
        assert response.status_code == 200


def test_legacy_document_paths_delegate_to_canonical_handlers(factory_app, monkeypatch):
    from app.routes.api import admin

    monkeypatch.setattr(admin, "PlayerDB", None)

    with factory_app.test_client() as client:
        _authenticate(client)

        legacy_latest = client.get("/api/workouts/latest")
        canonical_latest = client.get("/api/admin/workouts/latest")
        assert legacy_latest.status_code == canonical_latest.status_code == 200
        assert legacy_latest.get_json() == canonical_latest.get_json() == {"workout": None}

        for path in ("/player-docs/1", "/workout-docs/1"):
            assert client.get(path).status_code == 404


def test_authenticated_unknown_route_uses_factory_error_handler(factory_app):
    with factory_app.test_client() as client:
        _authenticate(client)
        response = client.get("/this-route-does-not-exist")
        assert response.status_code == 404
        assert b"Page Not Found" in response.data


def test_factory_wsgi_does_not_import_legacy_app(monkeypatch):
    import app as app_package

    monkeypatch.setattr(app_package, "ensure_default_admin", lambda: None)
    monkeypatch.setattr(Config, "ensure_directories", classmethod(lambda cls: None))
    sys.modules.pop("wsgi_refactored", None)
    sys.modules.pop("app_py", None)

    module = importlib.import_module("wsgi_refactored")

    assert module.application is module.app
    assert module.app.name == "app"
    assert "app_py" not in sys.modules


def test_factory_fails_startup_when_route_registration_is_incomplete(monkeypatch):
    import app as app_package

    def fail_registration(_app):
        raise RuntimeError("route registration failed")

    monkeypatch.setattr(app_package, "register_routes", fail_registration)
    with pytest.raises(RuntimeError, match="route registration failed"):
        app_package.create_app(FactoryTestConfig)


def test_legacy_wsgi_remains_available_as_rollback(factory_app, monkeypatch):
    import app as app_package

    monkeypatch.setattr(app_package, "ensure_default_admin", lambda: None)
    monkeypatch.setattr(Config, "ensure_directories", classmethod(lambda cls: None))
    sys.modules.pop("wsgi", None)

    legacy_wsgi = importlib.import_module("wsgi")

    factory_routes = set(_factory_method_routes(factory_app))
    rollback_routes = set(_factory_method_routes(legacy_wsgi.application))
    assert legacy_wsgi.application is legacy_wsgi.app
    assert factory_routes <= rollback_routes
