"""Focused tests for the optimized Gameday and Matchups data paths."""

from __future__ import annotations

import pytest

from src import scrape_savant
from src import next_opponent
from src.csv_data_loader import CSVDataLoader


class _FakeResponse:
    content = (
        b"pitch_type,game_date,game_year,batter,pitcher,events,game_type,game_pk,at_bat_number,pitch_number\n"
        b"FF,2021-05-15,2021,222,111,single,R,1001,1,1\n"
    )

    def raise_for_status(self):
        return None


def test_direct_matchup_fetch_filters_upstream_and_reuses_disk_cache(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResponse()

    monkeypatch.setattr(scrape_savant, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(scrape_savant.requests, "get", fake_get)

    first = scrape_savant.fetch_matchup_statcast(111, 222, "2015-03-01", "2026-11-30")
    second = scrape_savant.fetch_matchup_statcast(111, 222, "2015-03-01", "2026-11-30")

    assert len(first) == len(second) == 1
    assert len(calls) == 1
    _, request_kwargs = calls[0]
    assert request_kwargs["params"]["pitchers_lookup[]"] == 111
    assert request_kwargs["params"]["batters_lookup[]"] == 222
    assert request_kwargs["timeout"] == (5, 45)


def test_player_search_returns_stable_local_id():
    loader = CSVDataLoader()
    results = loader.search_players("Shane McClanahan")

    assert results
    assert results[0]["player_id"] == 663556
    assert results[0]["player_type"] == "pitcher"


def test_gameday_schedule_uses_one_bounded_minimal_request(monkeypatch):
    calls = []

    def fake_get(endpoint, params, **kwargs):
        calls.append((endpoint, params, kwargs))
        return {
            "dates": [{
                "date": "2026-08-18",
                "games": [{
                    "gamePk": 123,
                    "gameDate": "2026-08-18T23:10:00Z",
                    "gameType": "R",
                    "status": {"detailedState": "Scheduled"},
                    "teams": {
                        "home": {"team": {"id": 121, "name": "New York Mets"}},
                        "away": {
                            "team": {"id": 120, "name": "Washington Nationals"},
                            "probablePitcher": {"id": 456, "fullName": "Test Pitcher"},
                        },
                    },
                    "venue": {"name": "Citi Field"},
                    "seriesDescription": "Regular Season",
                }],
            }],
        }

    monkeypatch.setattr(next_opponent.statsapi, "get", fake_get)
    monkeypatch.setattr(
        next_opponent,
        "_team_index",
        lambda: pytest.fail("static MLB abbreviation performed a metadata request"),
    )

    games = next_opponent.next_games(
        "NYM",
        days_ahead=30,
        include_started=True,
        start_date="2026-08-01",
    )

    assert len(calls) == 1
    endpoint, params, kwargs = calls[0]
    assert endpoint == "schedule"
    assert params["teamId"] == 121
    assert params["hydrate"] == "probablePitcher(note)"
    assert kwargs["request_kwargs"]["timeout"] == (3.05, 15)
    assert games[0]["opponent_name"] == "Washington Nationals"
    assert games[0]["probable_pitchers"] == [{"id": 456, "name": "Test Pitcher"}]
