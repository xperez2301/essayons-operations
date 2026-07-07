# PRC-0008 — Full Operational Simulation Report

**Mission:** PRC-0008 — Full Operational Simulation
**Role:** Claude, acting as Simulation Director
**Authority:** Bastion (Chief Architect) — final certification remains Bastion's after Commander live validation
**Branch:** ft3-automation-worker
**Date:** 2026-07-07
**Status:** Simulation plan complete. Not certified. Not live-executed.

---

## 1. Purpose and Scope

This mission validates that the seven certified EOMS workspaces (Platform, Dispatch, Driver, Receiving, Dispatcher Close-Out, Inventory, Reporting) function as **one closed-loop system**, not just as individually correct modules. No architecture was changed, no features were added, and no code was modified during this mission.

## 2. Methodology

Live execution requires a running app with seeded data and multiple user sessions, which is outside what I can do from this seat. Instead, I performed a full source-level trace of the operational chain for every required scenario, following actual data as it moves through:

`app.py routes → recovery_center_service → driver_center_service → receiving_service → dispatcher_closeout_service → inventory_service → fulfillment_service → reporting_service → command_center_service`

Every state transition, guard condition, and status string below is taken directly from the current code, not assumed. Where a scenario's outcome depends on something only observable at runtime (timing, UI behavior, real concurrent requests), that's flagged explicitly as something Xavier needs to confirm live — it is not treated as passed.

---

## 3. Simulation Plan — 15 Required Scenarios

### 1. Standard Recovery Route
**Initial State:** One store record, `status: Unassigned`, valid BOL, city/hub set, no route assigned.
**Operational Steps:**
1. Dispatcher assigns the store to a driver via `/api/assign-route` (requires `status == "Unassigned"`).
2. Dispatcher dispatches the route via `/api/dispatch-route`.
3. Driver accepts the route via `/api/driver/accept-route`.
4. Driver submits component counts via `/api/driver/save-counts`.
5. Driver completes the stop via `/api/driver/complete-stop`.
6. Warehouse receives the load via `/api/receiving/receive` with verified counts.
7. Dispatcher closes the BOL via `/api/dispatcher/closeout`.
**Expected State Changes:** `status`: Unassigned → Assigned → Recovered → Completed. `receiving_status`: "" → Pending → Received. `dispatcher_closeout_status`: "" → Pending → Closed.
**Inventory Effects:** Zero effect until step 7. After close-out, one "Good Inventory" transaction per component with `quantity > 0`, keyed to this BOL's `inventory_transaction_id`.
**Reporting Effects:** Store is invisible to Reporting until `dispatcher_closeout_status == "Closed"`. After close-out it appears in `recovered_stops`, contributes to `estimated_recovery_weight` using **warehouse-verified** counts (per the FT4.7 fix), and appears in `inventory`/`receiving` KPIs.
**Executive Dashboard Effects:** Command Center reflects the Recovered stop immediately after step 5 (it is a live view, not close-out-gated) — this is expected, see Scenario 15.
**Audit Trail:** `audit_history` gets "Driver Completion" and "Warehouse Verification" entries (backfilled at close-out via `ensure_operational_audit_history`), then a "Dispatcher Approval" entry with the driver/verified count diff.
**Pass Criteria:** All 3 status fields land in their terminal state; Inventory and Reporting are unaffected until close-out; audit_history has all three event types in chronological order.

