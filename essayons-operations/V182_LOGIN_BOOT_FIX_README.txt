EOMS v1.8.2 Login Boot Fix

Fixes:
- Adds missing import os so Azure can start the app
- Adds complete admin login handler
- Adds /logout
- Protects EOMS routes behind login
- Forces Playwright test browser to headless=True for Azure compatibility
- Includes templates/login.html

Default login:
Username: admin
Password: ChangeMeNow123!

After upload:
1. Commit to production
2. Push origin production
3. Wait for Azure Deployment Center Logs to show Succeeded (Active)
4. Test /login
