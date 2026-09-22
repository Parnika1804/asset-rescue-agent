"""
tools.py
Business-logic tools for the Asset Rescue Agent.

Functions
─────────
search_assets(query)                          – full-text search
get_high_risk_assets(threshold)               – scored assets above threshold
get_underused_assets(asset_type)              – underuse-flagged assets, optional type filter
schedule_maintenance(asset_id)                – propose maintenance (validated)
reallocate_asset(asset_id, new_dept, loc)     – propose reallocation (validated)
execute_action(action_dict)                   – commit a PROPOSED action to DB
_get_asset(conn, asset_id)                    – internal: fetch one asset row

Validation rules (enforced in proposals AND execute_action):
  • Asset must exist.
  • Asset must not be Decommissioned (for both actions).
  • reallocate_asset: asset must not be Under Repair.
  • reallocate_asset: new_dept must differ from current dept.
"""

import json
import sqlite3
from datetime import date, datetime

import pandas as pd

from db import get_connection
from scoring import score_assets

TODAY = date(2026, 9, 20)

# ── status constants ──────────────────────────────────────────────────────────
STATUS_DECOMMISSIONED = "Decommissioned"
STATUS_UNDER_REPAIR   = "Under Repair"


# ── internal helper ───────────────────────────────────────────────────────────
def _get_asset(conn: sqlite3.Connection, asset_id: str):
    """Return a sqlite3.Row for the asset, or None if not found."""
    return conn.execute(
        "SELECT * FROM assets WHERE id = ?", (asset_id,)
    ).fetchone()


def _error(msg: str) -> dict:
    """Return a standardised error dict."""
    return {"error": msg}


# ── 1. search_assets ──────────────────────────────────────────────────────────
def search_assets(query: str) -> pd.DataFrame:
    """
    Case-insensitive substring search across id, type, dept, and location.
    Returns a DataFrame of matching rows (no scoring columns added).
    """
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM assets", conn)
    conn.close()

    q = query.lower()
    mask = (
        df["id"].str.lower().str.contains(q, na=False)
        | df["type"].str.lower().str.contains(q, na=False)
        | df["dept"].str.lower().str.contains(q, na=False)
        | df["location"].str.lower().str.contains(q, na=False)
    )
    return df[mask].reset_index(drop=True)


# ── 2. get_underused_assets ───────────────────────────────────────────────────
def get_underused_assets(asset_type: str | None = None) -> pd.DataFrame:
    """
    Returns assets flagged as underused (underuse == True) by scoring.py.
    Only Active and Idle assets can be underused (scoring.py enforces this).

    If asset_type is provided (e.g. "laptop" or "laptops"), further filters
    to assets whose type matches case-insensitively, handling singular/plural
    by stripping a trailing 's' from both sides before comparing.

    Returns the same column shape as get_high_risk_assets for consistency:
        id, type, dept, status, repair_risk, usage_hours, reason
    Returns an empty DataFrame (not an error) when nothing matches.
    """
    scored = score_assets()
    result = scored[scored["underuse"] == True].reset_index(drop=True)

    if asset_type:
        # Normalise both sides: lowercase + strip trailing 's' for plural safety
        # e.g. "laptops" → "laptop", "Laptop" → "laptop"
        normalise = lambda s: s.lower().rstrip("s")
        needle = normalise(asset_type)
        result = result[
            result["type"].apply(lambda t: normalise(t) == needle)
        ].reset_index(drop=True)

    return result


# ── 3. get_high_risk_assets ───────────────────────────────────────────────────
def get_high_risk_assets(threshold: int = 60) -> pd.DataFrame:
    """
    Returns non-Decommissioned assets with repair_risk >= threshold,
    sorted highest risk first.
    """
    scored = score_assets()
    return (
        scored[
            (scored["status"] != STATUS_DECOMMISSIONED)
            & (scored["repair_risk"] >= threshold)
        ]
        .sort_values("repair_risk", ascending=False)
        .reset_index(drop=True)
    )


