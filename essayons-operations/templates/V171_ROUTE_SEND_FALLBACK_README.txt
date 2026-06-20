EOMS v1.7.1 Route Send Fallback

Problem:
- On Windows desktop, sms: links may do nothing if no SMS handler/default app is configured.

Fix:
- Send Route now opens an in-app send box.
- It shows the full route message.
- It copies the message to clipboard.
- It provides Open SMS App and Try SMS Backup buttons.
- If Windows SMS does not open, paste the copied message manually.
- This prepares the workflow for direct Telnyx sending next.

Also includes:
- Fixed app.py with duplicate Flask route blocks removed.

Safe update:
This package excludes data/, bol_files/, uploads/, diagnostics/.
Copy only app.py, templates/, static/, requirements.txt if present.
