EOMS v1.8.1 Admin Login Lockdown

Adds:
- /login
- /logout
- Admin session login
- Protects EOMS pages and API routes by default
- Professional EOMS login page
- Azure environment variable support

Default local fallback:
Username: admin
Password: ChangeMeNow123!

For Azure, set these under:
Azure Portal > eoms-dispatch > Environment variables

SECRET_KEY = long random value
ADMIN_USERNAME = your admin username
ADMIN_PASSWORD = your password
SESSION_TIMEOUT_MINUTES = 720

Safe update:
No data/, bol_files/, uploads/, diagnostics/ included.
Copy/upload only:
app.py
templates/
static/
requirements.txt if present
