"""
db.py
Loads data/assets.csv into SQLite (data/assets.db).
Also creates the actions_log table used by tools.py.
Run: python db.py
"""

import sqlite3
import csv
from pathlib import Path

DB_PATH   = Path("data/assets.db")
CSV_PATH  = Path("data/assets.csv")


# ── connection helper ─────────────────────────────────────────────────────────
def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection. Always use this so the path stays consistent."""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # lets us access columns by name
    return conn


# ── create tables ─────────────────────────────────────────────────────────────
def create_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS assets (
            id               TEXT PRIMARY KEY,
            type             TEXT,
            dept             TEXT,
            location         TEXT,
            purchase_date    TEXT,
            last_maintenance TEXT,
            usage_hours      INTEGER,
            failures         INTEGER,
            status           TEXT
        );

        CREATE TABLE IF NOT EXISTS actions_log (
            log_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp    TEXT    DEFAULT (datetime('now','localtime')),
            asset_id     TEXT,
            action_type  TEXT,
            details      TEXT,
            performed_by TEXT    DEFAULT 'system'
        );
    """)
    conn.commit()
    print("✅  Tables ready.")


# ── load CSV into assets table ────────────────────────────────────────────────
def load_assets(conn: sqlite3.Connection):
    if not CSV_PATH.exists():
        print(f"❌  CSV not found at {CSV_PATH}. Run make_data.py first.")
        return

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # use INSERT OR REPLACE so we can safely re-run this script
    conn.executemany("""
        INSERT OR REPLACE INTO assets
            (id, type, dept, location, purchase_date, last_maintenance,
             usage_hours, failures, status)
        VALUES
            (:id, :type, :dept, :location, :purchase_date, :last_maintenance,
             :usage_hours, :failures, :status)
    """, rows)
    conn.commit()
    print(f"✅  Loaded {len(rows)} assets into {DB_PATH}")


# ── clear actions_log ────────────────────────────────────────────────────────
def clear_actions_log(conn: sqlite3.Connection):
    conn.execute("DELETE FROM actions_log")
    # Reset the autoincrement counter so IDs start from 1 again.
    conn.execute("DELETE FROM sqlite_sequence WHERE name='actions_log'")
    conn.commit()
    print("✅  actions_log cleared.")



def verify(conn: sqlite3.Connection):
    total     = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    by_status = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM assets GROUP BY status"
    ).fetchall()
    log_count = conn.execute("SELECT COUNT(*) FROM actions_log").fetchone()[0]
    print(f"   Total assets in DB: {total}")
    for row in by_status:
        print(f"   {row['status']}: {row['cnt']}")
    print(f"   actions_log rows: {log_count}")


# ── entry point ───────────────────────────────────────────────────────────────
def main():
    conn = get_connection()
    create_tables(conn)
    load_assets(conn)
    clear_actions_log(conn)   # always start with an empty log
    verify(conn)
    conn.close()


if __name__ == "__main__":
    main()
