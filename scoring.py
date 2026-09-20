"""
scoring.py
Calculates a repair_risk score (0–100) and underuse flag for every asset,
plus a plain-English reason string explaining the score.

Run standalone:  python scoring.py
Import anywhere: from scoring import score_assets
"""

import pandas as pd
from datetime import date
from db import get_connection

# ── fixed "today" so scores stay deterministic with our generated data ────────
TODAY = date(2026, 9, 20)


# ── thresholds (also referenced in the policy docs) ──────────────────────────
MAINTENANCE_WARN_DAYS  = 365   # 12 months → medium risk (matches policy "action trigger")
MAINTENANCE_HIGH_DAYS  = 548   # 18 months → high risk
FAILURE_WARN           = 2     # 2+ failures → medium risk
FAILURE_HIGH           = 4     # 4+ failures → high risk
AGE_WARN_YEARS         = 5     # 5+ years old → medium risk
AGE_HIGH_YEARS         = 8     # 8+ years old → high risk
# Underuse is age-relative: expected ~500 hrs/yr for active equipment.
# An asset is underused when its hours are < 25% of the age-expected hours,
# with a floor of 200 hrs (matches "< 200 hrs" in allocation_policy.md).
UNDERUSE_EXPECTED_HRS_PER_YEAR = 500
UNDERUSE_RATIO                 = 0.25   # below 25% of expected → underused
UNDERUSE_MIN_HOURS             = 200    # hard floor from policy


def score_assets(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Accept a DataFrame (or load from DB if none given).
    Returns the same DataFrame with three new columns:
        repair_risk  – integer 0-100
        underuse     – bool
        reason       – plain-English explanation
    """
    if df is None:
        conn = get_connection()
        df = pd.read_sql("SELECT * FROM assets", conn)
        conn.close()

    df = df.copy()

    # ── convert date strings to actual dates ──────────────────────────────────
    df["purchase_date"]    = pd.to_datetime(df["purchase_date"]).dt.date
    df["last_maintenance"] = pd.to_datetime(df["last_maintenance"]).dt.date

    # ── derived numeric features ──────────────────────────────────────────────
    df["days_since_maintenance"] = df["last_maintenance"].apply(
        lambda d: (TODAY - d).days
    )
    df["age_years"] = df["purchase_date"].apply(
        lambda d: (TODAY - d).days / 365.25
    )
    df["failures"]    = df["failures"].astype(int)
    df["usage_hours"] = df["usage_hours"].astype(int)

    # ── score components (each 0–33 points, total capped at 100) ─────────────
    def maintenance_score(days: int) -> int:
        if days >= MAINTENANCE_HIGH_DAYS:
            return 33
        elif days >= MAINTENANCE_WARN_DAYS:
            return 18
        return 0

    def failure_score(failures: int) -> int:
        if failures >= FAILURE_HIGH:
            return 34
        elif failures >= FAILURE_WARN:
            return 17
        return 0

    def age_score(years: float) -> int:
        if years >= AGE_HIGH_YEARS:
            return 33
        elif years >= AGE_WARN_YEARS:
            return 18
        return 0

    # ── only score Active / Idle / Under Repair assets ───────────────────────
    # Decommissioned assets get risk=0, underuse=False, fixed reason string.
    SCOREABLE = {"Active", "Idle", "Under Repair"}
    scoreable_mask = df["status"].isin(SCOREABLE)

    raw_risk = (
        df["days_since_maintenance"].apply(maintenance_score)
        + df["failures"].apply(failure_score)
        + df["age_years"].apply(age_score)
    ).clip(upper=100)

    df["repair_risk"] = raw_risk.where(scoreable_mask, other=0)

    # ── underuse flag (age-relative, floor at UNDERUSE_MIN_HOURS) ─────────────
    # Expected hours = age_years * 500; underused if actual < 25% of expected
    # OR below the hard floor of 200 hrs (per allocation_policy.md section 4).
    # Only Active and Idle assets can be flagged underused:
    #   - Decommissioned: already retired, scoring skipped entirely.
    #   - Under Repair: low hours are expected while offline; cannot be
    #     reallocated until cleared (allocation_policy.md section 7).
    UNDERUSE_ELIGIBLE = {"Active", "Idle"}

    def is_underused(row) -> bool:
        if row["status"] not in UNDERUSE_ELIGIBLE:
            return False
        expected = max(1.0, row["age_years"]) * UNDERUSE_EXPECTED_HRS_PER_YEAR
        return (row["usage_hours"] < UNDERUSE_RATIO * expected
                or row["usage_hours"] < UNDERUSE_MIN_HOURS)

    df["underuse"] = df.apply(is_underused, axis=1)

    # ── plain-English reason ──────────────────────────────────────────────────
    def build_reason(row) -> str:
        # Decommissioned assets need no scoring — exit immediately.
        if row["status"] == "Decommissioned":
            return "Decommissioned — no action needed."

        parts = []

        # maintenance
        if row["days_since_maintenance"] >= MAINTENANCE_HIGH_DAYS:
            parts.append(
                f"No maintenance in {row['days_since_maintenance']} days "
                f"(critical threshold: {MAINTENANCE_HIGH_DAYS} days)."
            )
        elif row["days_since_maintenance"] >= MAINTENANCE_WARN_DAYS:
            parts.append(
                f"Maintenance overdue — {row['days_since_maintenance']} days "
                f"since last service (warning threshold: {MAINTENANCE_WARN_DAYS} days)."
            )

        # failures
        if row["failures"] >= FAILURE_HIGH:
            parts.append(
                f"High failure count: {row['failures']} failures recorded."
            )
        elif row["failures"] >= FAILURE_WARN:
            parts.append(f"{row['failures']} failures recorded — monitor closely.")

        # age
        age_y = round(row["age_years"], 1)
        if row["age_years"] >= AGE_HIGH_YEARS:
            parts.append(f"Asset is {age_y} years old — beyond replacement threshold ({AGE_HIGH_YEARS} yrs).")
        elif row["age_years"] >= AGE_WARN_YEARS:
            parts.append(f"Asset is {age_y} years old — approaching end of life ({AGE_WARN_YEARS} yr threshold).")

        # underuse
        if row["underuse"]:
            expected = round(max(1.0, row["age_years"]) * UNDERUSE_EXPECTED_HRS_PER_YEAR)
            parts.append(
                f"Only {row['usage_hours']} usage hours logged "
                f"(expected ≥ {int(UNDERUSE_RATIO * expected)} hrs for a "
                f"{round(row['age_years'], 1)}-year-old asset) — consider reallocation."
            )

        if not parts:
            return "No issues detected. Asset is in good standing."

        return " ".join(parts)

    df["reason"] = df.apply(build_reason, axis=1)

    return df


# ── entry point ───────────────────────────────────────────────────────────────
def main():
    scored = score_assets()
    print(f"✅  Scored {len(scored)} assets.")

    high_risk = scored[scored["repair_risk"] >= 60].sort_values(
        "repair_risk", ascending=False
    )
    print(f"\n🔴  High-risk assets (score ≥ 60): {len(high_risk)}")
    cols = ["id", "type", "dept", "repair_risk", "reason"]
    print(high_risk[cols].to_string(index=False))

    underused = scored[scored["underuse"]]
    print(f"\n🟡  Underused assets: {len(underused)}")
    print(underused[["id", "type", "dept", "status", "usage_hours",
                      "age_years", "reason"]].to_string(index=False))


if __name__ == "__main__":
    main()
