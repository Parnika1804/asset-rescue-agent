# Maintenance Policy

## 1. Purpose

This document defines the scheduled and reactive maintenance rules for all university assets tracked in the Asset Rescue Agent system. The goal is to minimise unplanned downtime and extend the useful life of equipment.

---

## 2. Scope

Applies to all physical assets registered in the system, including laptops, desktops, lab equipment, servers, projectors, and smart boards across all departments.

---

## 3. Maintenance Intervals

| Asset Category      | Required Interval | Warning Threshold | Critical Trigger |
|---------------------|-------------------|-------------------|------------------|
| Computers & Servers | Every 12 months   | 365 days          | 548 days         |
| Lab Equipment       | Every 12 months   | 365 days          | 548 days         |
| AV & Projectors     | Every 12 months   | 365 days          | 548 days         |
| Network Devices     | Every 12 months   | 365 days          | 548 days         |

- **Warning threshold (365 days):** System flags asset with medium risk (+18 pts). Department head notified.
- **Critical trigger (548 days / 18 months):** System flags asset with high risk (+33 pts). Maintenance *must* be scheduled within 14 days.

---

## 4. Risk Score Contribution

Maintenance history contributes up to **33 points** of the total repair risk score (0–100):

- 0 – 364 days since last maintenance: **0 points**
- 365 – 547 days: **18 points**
- 548+ days (18 months): **33 points**

---

## 5. Scheduling Process

1. The system generates a `schedule_maintenance` proposal via `tools.py`.
2. Department head or IT coordinator reviews the proposal.
3. Approved proposals are committed using `execute_action()`, which updates `last_maintenance` in the database and logs the action.
4. The technician who performed the maintenance must also update the physical asset tag.

---

## 6. Emergency Maintenance

Assets with **4 or more recorded failures** must be inspected within **48 hours** regardless of their scheduled interval. Status is automatically set to *Under Repair* until cleared.

---

## 7. Record Keeping

All maintenance actions are stored in the `actions_log` table with a timestamp, the acting user, and full action details in JSON format for auditability.
