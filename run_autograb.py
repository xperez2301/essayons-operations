from eoms_modules.rms_api_client import RMSApiClient


client = RMSApiClient()

page = 1
all_bols = []

while True:
    res = client.fetch(page)

    # 🚨 STOP if not logged in / bad response
    if res is None:
        print("❌ No valid response (check login/cookie)")
        break

    # safety check
    if "data" not in res:
        print("❌ Unexpected response format:")
        print(res)
        break

    all_bols.extend(res["data"])

    print(f"Page {page} loaded | Total so far: {len(all_bols)}")

    last_page = res.get("last_page", 1)

    if page >= last_page:
        break

    page += 1


print("\n====================")
print("TOTAL BOLS:", len(all_bols))
print("====================")

if len(all_bols) > 0:
    print("FIRST BOL:")
    print(all_bols[0])