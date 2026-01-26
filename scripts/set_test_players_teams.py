"""
Ensure local test accounts exist and give each a different team_abbr.

This makes schedules/series differ per test user (more realistic admin testing).
"""

from pathlib import Path
import sys

from werkzeug.security import generate_password_hash


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from database import PlayerDB  # noqa: E402


TEST_PASSWORD = "test1234"

TEST_PLAYERS = [
    # email, first_name, last_name, team_abbr
    ("testplayer1@sequence.local", "Test", "Player1", "NYY"),
    ("testplayer2@sequence.local", "Test", "Player2", "BOS"),
    ("testplayer3@sequence.local", "Test", "Player3", "LAD"),
    ("testplayer4@sequence.local", "Test", "Player4", "CHC"),
    ("testplayer5@sequence.local", "Test", "Player5", "NYM"),
]


def main() -> None:
    db = PlayerDB()
    created = []
    updated = []
    skipped = []

    pw_hash = generate_password_hash(TEST_PASSWORD)

    try:
        for email, first, last, team_abbr in TEST_PLAYERS:
            user = db.get_user_by_email(email)
            if not user:
                user_id = db.create_user(email=email, password_hash=pw_hash, first_name=first, last_name=last)
                created.append(email)
            else:
                user_id = int(user["id"])

            # Set explicit team to guarantee different schedules.
            existing_team = (user.get("team_abbr") if user else None) if isinstance(user, dict) else None
            if (existing_team or "").strip().upper() == team_abbr:
                skipped.append(email)
            else:
                db.set_user_team_abbr(user_id, team_abbr)
                updated.append(f"{email} -> {team_abbr}")
    finally:
        db.close()

    print("Test player setup complete.")
    if created:
        print(f"Created: {', '.join(created)}")
    if updated:
        print("Updated teams:")
        for row in updated:
            print(f" - {row}")
    if skipped:
        print(f"Already set: {', '.join(skipped)}")
    print(f"Password for test accounts: {TEST_PASSWORD}")


if __name__ == "__main__":
    main()