# ── 4. schedule_maintenance ───────────────────────────────────────────────────
def schedule_maintenance(asset_id: str) -> dict:
    """
    Validates and PROPOSES a maintenance action.
    Returns an error dict (with key "error") on any validation failure.
    Does NOT write to the database — call execute_action() to commit.

    Validation:
        • Asset must exist.
        • Asset must not be Decommissioned.
    """
    conn = get_connection()
    row = _get_asset(conn, asset_id)
    conn.close()

    if row is None:
        return _error(f"Asset '{asset_id}' not found.")

    if row["status"] == STATUS_DECOMMISSIONED:
        return _error(
            f"Asset '{asset_id}' is Decommissioned — maintenance cannot be scheduled."
        )

    return {
        "action_type": "schedule_maintenance",
        "asset_id":    asset_id,
        "asset_type":  row["type"],
        "dept":        row["dept"],
        "location":    row["location"],
        "proposed_maintenance_date": TODAY.isoformat(),
        "current_last_maintenance":  row["last_maintenance"],
        "status":      "PROPOSED – awaiting approval",
        "note": (
            "Confirm with execute_action() to update the maintenance record."
        ),
    }


# ── 5. reallocate_asset ───────────────────────────────────────────────────────
def reallocate_asset(asset_id: str, new_dept: str, new_location: str) -> dict:
    """
    Validates and PROPOSES a reallocation action.
    Returns an error dict (with key "error") on any validation failure.
    Does NOT write to the database — call execute_action() to commit.

    Validation:
        • Asset must exist.
        • Asset must not be Decommissioned.
        • Asset must not be Under Repair.
        • new_dept must differ from the asset's current dept.
    """
    conn = get_connection()
    row = _get_asset(conn, asset_id)
    conn.close()

    if row is None:
        return _error(f"Asset '{asset_id}' not found.")

    if row["status"] == STATUS_DECOMMISSIONED:
        return _error(
            f"Asset '{asset_id}' is Decommissioned — reallocation is not permitted."
        )

    if row["status"] == STATUS_UNDER_REPAIR:
        return _error(
            f"Asset '{asset_id}' is Under Repair — reallocation is blocked "
            f"until its status is cleared by IT."
        )

    if row["dept"] == new_dept:
        return _error(
            f"Asset '{asset_id}' is already assigned to '{new_dept}'. "
            f"Target department must be different from the current department."
        )

    return {
        "action_type":   "reallocate_asset",
        "asset_id":      asset_id,
        "asset_type":    row["type"],
        "from_dept":     row["dept"],
        "from_location": row["location"],
        "to_dept":       new_dept,
        "to_location":   new_location,
        "status":        "PROPOSED – awaiting approval",
        "note": (
            "Confirm with execute_action() to update the asset record."
        ),
    }


# ── 6. execute_action ─────────────────────────────────────────────────────────
def execute_action(action: dict, performed_by: str = "agent") -> dict:
    """
    Commits an approved PROPOSED action to the database and logs it.
    Re-runs all validation before writing so a stale or tampered proposal
    is rejected cleanly.

    Supported action_type values:
        "schedule_maintenance"  – updates last_maintenance to proposed date
        "reallocate_asset"      – updates dept and location

    Returns {"success": True, ...} or {"success": False, "error": ...}.
    """
    action_type = action.get("action_type")
    asset_id    = action.get("asset_id")

    if not asset_id or not action_type:
        return {"success": False, "error": "action_type and asset_id are required."}

    # Re-validate before writing.
    if action_type == "schedule_maintenance":
        check = schedule_maintenance(asset_id)
    elif action_type == "reallocate_asset":
        check = reallocate_asset(
            asset_id,
            action.get("to_dept", ""),
            action.get("to_location", ""),
        )
    else:
        return {"success": False, "error": f"Unknown action_type: '{action_type}'."}

    if "error" in check:
        return {"success": False, "error": check["error"]}

    # Validation passed — write to DB.
    conn = get_connection()
    try:
        if action_type == "schedule_maintenance":
            new_date = action.get("proposed_maintenance_date", TODAY.isoformat())
            conn.execute(
                "UPDATE assets SET last_maintenance = ? WHERE id = ?",
                (new_date, asset_id),
            )

        elif action_type == "reallocate_asset":
            conn.execute(
                "UPDATE assets SET dept = ?, location = ? WHERE id = ?",
                (action["to_dept"], action["to_location"], asset_id),
            )

        conn.execute(
            """INSERT INTO actions_log (asset_id, action_type, details, performed_by)
               VALUES (?, ?, ?, ?)""",
            (asset_id, action_type, json.dumps(action), performed_by),
        )
        conn.commit()
        return {
            "success":     True,
            "action_type": action_type,
            "asset_id":    asset_id,
            "timestamp":   datetime.now().astimezone().isoformat(timespec="seconds"),
        }

    except sqlite3.Error as e:
        conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


