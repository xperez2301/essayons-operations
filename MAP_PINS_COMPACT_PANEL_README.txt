EOMS v1.3.8 Map Pins + Compact Panel

Fixes:
- Dispatch Map now fits bounds around all hubs and visible store pins.
- Duplicate/overlapping store coordinates are offset slightly so pins do not hide behind each other.
- Markers use numbered labels when multiple stores share the same location.
- Available Stores panel is smaller and scrollable.
- Store cards are more compact.
- Adds /api/dispatch-map-debug for troubleshooting map visibility.

Test:
1. Run py -3.12 app.py
2. Go to /dispatch-map
3. Confirm store pins are visible.
4. If a store is missing, open /api/dispatch-map-debug to confirm its status and coordinates.