### 2. Multi-stop Route
**Initial State:** 3 unassigned stores, same hub, one driver.
**Operational Steps:** Assign all 3 in one `/api/assign-route` call → dispatch → driver accepts → complete stop 1 → complete stop 2 → complete stop 3.
**Expected State Changes:** `promote_next_waiting_stop` keeps exactly one stop at `driver_work_status: Current` at a time; `advance_next_driver_stop` promotes the next stop only after the prior one reaches Recovered/Exception. Route `status` becomes "Recovered" only once **all 3** stops are terminal.
**Inventory Effects:** None until each BOL individually clears Dispatcher Close-Out — closing is per-BOL, not per-route.
**Reporting Effects:** Each BOL enters Reporting independently as it's individually closed; a partially-closed route contributes only its closed stops.
**Executive Dashboard Effects:** `route.recovery_progress` (`recovered_stops`/`remaining_stops`) updates after each stop; Driver workspace `waiting_count` decrements per stop.
**Audit Trail:** Three independent audit trails, one per BOL — no shared state between stops besides the route grouping.
**Pass Criteria:** Stops are strictly sequential (never two "Current" stops at once); route only reaches "Recovered" after the last stop; no component-count bleed between stops.

### 3. Multiple BOL Route
**Initial State:** One route, 2–3 stores with distinct BOL numbers.
**Operational Steps:** Same as Scenario 2, through full close-out of every BOL on the route.
**Expected State Changes:** Each store retains its own distinct `bol` and `inventory_transaction_id` (`INV-{id or bol}`) throughout.
**Inventory Effects:** `inventory_receipt_transactions()` produces separate, BOL-tagged transaction rows per component/category — verify no aggregation collapses two BOLs' quantities together.
**Reporting Effects:** Operational timeline entries (Recovery, Receipt, Dispatcher Approval, Inventory Transaction, Shipment) each carry the correct BOL in `detail`.
**Executive Dashboard Effects:** `recent_activity` and `alerts` show distinct entries per BOL, not a route-level rollup.
**Audit Trail:** Every transaction/timeline row must be traceable to exactly one BOL.
**Pass Criteria:** Zero cross-BOL bleed anywhere — inventory totals, reporting totals, and timeline entries all attribute correctly by BOL.

### 4. Multiple Drivers (concurrent)
**Initial State:** 2 routes, 2 distinct drivers, disjoint store sets.
**Operational Steps:** Both drivers work simultaneously — accept, save counts, complete stops for their own stops, at the same time.
**Expected State Changes:** `store_matches_driver` blocks a driver from touching another driver's stop (`PermissionError`). This is enforced correctly in code.
**Inventory / Reporting Effects:** Same as Scenario 1, once each BOL clears close-out — independent per driver.
**Executive Dashboard Effects:** Both drivers' activity shows up correctly attributed.
**Audit Trail:** Each store's audit trail records the correct driver as operator.
**Pass Criteria (code-level):** Role isolation holds — a driver cannot act on another driver's stop.
**⚠ Live-only risk:** `stores.json`/`routes.json` are flat files read-modified-written per request (`read_json` → mutate → `write_json`), with no file lock and no optimistic-concurrency check. `write_json` is atomic (temp file + `os.replace`) so the file itself can't corrupt, but two near-simultaneous requests can still race: both read the file before either writes, and the second write silently discards the first driver's change (classic lost-update). This is not observable from static review — **must be tested live with two real concurrent submissions** (see §6).

### 5. Multiple Receiving Clerks (concurrent)
**Initial State:** 2+ loads pending receiving, 2 warehouse users (role `dispatcher` or `admin` — there is no distinct "clerk" role; anyone with dispatch/admin access can receive).
**Operational Steps:** Two users call `/api/receiving/receive` for **different** BOLs at the same time.
**Expected State Changes:** Each BOL's own record is updated; `already_received` guard prevents double-processing of the *same* BOL.
**Inventory/Reporting Effects:** Independent per BOL once closed.
**Pass Criteria (code-level):** No cross-BOL interference for different-store concurrent receiving.
**⚠ Live-only risk:** Same lost-update race as Scenario 4, now on `stores.json` writes from two receiving actions. **Must be tested live.**

