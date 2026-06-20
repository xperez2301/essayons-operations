EOMS v1.4.3 Address Geocode Fix

Problem fixed:
- Pins were using city fallback coordinates, not exact store addresses.

Adds:
- Google Maps Geocoding from full RMS Origin address.
- Settings field for Google Maps API Key.
- Re-Geocode Stores button on Dispatch Map.
- /api/geocode-stores endpoint.
- stores.json now saves:
  full_address
  geocode_status
  true lat/lng from Google when available.

Important:
If no Google Maps API key is saved in Settings, EOMS will still fall back to city coordinates.

Test:
1. /settings
2. Save Google Maps API Key
3. /dispatch-map
4. Click Re-Geocode Stores
5. Check /api/dispatch-map-debug
6. Pins should move from city-center to actual street addresses.
