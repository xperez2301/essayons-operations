EOMS v1.6.0 Dispatch Board

Adds:
- New /dispatch-board page
- Live columns:
  Need Review
  Unassigned
  Assigned
  Dispatched
  Completed
- Dashboard metrics:
  Need Review count
  Unassigned count
  Assigned count
  Dispatched count
  Completed count
  Total racks
  Total weight
  Revenue
  Driver pay
- Card actions:
  View Live BOL
  View Saved BOL
  Print BOL
  Approve Need Review
  Dispatch Assigned
  Complete Dispatched
  Unassign Assigned
- Adds Dispatch Board link to left navigation
- Keeps login/home page unchanged

Safe update:
This package excludes data/, bol_files/, uploads/, and diagnostics/.
Only copy app.py, templates/, static/, and requirements.txt if present.