# ── smoke test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    SEP = "─" * 60

    def show(label: str, obj):
        print(f"\n{SEP}")
        print(f"  {label}")
        print(SEP)
        if isinstance(obj, pd.DataFrame):
            print(obj.to_string(index=False))
        else:
            print(json.dumps(obj, indent=2, ensure_ascii=False))

    # ── happy-path searches ───────────────────────────────────────────────────
    show("search_assets('laptop') — first 5 rows",
         search_assets("laptop")[["id", "type", "dept", "status"]].head())

    show("get_high_risk_assets(60) — top 3",
         get_high_risk_assets(60)[["id", "repair_risk", "status", "reason"]].head(3))

    # ── pick a valid (Active/Idle) asset and a decommissioned one ─────────────
    conn = get_connection()
    valid_row = conn.execute(
        "SELECT * FROM assets WHERE status IN ('Active','Idle') LIMIT 1"
    ).fetchone()
    decomm_row = conn.execute(
        "SELECT * FROM assets WHERE status = 'Decommissioned' LIMIT 1"
    ).fetchone()
    repair_row = conn.execute(
        "SELECT * FROM assets WHERE status = 'Under Repair' LIMIT 1"
    ).fetchone()
    conn.close()

    valid_id  = valid_row["id"]   if valid_row  else None
    decomm_id = decomm_row["id"] if decomm_row else None
    repair_id = repair_row["id"] if repair_row else None

    # ── schedule_maintenance: happy path ─────────────────────────────────────
    if valid_id:
        show(f"schedule_maintenance('{valid_id}') — valid asset [no DB write]",
             schedule_maintenance(valid_id))

    # ── ERROR: non-existent asset ─────────────────────────────────────────────
    show("schedule_maintenance('ASSET-9999') — ERROR: not found",
         schedule_maintenance("ASSET-9999"))

    # ── ERROR: decommissioned asset ───────────────────────────────────────────
    if decomm_id:
        show(f"schedule_maintenance('{decomm_id}') — ERROR: Decommissioned",
             schedule_maintenance(decomm_id))

    # ── reallocate_asset: happy path (different dept guaranteed) ──────────────
    if valid_id:
        current_dept = valid_row["dept"]
        # Pick any dept that is NOT the current one.
        other_dept = next(
            d for d in [
                "Computer Science", "Biology", "Mechanical Engineering",
                "Library", "Administration", "Physics", "Chemistry",
                "Architecture", "Medical School", "Student Affairs",
            ]
            if d != current_dept
        )
        show(f"reallocate_asset('{valid_id}', '{other_dept}', 'Building Z') — valid",
             reallocate_asset(valid_id, other_dept, "Building Z - Room 1"))

    # ── ERROR: same department ────────────────────────────────────────────────
    if valid_id:
        show(f"reallocate_asset — ERROR: same department ('{valid_row['dept']}')",
             reallocate_asset(valid_id, valid_row["dept"], "Building Z - Room 1"))

    # ── ERROR: Under Repair ───────────────────────────────────────────────────
    if repair_id:
        show(f"reallocate_asset('{repair_id}') — ERROR: Under Repair",
             reallocate_asset(repair_id, "Library", "Main Library"))

    # ── ERROR: Decommissioned ─────────────────────────────────────────────────
    if decomm_id:
        show(f"reallocate_asset('{decomm_id}') — ERROR: Decommissioned",
             reallocate_asset(decomm_id, "Physics", "Building A"))

    # ── execute_action: verify it re-validates and blocks bad proposals ────────
    show("execute_action with Decommissioned proposal — ERROR expected",
         execute_action({
             "action_type": "schedule_maintenance",
             "asset_id":    decomm_id or "ASSET-9999",
             "proposed_maintenance_date": TODAY.isoformat(),
         }))

    # execute_action is NOT called with a valid proposal here.
    # The real database stays untouched. Call execute_action() from the agent.
    print(f"\n{SEP}")
    print("  execute_action with valid proposal — SKIPPED (DB stays clean)")
    print(SEP)

    # ── confirm log is still empty ────────────────────────────────────────────
    conn = get_connection()
    log_count = conn.execute("SELECT COUNT(*) FROM actions_log").fetchone()[0]
    conn.close()
    print(f"\n✅  actions_log rows after smoke test: {log_count}  (expected 0)")
