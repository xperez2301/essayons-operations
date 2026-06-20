EOMS v1.4.2 Actual Location Pins

Change:
- Pins now use the exact stored latitude/longitude.
- No diagonal offset.
- No circular spread.
- Mouse wheel zoom without CTRL remains enabled.

Note:
If several BOLs share the same city/default coordinate, pins may overlap. That means EOMS needs better address geocoding next, not artificial pin movement.

Test:
1. Run py -3.12 app.py
2. Open /dispatch-map
3. Confirm pins are at actual stored location.
