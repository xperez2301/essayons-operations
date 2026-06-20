EOMS v1.4.1 Map Zoom + Pin Spread Fix

Fixes:
- Mouse wheel zoom works without holding CTRL.
- Google Maps uses gestureHandling: greedy.
- Duplicate or same-city pins no longer align in a straight diagonal line.
- Pins spread in a small circle around the true location.

Test:
1. Run py -3.12 app.py
2. Open /dispatch-map
3. Hover over map and scroll mouse wheel
4. Confirm it zooms without CTRL
5. Confirm grouped pins are spread naturally instead of in a straight line.
