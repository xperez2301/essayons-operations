EOMS v1.8.3 Force Admin Login Fix

Fixes:
- Missing import os
- Flask imports for redirect, url_for, session
- Real /login GET + POST route
- /logout route
- Blocks every page/API unless logged in
- Allows only /login, /logout, /static, /favicon.ico without login
- Sets Playwright headless=True for Azure

Default login:
Username: admin
Password: ChangeMeNow123!

Install:
1. Copy app.py to repo root.
2. Copy templates/login.html to templates/login.html.
3. Commit to production.
4. Push origin.
5. Wait for Azure Succeeded Active.
6. Open /login.
