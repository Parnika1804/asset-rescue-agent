# Asset Replacement Policy

## 1. Purpose

This policy defines the criteria and process for retiring end-of-life assets and procuring replacements, ensuring departments always have functional, up-to-date equipment.

---

## 2. Scope

All assets in the system with `status` of Active, Idle, or Under Repair. Decommissioned assets are outside scope.

---

## 3. Replacement Thresholds

An asset qualifies for replacement review when **any** of the following conditions are met:

| Condition                              | Threshold            | Risk Points Added |
|----------------------------------------|----------------------|-------------------|
| Asset age                              | ≥ 8 years            | 33 pts            |
| Cumulative failures                    | ≥ 4 failures         | 34 pts            |
| Days since last maintenance            | ≥ 548 days           | 33 pts            |
| Repair cost > 60% of replacement cost  | Manual assessment    | Triggers review   |

- A **combined repair_risk score ≥ 80** automatically creates a replacement recommendation in the system.

---

## 4. Asset Categories and Expected Lifespan

| Category            | Expected Lifespan | Replacement Cycle |
|---------------------|-------------------|-------------------|
| Laptops & Desktops  | 5 – 7 years       | 5 years           |
| Servers             | 6 – 8 years       | 7 years           |
| Lab Instruments     | 8 – 10 years      | 8 years           |
| Projectors / AV     | 6 – 8 years       | 7 years           |
| Network Equipment   | 6 – 8 years       | 7 years           |

---

## 5. Replacement Process

1. **Flag:** System sets asset `status = "Decommissioned"` when repair_risk ≥ 80 or asset age exceeds its lifespan.
2. **Review:** IT Asset Manager verifies the flag and confirms physical condition within **14 days**.
3. **Approve:** Department head submits a Purchase Request referencing the asset ID.
4. **Procure:** Procurement team issues tender or framework purchase within **30 days** of approval.
5. **Retire:** Old asset is logged with `action_type = "decommission"` and disposed of per the university's e-waste policy.
6. **Register:** Replacement asset is registered in the system with a new `ASSET-XXXX` ID before being deployed.

---

## 6. Budget Planning

Departments must maintain a rolling 3-year asset replacement forecast using the system's age and risk data. The IT department publishes an annual forecast report each October.

---

## 7. Exceptions

Exceptions to the replacement thresholds (e.g., a specialised instrument with no available replacement) must be approved in writing by the IT Director and reviewed annually.
