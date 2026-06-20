EOMS v1.6.1 Dispatch Board Inside Dispatch Map

Workaround:
Instead of using a separate /dispatch-board route, the Dispatch Board is built directly inside /dispatch-map.

Why:
- /dispatch-map is confirmed working.
- Avoids 404 route/path/restart issues.
- Uses the store data already loaded by Dispatch Map.

Adds inside Dispatch Map:
- Need Review
- Unassigned
- Assigned
- Dispatched
- Completed
- Counts
- Racks
- Weight
- Revenue
- Driver Pay
- Approve
- Select
- Dispatch
- Complete
- Unassign
- Live/Saved/Print BOL links

Safe update:
No data/, bol_files/, uploads/, or diagnostics/ included.
Copy only app.py, templates/, static/, requirements.txt if present.
