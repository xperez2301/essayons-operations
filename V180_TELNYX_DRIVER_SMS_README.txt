EOMS v1.8.0 Telnyx Driver SMS

Adds:
- Telnyx API Key field in Settings
- Telnyx From Number field in Settings
- Public EOMS URL field in Settings
- /api/send-route-sms endpoint
- Send via Telnyx button in Route Builder send modal
- Saves last SMS status/time/response on route record

Workflow:
1. Open /settings
2. Save:
   Telnyx API Key
   Telnyx From Number: +12103529669
   Public EOMS URL if deployed
3. Open /route-builder
4. Save Driver with phone number
5. Click Send Route
6. Click Send via Telnyx

Important:
If Public EOMS URL is blank, route link will use local http://127.0.0.1:5000.
That local link will not work on a driver's phone unless the app is deployed or exposed publicly.

Safe update:
This package excludes data/, bol_files/, uploads/, diagnostics/.
Copy only app.py, templates/, static/, requirements.txt if present.