### 6. Driver vs Warehouse Variance
**Initial State:** Driver submits counts that differ from what the warehouse later verifies (e.g., driver reports 10 Corner Posts, warehouse verifies 8).
**Operational Steps:** Standard flow through close-out, with `warehouse_verified_counts` deliberately set different from driver-submitted counts at the Receiving step.
**Expected State Changes:** `closeout_difference()` = verified − driver, per component. `variance` = verified_racks − expected_racks; `variance_review = True` when `abs(variance) >= 2`.
**Inventory Effects:** Inventory receipt is built from **verified** counts only (`receipt_counts_for_store` → `warehouse_verified_counts_from_store`) — driver's higher/lower number never enters inventory.
**Reporting Effects:** This is the direct regression test for the FT4.7 fix. `estimated_recovery_weight` must equal the warehouse-verified weight, **not** the driver-submitted weight. Before FT4.7 this was wrong (used driver counts); confirm it is now correct.
**Audit Trail:** The "Dispatcher Approval" audit event stores both `driver_counts` and `warehouse_verified_counts` plus the `difference` — the variance itself is fully auditable.
**Pass Criteria:** Inventory and Reporting both reflect verified counts; the variance is visible in the close-out audit record but never silently applied to stock.

### 7. Damaged Inventory
**Initial State:** Receiving submits `damage_counts["Damaged Inventory"]` with nonzero quantities for one or more components.
**Operational Steps:** Standard flow; at Receiving, populate the "Damaged Inventory" damage category.
**Expected State Changes:** `total_damaged_components()` > 0; `variance_review` may also trigger if damage caused a rack/piece shortfall.
**Inventory Effects:** `inventory_receipt_transactions()` emits a separate "Damaged Inventory" transaction (not "Good Inventory") for the damaged quantity; `category_inventory_totals()` correctly buckets it away from good stock.
**Reporting Effects:** Reporting's inventory numbers (via `build_inventory_workspace`) already exclude damaged stock from "available" by construction — confirm the Reporting KPI matches the Inventory workspace exactly for this BOL.
**Audit Trail:** `damage_counts`, `damaged_material`, `damage_notes` all persist on the store and are visible in the Warehouse Verification audit entry.
**Pass Criteria:** Damaged units are counted, tracked, and excluded from good/available stock, with full audit visibility.

### 8. Awaiting Repair
**Initial State:** Same as Scenario 7, using the `"Awaiting Repair"` damage category instead.
**Operational Steps / Effects:** Identical mechanism to Scenario 7, different bucket.
**Pass Criteria:** "Awaiting Repair" quantities are tracked as their own category, distinct from "Damaged Inventory" and "Returned to EZ Rack," and excluded from available/good stock.

### 9. Returned to EZ Rack
**Initial State:** Same pattern, using the `"Returned to EZ Rack"` category.
**Pass Criteria:** Same as above — category isolation confirmed across all three damage buckets plus "Good Inventory," and `Good = verified − sum(all three damage categories)` holds exactly (`category_inventory_totals` logic).

### 10. Zero Recovery / No Pickup
**Initial State:** Driver reports a "No Pickup" exception at a stop.
**Operational Steps:** `/api/driver/save-exception` with `driver_exception_type = "No Pickup"` (requires `no_pickup_manager_name`). This zeroes all four component fields and `collected_racks`/`collected_pieces`. Stop still proceeds to Receiving (verified counts will also be zero) and Dispatcher Close-Out.
**Expected State Changes:** `status: Exception`; at close-out, `recovery_result_status` is preserved as "Exception" (not overwritten by the generic "Completed" status).
**Inventory Effects:** `receipt_counts_for_store` returns all-zero; `inventory_receipt_transactions()` skips creating **any** transaction row for this BOL (both the "Good Inventory" branch and every damage branch are gated on `quantity/good_quantity` being truthy — zero is falsy). Confirm this: zero-recovery BOLs must contribute nothing to inventory, not a set of zero-value rows.
**Reporting Effects:** BOL appears in `exception_stops` with `0` weight contribution — no phantom material.
**Audit Trail:** "Dispatcher Approval" timeline entry still fires (BOL is still closed and auditable even though it moved nothing) — this now works correctly with the FT4.7 timeline addition.
**Pass Criteria:** No pickup ≠ no audit trail. The BOL is fully traceable end-to-end while correctly contributing zero material anywhere.

