EOMS app.py Duplicate Route Fix

What I fixed:
- Removed the older duplicate /api/update-route-driver endpoint.
- Removed the older duplicate /route-view/<route_id> endpoint.
- Kept the newer v1.7 driver dispatch workflow version with:
  Driver
  Phone
  Truck
  Helper
  Dispatch route
  Complete route
  Mobile route view

Compile check: PASSED

Install:
1. Stop EOMS with CTRL+C.
2. Copy app.py from this ZIP.
3. Replace:
   C:\Users\essay\OneDrive\Documentos\GitHub\essayons-operations\app.py
4. In PowerShell:
   cd "C:\Users\essay\OneDrive\Documentos\GitHub\essayons-operations"
   py -3.12 app.py

Route counts after fix:
- /api/update-route-driver count: 1
- /route-view/<route_id> count: 1

Potential duplicate function endpoints after fix:
{}

Compile error:

