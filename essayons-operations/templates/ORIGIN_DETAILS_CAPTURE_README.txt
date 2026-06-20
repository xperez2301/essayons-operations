EOMS v1.3.6 Origin Details Capture

Adds capture from the top-left Origin block of RMS Printable BOL:
- Origin code
- Name
- Address
- City
- State
- ZIP
- Contact
- Destination code and details

Updates:
- RMS Queue shows Address and Contact
- Dispatch Map store cards show Origin, address, city/state/zip, contact
- Need Review shows origin details

Test:
1. Go to /rms-queue
2. Click Repair/Parse on an existing BOL or Import/Re-import Selected
3. Open /dispatch-map
4. Store card should show origin name, address, city/state, contact.
