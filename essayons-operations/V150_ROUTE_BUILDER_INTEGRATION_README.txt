EOMS v1.5.0 Route Builder Integration

Adds:
- Dispatch Map can build routes directly.
- Option 3 implemented:
  1. Build Route - Selection Order
  2. Optimize Route
- Selection Order keeps the exact order stores were clicked.
- Optimize Route uses nearest-stop logic from the hub.
- Route Builder page now shows route details and stop-by-stop table.
- M2 payload check remains active. Over-limit route assignment is blocked.

Workflow:
1. Open /dispatch-map
2. Select stores/pins
3. Select driver if desired
4. Click Build Route - Selection Order or Optimize Route
5. EOMS assigns route and opens /route-builder
