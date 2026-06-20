EOMS v1.3.3 Direct RMS Printable Link

Change:
- Live Printable no longer clicks through the BOL detail page.
- It logs into RMS, then goes directly to:
  https://rms.reusability.com/bills-of-lading/{BOL}/print

Why:
- Faster
- More reliable
- Matches actual RMS URL pattern
- Better for printing

Use:
1. Save RMS credentials in /settings
2. Go to /rms-queue
3. Click Live Printable
4. EOMS opens the direct RMS printable page and saves a backup copy.
