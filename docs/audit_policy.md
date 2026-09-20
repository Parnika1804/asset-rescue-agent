# Asset Audit Policy

## 1. Purpose

Regular audits verify that the physical inventory matches the digital records in the system, ensure compliance with maintenance schedules, and identify assets that need corrective action.

---

## 2. Scope

All assets registered in the `assets` table of the SQLite database, across every department and campus location.

---

## 3. Audit Frequency

| Audit Type        | Frequency   | Trigger |
|-------------------|-------------|---------|
| Full Inventory    | Annually    | Start of each academic year (September) |
| Departmental Spot | Quarterly   | First week of each quarter |
| High-Risk Review  | Monthly     | Automated — all assets with repair_risk ≥ 60 |
| Post-Incident     | Within 48 h | After any asset failure or security event |

---

## 4. Risk Score Audit Trigger

Assets are automatically escalated for audit review based on their risk score:

- **Score 40–59 (Medium Risk):** Include in next quarterly spot audit.
- **Score 60–79 (High Risk):** Review within the current month.
- **Score 80–100 (Critical Risk):** Immediate review required within **7 days**.

---

## 5. Audit Steps

1. Export the current asset register from the system (Dashboard → download).
2. Physically verify each asset: confirm presence, condition, and location match the database.
3. Record any discrepancies in the `actions_log` with `action_type = "audit_discrepancy"`.
4. Submit a signed audit report to the IT Asset Manager within **5 business days** of completion.

---

## 6. Data Integrity Rules

- No asset record may be deleted; set `status = "Decommissioned"` instead.
- Any manual database edit must be accompanied by a log entry explaining the change.
- The `actions_log` table is append-only — existing entries must never be modified.

---

## 7. Compliance & Reporting

Audit results feed into the annual university compliance report. Departments with more than **10% discrepancy** rate face a mandatory corrective action review within 30 days.
