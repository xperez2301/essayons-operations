EOMS v1.5.4 Due Dates + Navigation Cleanup

Fixes:
- Removes duplicate Route Builder link from left navigation.
- Captures due date from the RMS Bills of Lading list row during Refresh RMS Queue.
- Carries due date from RMS Queue into stores.json during Import/Re-import Selected when printable BOL does not include due date.
- Adds due date color chips on RMS Queue and Route Builder.

Due date colors:
- Green = more than 4 days away or no due date captured
- Amber = due within 4 days
- Red = past due

Important:
After installing, run Refresh RMS Queue so due dates are captured from RMS list rows.
Then Import/Re-import Selected so due dates transfer into store/route records.
