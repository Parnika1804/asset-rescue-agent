"""
make_data.py
Generates data/assets.csv with 150 realistic university asset rows.
Run: python make_data.py
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

# ── reproducible randomness ──────────────────────────────────────────────────
random.seed(42)

# ── lookup tables ────────────────────────────────────────────────────────────
ASSET_TYPES = [
    "Laptop", "Desktop PC", "Projector", "Lab Microscope",
    "3D Printer", "Server", "Tablet", "Smart Board",
    "Network Switch", "Oscilloscope",
]

DEPARTMENTS = [
    "Computer Science", "Biology", "Mechanical Engineering",
    "Library", "Administration", "Physics", "Chemistry",
    "Architecture", "Medical School", "Student Affairs",
]

LOCATIONS = [
    "Building A - Room 101", "Building B - Room 204",
    "Building C - Lab 1",   "Building D - Office 3",
    "Main Library",         "Server Room",
    "Engineering Hall",     "Science Block - Room 5",
    "Admin Block",          "Med Campus - Lab 2",
]

STATUSES = ["Active", "Active", "Active", "Idle", "Idle", "Under Repair", "Decommissioned"]


# ── helper: random date between two dates ────────────────────────────────────
def rand_date(start: date, end: date) -> date:
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


# ── generate rows ─────────────────────────────────────────────────────────────
def generate_assets(n: int = 150) -> list[dict]:
    today = date(2026, 9, 20)          # fixed "today" so data stays consistent
    rows = []

    for i in range(1, n + 1):
        purchase_date = rand_date(date(2018, 1, 1), date(2024, 12, 31))
        age_years = (today - purchase_date).days / 365.25

        # ── last_maintenance: bias toward recent (within 2 yrs) for most assets ──
        # ~70% of assets: maintained within last 2 years
        # ~30%: maintained somewhere between purchase and 2 years ago (old/neglected)
        two_years_ago = today - timedelta(days=730)
        if random.random() < 0.70 and two_years_ago > purchase_date:
            last_maintenance = rand_date(two_years_ago, today)
        else:
            last_maintenance = rand_date(purchase_date, today)

        # ── usage_hours: age-scaled so underuse is realistic ──────────────────
        # Expected ~500 hrs/yr for active equipment; underused assets get much less.
        # ~12% chance an asset is low-usage (flag candidates for underuse scoring)
        if random.random() < 0.12:
            # Low-usage: 20–150 hrs regardless of age
            usage_hours = int(random.uniform(20, 150))
        else:
            # Normal use: scale by age, with some variance
            expected = age_years * 500
            usage_hours = max(200, int(random.triangular(expected * 0.4,
                                                          expected * 2.0,
                                                          expected)))

        failures = random.choices([0, 1, 2, 3, 4, 5], weights=[40, 25, 15, 10, 6, 4])[0]

        # derive a realistic status
        if failures >= 4:
            status = "Under Repair"
        elif age_years > 6:
            status = random.choice(["Idle", "Decommissioned"])
        elif usage_hours < 200:
            status = "Idle"
        else:
            status = "Active"

        rows.append({
            "id":               f"ASSET-{i:04d}",
            "type":             random.choice(ASSET_TYPES),
            "dept":             random.choice(DEPARTMENTS),
            "location":         random.choice(LOCATIONS),
            "purchase_date":    purchase_date.isoformat(),
            "last_maintenance": last_maintenance.isoformat(),
            "usage_hours":      usage_hours,
            "failures":         failures,
            "status":           status,
        })

    return rows


# ── write CSV ─────────────────────────────────────────────────────────────────
def main():
    out_path = Path("data/assets.csv")
    out_path.parent.mkdir(exist_ok=True)

    assets = generate_assets(150)
    fieldnames = ["id", "type", "dept", "location",
                  "purchase_date", "last_maintenance",
                  "usage_hours", "failures", "status"]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(assets)

    print(f"✅  Generated {len(assets)} rows → {out_path}")

    # quick sanity check
    status_counts = {}
    for a in assets:
        status_counts[a["status"]] = status_counts.get(a["status"], 0) + 1
    print("   Status breakdown:", status_counts)


if __name__ == "__main__":
    main()
