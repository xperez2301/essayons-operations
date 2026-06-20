EOMS v1.7.0 Driver Dispatch Workflow

Adds to Route Builder:
- Driver Name
- Driver Phone
- Truck
- Helper
- Save Driver
- Send Route
- Mark Dispatched
- Mark Completed

Adds:
- /route-view/<route_id> mobile-friendly driver route page
- SMS draft link that sends route URL to driver
- Dispatch route endpoint
- Complete route endpoint
- Driver assignment writes back to stores.json
- Route statuses update store statuses:
  Assigned
  Dispatched
  Completed

Workflow:
1. Build route from Dispatch Map.
2. Open Route Builder.
3. Add driver name, phone, truck, helper.
4. Save Driver.
5. Send Route.
6. Mark Dispatched.
7. Mark Completed.

Safe update:
This package excludes data/, bol_files/, uploads/, diagnostics/.
Copy only app.py, templates/, static/, requirements.txt if present.