### 11. Duplicate Receiving Verification
**Initial State:** A load already has `receiving_status: Received`.
**Operational Steps:** Call `/api/receiving/receive` again for the same `store_id`.
**Expected State Changes:** `receive_load()` detects `is_received_store(store)` is already true and returns immediately with `already_received: True` — **no fields are re-written**, no duplicate history entry.
**Inventory Effects:** No duplicate transaction — `inventory_receipt_transactions()` only reads the store's single, final `warehouse_verified_counts`.
**Pass Criteria (code-level):** Verified — this guard is unconditional and correct.
**⚠ Live-only nuance:** This protects against duplicate *processing*, but if two duplicate requests race each other before either commits (see Scenario 5's concurrency note), both could pass the `is_received_store` check before either writes. Sequential double-clicks are safe; **truly simultaneous** duplicate submissions are the same race as Scenario 5 and should be tested live.

### 12. Duplicate Dispatcher Approval
**Initial State:** A BOL already has `dispatcher_closeout_status: Closed`.
**Operational Steps:** Call `/api/dispatcher/closeout` again for the same `store_id`.
**Expected State Changes:** `closeout_store()` detects the store is already closed and returns a copy with `already_closed: True` — no re-mutation, no duplicate `inventory_updated_at`/audit entry. `append_audit_event()` also independently dedupes by `(event, timestamp)`.
**Inventory/Reporting Effects:** No duplicate inventory transaction, no duplicate reporting entry — Law #6 (idempotency) holds by construction, since Reporting recomputes fresh from current state on every request rather than accumulating.
**Pass Criteria (code-level):** Verified — double-submit produces no double-counted inventory or reporting.
**⚠ Live-only nuance:** Same simultaneous-race caveat as Scenario 11 applies to two truly concurrent close-out clicks on the same BOL.

### 13. Inventory Audit Verification
**Initial State:** Several BOLs across the full range of scenarios above (mixed good/damaged/zero-recovery), all closed out.
**Operational Steps:** Pull `/inventory` workspace and cross-reference every line in `workspace.inventory.transactions` against the originating BOL's audit trail.
**Expected State Changes:** N/A (read-only verification).
**Inventory Effects:** Every inventory transaction must resolve to exactly one BOL, one component, one category, with `dispatcher_approval`/`dispatcher_approved_at` and `warehouse_verification`/`warehouse_verified_at` populated (`inventory_receipt_transactions()` fields).
**Pass Criteria:** 1:1 traceability from every inventory unit back to a specific BOL, warehouse verification, and dispatcher approval — no orphaned or unattributed inventory.

### 14. Reporting Audit Verification
**Initial State:** Same closed BOL set as Scenario 13.
**Operational Steps:** Pull `/reporting` and confirm every KPI traces to the underlying domain workspaces it wraps.
**Expected State Changes:** N/A (read-only verification).
**Reporting Effects:** `reporting.inventory` must equal `inventory` workspace exactly (same function call, same filtered store set); `reporting.timeline` must now show Recovery → Receipt → **Dispatcher Approval** → **Inventory Transaction** → Shipment entries per BOL (FT4.7 addition) — confirm no BOL is missing its Dispatcher Approval or Inventory Transaction row.
**Pass Criteria:** Every number on the Reporting dashboard is explainable by drilling into the operational timeline; nothing is a dead/orphaned figure — **except** the flagged `fulfillment_metrics()` zeros (open/reserved orders, reservation rate — see Risk R-2), which Bastion has not yet ruled on.

### 15. Executive Dashboard Validation
**Initial State:** A mix of in-flight (not yet closed) and closed BOLs.
**Operational Steps:** Compare `/dashboard` (Command Center) against `/reporting` for the same data set.
**Expected State Changes:** N/A (read-only verification).
**Executive Dashboard Effects:** Command Center is intentionally a **live** view — it calls `recovery_metrics`/`fulfillment_metrics`/etc. on the **full, unfiltered** store list, so in-flight (not-yet-closed) BOLs show up there immediately. Reporting is intentionally **close-out-gated only**. These are two different, both-correct views of different scopes.
**Pass Criteria:** Command Center shows more activity than Reporting whenever in-flight work exists, and the two converge once everything is closed out. **Recommend Bastion/Xavier confirm this dual-scope design is intentional and, ideally, documented somewhere visible to end users** — otherwise a live/finalized number mismatch between two dashboards will read as a bug to whoever's using the system (flagged as Risk R-5, documentation-only, not a code defect).

---

## 4. Test Matrix

| # | Scenario | Domains Touched | Concurrency Risk | Validated by Code Review | Requires Live Test |
|---|----------|------------------|-------------------|:---:|:---:|
| 1 | Standard Recovery Route | Dispatch→Driver→Receiving→Close-Out→Inventory→Reporting | No | ✅ | ✅ |
| 2 | Multi-stop Route | Driver, Dispatch | No | ✅ | ✅ |
| 3 | Multiple BOL Route | Driver, Receiving, Inventory, Reporting | No | ✅ | ✅ |
| 4 | Multiple Drivers | Driver, Dispatch | **Yes** | ✅ (isolation logic) | ⚠ Required |
| 5 | Multiple Receiving Clerks | Receiving | **Yes** | ✅ (isolation logic) | ⚠ Required |
| 6 | Driver vs Warehouse Variance | Close-Out, Inventory, Reporting | No | ✅ (incl. FT4.7 regression) | ✅ |
| 7 | Damaged Inventory | Receiving, Inventory | No | ✅ | ✅ |
| 8 | Awaiting Repair | Receiving, Inventory | No | ✅ | ✅ |
| 9 | Returned to EZ Rack | Receiving, Inventory | No | ✅ | ✅ |
| 10 | Zero Recovery / No Pickup | Driver, Receiving, Close-Out, Inventory, Reporting | No | ✅ | ✅ |
| 11 | Duplicate Receiving Verification | Receiving | **Yes (edge)** | ✅ (sequential) | ⚠ Recommended |
| 12 | Duplicate Dispatcher Approval | Close-Out | **Yes (edge)** | ✅ (sequential) | ⚠ Recommended |
| 13 | Inventory Audit Verification | Inventory | No | ✅ | ✅ |
| 14 | Reporting Audit Verification | Reporting | No | ✅ | ✅ |
| 15 | Executive Dashboard Validation | Command Center, Reporting | No | ✅ | ✅ |

---

## 5. Risk Assessment

| ID | Severity | Area | Root Cause | Suggested Resolution |
|----|----------|------|------------|------------------------|
| R-1 | **High** | Data layer (`app.py` `read_json`/`write_json`) | `stores.json`/`routes.json` are flat files with no file locking or optimistic-concurrency check. `write_json` is atomic against corruption but not against lost updates: two concurrent requests can both read stale data and the second write silently discards the first. Production runs under gunicorn (multi-worker), so this is a live risk, not just theoretical. | Architectural decision for Bastion: add per-record file locking (e.g. `flock` around read-modify-write), move to a real transactional store, or at minimum add an optimistic version/etag check that rejects a write if the record changed since read. Out of scope for me to implement without direction. |
| R-2 | Low | `reporting_service.fulfillment_metrics()` | `open_orders`, `reserved_orders`, `reservation_rate`, `components_reserved` are hardcoded to `0` while `shipped_orders` is computed normally — flagged during FT4.7, still unresolved. Doesn't leak unfinalized data (arguably over-conservative), but the fields are dead on the dashboard. | Bastion to decide: is this intentional (Reporting should only ever show shipped/finalized fulfillment activity) or unfinished work that should compute real values from the already-correctly-scoped fulfillment summary. |
| R-3 | Low | `inventory_service.build_component_row()` | `reserved` is never passed a value and defaults to `0`, so "Reserved Inventory" is always `0` in both the certified Inventory workspace and Reporting. Actual reservation tracking lives only in `fulfillment_service.active_reservation_totals()`, which Inventory's own summary doesn't consult. | Inherited from the certified Inventory workspace — out of scope to touch here. Note for Bastion in case this was meant to be wired up. |
| R-4 | Low | `receiving_service.component_totals_for_stores()` | Falls back to raw driver counts if `warehouse_verified_counts` is present but all-zero. In the current flow this only matters if a store is genuinely received with all-zero verified counts while driver counts were nonzero — an operator data-entry inconsistency rather than a code path that's reachable through normal use. | Recommend a live test of Scenario 10 (Zero Recovery) confirms this fallback never triggers incorrectly; if it does, flag to Bastion — this file is inside the certified Receiving workspace and out of scope for me to modify unilaterally. |
| R-5 | Low | UX / documentation | Command Center (live, unfiltered) and Reporting (close-out-gated only) will show different numbers for the same in-flight BOL by design. Confirmed correct in code, but not documented anywhere for end users. | Recommend a short note in `docs/USER_ROLES.md` or on the dashboards themselves clarifying "Executive Command = live pipeline view, Reporting = finalized-only view" so the discrepancy doesn't get reported as a bug. |

No findings rise to the level of blocking Release Candidate on their own. R-1 is the one item I'd want explicitly acknowledged before Commander live validation, since it's the only one that can cause silent data loss rather than a cosmetic/reporting gap.

---

## 6. Recommended Live Validation Steps

Sequence for Xavier to run against a live environment (staging, not production data):

1. **Seed data:** 6–8 fresh BOLs across at least 2 hubs/cities, 2 driver accounts, 2 dispatcher/admin accounts.
2. **Run Scenarios 1–3 sequentially**, single-user, confirming each status transition and the Inventory/Reporting boundary at close-out.
3. **Run Scenario 6** deliberately entering a driver/warehouse mismatch, then check the Reporting "Recovery Weight" KPI against the warehouse-verified number by hand — this is the direct FT4.7 regression check.
4. **Run Scenarios 7–9** one damage category at a time, then together on one BOL, and confirm Inventory's category breakdown sums correctly.
5. **Run Scenario 10** and confirm zero rows appear in no inventory table, but the BOL still shows in the Reporting timeline as a Dispatcher Approval event.
6. **Concurrency test (R-1, Scenarios 4/5/11/12):** open two browser sessions as two different drivers (or two receiving users), and fire two submissions **within the same second** against different BOLs, then the same BOL. Confirm no data is silently lost. This is the one test that cannot be skipped — it's the only unresolved unknown from this review.
7. **Run Scenarios 13–14** by manually picking 3 closed BOLs and tracing each dollar/unit from Inventory back through Reporting's timeline to the original driver submission.
8. **Run Scenario 15** with 2 in-flight (not yet closed) BOLs on the board — confirm Command Center shows them and Reporting doesn't, and that this is the expected behavior, not a defect.
9. Record pass/fail per row of the Test Matrix in §4 and hand results to Bastion for PRC-0008 certification.

---

## 7. Final Readiness Assessment

**Verdict: Conditionally ready for Commander-led live validation.**

Every certified workspace behaves correctly in isolation and in the closed-loop trace I performed, including the two defects found and fixed during FT4.7 (driver-count leakage into Reporting weight, missing Dispatcher Approval/Inventory Transaction audit trail). Operational Laws 1–8 hold under static review across all 15 required scenarios.

The one open question that live testing must answer before Bastion certifies is **R-1 (concurrent write safety)** — this is a structural property of the JSON-file data layer that cannot be confirmed or ruled out from code review alone, and it's the only finding with a plausible path to silent data loss rather than a display/reporting inconvenience. Everything else in the Risk Assessment (R-2 through R-5) is low-severity and a product decision for Bastion, not a blocker.

Recommend Commander proceeds with live validation per §6, with particular attention to step 6, and reports results back to Bastion for final PRC-0008 certification and Release Candidate designation.
