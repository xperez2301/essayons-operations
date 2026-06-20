EOMS v1.7.2 Dispatch Board Live Data Fix

Fix:
- Dispatch Board inside Dispatch Map now pulls directly from /api/dispatch-board-live.
- Uses all records from data/stores.json.
- Board no longer depends on the map's local filtered store list.
- Need Review / Unassigned / Assigned / Dispatched / Completed should now populate correctly.

Test:
1. Restart EOMS.
2. Open /dispatch-map.
3. Check Dispatch Board counts.
4. Open /api/dispatch-board-live to verify counts and stores.

Safe update:
No data/, bol_files/, uploads/, diagnostics/ included.
Copy only app.py, templates/, static/.
