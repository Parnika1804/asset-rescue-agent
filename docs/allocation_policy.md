# Asset Allocation Policy

## 1. Purpose

This policy governs how university assets are assigned to departments, monitored for utilisation, and reallocated when usage falls below acceptable levels. Efficient allocation ensures every asset delivers value to the institution.

---

## 2. Scope

Covers all movable assets registered in the system: computers, tablets, lab instruments, AV equipment, and shared peripherals.

---

## 3. Initial Allocation

1. New assets are registered with a primary department and location at point of purchase.
2. Every asset must have a single responsible department at all times.
3. Shared assets (e.g., projectors used by multiple rooms) are assigned to the department with the highest usage.

---

## 4. Underutilisation Thresholds

| Usage Hours (lifetime)                          | Classification     | Action Required            |
|-------------------------------------------------|--------------------|----------------------------|
| ≥ 25% of age-expected hours (500 hrs/yr)        | Normal use         | No action                  |
| < 25% of age-expected hours **or** < 200 hrs    | Underused          | Review within 30 days      |
| < 50 hours and > 1 year old                     | Severely underused | Reallocate or decommission |

- The system flags an asset as underused when its recorded hours are below **25% of the age-expected total** (based on 500 hrs/yr of typical use), or when total hours are below the hard floor of **200 hours** — whichever condition is met first.
- Underuse is evaluated for assets with status **Active** or **Idle** only. Assets with status `"Under Repair"` are excluded because low hours during a repair period are expected, and they cannot be reallocated until cleared (see section 7).
- A reallocation proposal is generated automatically by `tools.py`.

---

## 5. Reallocation Process

1. The system proposes a `reallocate_asset` action via `tools.py`, specifying the new department and location.
2. Both the sending and receiving department heads must acknowledge the transfer.
3. An IT coordinator commits the approved transfer using `execute_action()`.
4. The physical asset tag must be updated within **5 business days** of the system update.

---

## 6. Temporary Loans

- Assets may be temporarily loaned between departments for up to **30 days** without a formal reallocation.
- Loans exceeding 30 days must be formalised as a full reallocation.

---

## 7. Prohibited Reallocation

Assets with `status = "Under Repair"` or `status = "Decommissioned"` cannot be reallocated until their status is cleared by IT.
