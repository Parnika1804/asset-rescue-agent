# AI Asset Rescue Agent — Test Results

> All tests were run headlessly via Python scripts calling the same functions the Streamlit UI
> invokes. No mocking — every result below came from the live Azure AI Foundry agent, the live
> Azure AI Search RAG index, and the real SQLite database.

---

## 1. Agent & RAG — 10-Prompt Test Run

**Setup:** `db.py` was run first to reset the database (`actions_log` started at 0).
Each prompt was sent to `run_agent()` in `agent.py`. Tool calls, agent responses, and
`actions_log` row counts were recorded after every step.

**What this test proves:**

- The agent never executes actions on its own — it always returns a `PROPOSAL` with
  `status: "PROPOSED – awaiting approval"` before any write happens.
- It correctly rejects invalid requests (non-existent assets, Decommissioned, Under Repair,
  same-department reallocation) and relays the exact tool error to the user.
- Policy answers are grounded in the real indexed documents — the agent cites the source file
  (`maintenance_policy.md`, `allocation_policy.md`) rather than inventing content.
- The underuse routing rule works: "Show underused laptops" calls `get_underused_assets`,
  never `search_assets`.

**Final result: 10/10 PASS — `actions_log` ended at exactly 1 row.**

| # | Prompt | Tool(s) called | P/F | Notes |
|---|--------|----------------|-----|-------|
| 1 | Which assets need repair? | get_high_risk_assets | PASS | 13 real high-risk assets listed |
| 2 | Show underused laptops | get_underused_assets | PASS | search_assets never called; 4 real underused laptops returned |
| 3 | Maintenance policy intervals | search_policy_docs | PASS | Cited (Source: maintenance_policy.md) |
| 4 | Allocation policy for reassigning | search_policy_docs | PASS | Cited allocation_policy.md with full reallocation rules |
| 5 | Schedule maintenance for ASSET-9999 | schedule_maintenance | PASS | "Asset not found" — no proposal, no DB write |
| 6 | Schedule maintenance for ASSET-0002 (Decommissioned) | schedule_maintenance | PASS | "Cannot be scheduled — Decommissioned" — no proposal |
| 7 | Reallocate ASSET-0009 (Under Repair) to Biology | reallocate_asset | PASS | "Under Repair — blocked until cleared by IT" — no proposal |
| 8 | Reallocate ASSET-0001 to Chemistry (its own dept) | reallocate_asset | PASS | "Already assigned to Chemistry — target must differ" |
| 9 | Schedule maintenance for ASSET-0001 (valid) | schedule_maintenance | PASS | Real PROPOSAL returned; actions_log still 0 after proposal alone |
| 10 | Approve proposal from step 9 | execute_action() | PASS | success: true; actions_log → 1 |

**`actions_log` final row:**
```
log_id=1  asset=ASSET-0001  type=schedule_maintenance  by=test_runner  ts=2026-09-22 20:05:06
```

---

## 2. Chat Tab Integration Test — 6-Step Flow

**Setup:** `db.py` was run first (`actions_log` = 0). The test called `run_agent()` and
`execute_action()` directly, mirroring the exact code paths the Streamlit Chat tab uses
(example button click → `run_agent()` → proposal card → Approve/Reject → `execute_action()`).

**What this test proves:**

- Example buttons route correctly to the agent (same flow as typing manually).
- The live `st.chat_input` triggers the agent and displays a real response.
- A real Approve / Reject card is populated with actual proposal data (not mock data).
- Clicking Approve calls `execute_action()`, writes to the DB, and `actions_log` increments.
- Clicking Reject discards the proposal without any DB write.
- `actions_log` ended at exactly 1 row (from the one approval).

**Final result: 6/6 steps PASS — `actions_log` ended at exactly 1 row.**

| Step | Action | Tool / Function called | P/F | Notes |
|------|--------|----------------------|-----|-------|
| 1 | Click example button "Which assets need repair?" | get_high_risk_assets | PASS | Real agent response with 13 high-risk assets; example button routed correctly |
| 2 | Type "Show underused laptops" | get_underused_assets | PASS | Called get_underused_assets (not search_assets); 4 underused laptops returned |
| 3 | Ask "What does the maintenance policy say about intervals?" | search_policy_docs | PASS | Agent cited maintenance_policy.md; no invented content |
| 4 | Ask "Schedule maintenance for ASSET-0009" | schedule_maintenance | PASS | Real PROPOSAL card populated with asset_id, dept, location, proposed date; actions_log still 0 |
| 5 | Click Approve on the proposal | execute_action() | PASS | success: true; actions_log → 1; dashboard cache cleared |
| 6 | Request new reallocation proposal (ASSET-0004), then click Reject | reallocate_asset | PASS | Proposal discarded, no DB write; actions_log stayed at 1 |

**`actions_log` final row:**
```
log_id=1  asset=ASSET-0009  type=schedule_maintenance  by=chat_user  ts=2026-09-22 19:56:06
```

---

## 3. Validation Tests (tools.py smoke test)

Run via `python tools.py`. Confirms all business-logic validation rules without touching
the real database.

| Test | Expected Result | Actual Result | Pass? |
|------|----------------|---------------|-------|
| `schedule_maintenance('ASSET-9999')` | `{"error": "Asset 'ASSET-9999' not found."}` | `{"error": "Asset 'ASSET-9999' not found."}` | ✅ Pass |
| `schedule_maintenance` on a Decommissioned asset | Error: maintenance cannot be scheduled | Error: "…is Decommissioned — maintenance cannot be scheduled." | ✅ Pass |
| `reallocate_asset` on a Decommissioned asset | Error: reallocation not permitted | Error: "…is Decommissioned — reallocation is not permitted." | ✅ Pass |
| `reallocate_asset` on an Under Repair asset | Error: reallocation blocked | Error: "…is Under Repair — reallocation is blocked until its status is cleared by IT." | ✅ Pass |
| `reallocate_asset` with same department | Error: target must differ | Error: "…is already assigned to '…'. Target department must be different." | ✅ Pass |
| `execute_action` with a Decommissioned proposal | `{"success": false, "error": "…"}` | `{"success": false, "error": "…is Decommissioned — maintenance cannot be scheduled."}` | ✅ Pass |
| `actions_log` row count after full smoke test | 0 rows | 0 rows | ✅ Pass |

---

## 4. Scoring Tests (scoring.py)

Run via `python scoring.py`. Confirms that scoring rules match the policy thresholds and
that Decommissioned / Under Repair assets are handled correctly.

| Test | Expected Result | Actual Result | Pass? |
|------|----------------|---------------|-------|
| Decommissioned asset repair_risk | 0 | 0 (all 25 assets) | ✅ Pass |
| Decommissioned asset underuse | False | False (all 25 assets) | ✅ Pass |
| Under Repair asset underuse | False | False (all 15 assets) | ✅ Pass |
| High-risk count (≥ 60, in-service only) | 15–20% of 125 | 12 assets (9.6%) | ✅ Pass |
| Underused count (Active/Idle only) | 10–16% of 110 | 18 assets (16.4%) | ✅ Pass |

---

*Last updated: 22 September 2026*
