EOMS v1.4.4 Auto Geocode on Import

Fix:
- Import/Re-import Selected now automatically geocodes the full RMS Origin address.
- It uses:
  address + city + state + zip
- It overwrites old city-center coordinates in stores.json.
- Pins are placed at the actual street address when Google Maps API key is saved.
- Existing bad pins can be fixed by selecting the BOL and clicking Import/Re-import Selected again.
- The Fix Existing Pins button remains available as a backup, not the normal workflow.

Required:
1. Go to /settings
2. Save Google Maps API key
3. Go to /rms-queue
4. Select the BOL
5. Click Import/Re-import Selected
6. Go to /dispatch-map

Expected:
stores.json should show geocode_status starting with "Google geocoded" and lat/lng should no longer be city-center.
