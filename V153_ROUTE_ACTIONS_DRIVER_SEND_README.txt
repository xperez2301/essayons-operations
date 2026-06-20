EOMS v1.5.3 Route Actions + Driver Send

Fixes:
- Route Builder buttons now have scripts inside the Jinja block so they execute.
- Print BOL button opens browser/Windows print dialog.
- Unassign Stop returns that stop to Dispatch Map.
- Unassign Entire Route returns all route stops to Dispatch Map.
- Empty routes are removed after stops are unassigned.

Adds:
- Driver name field on each route.
- Driver phone field on each route.
- Save Driver button.
- Send Route button.
- /route-view/<route_id> mobile-friendly route page.
- Send Route opens SMS app with a route link.

Note:
Send Route currently opens a local SMS draft using sms:. Direct Telnyx sending can be wired next once the route link is available from an Azure/public URL.
