from playwright.sync_api import sync_playwright
from eoms_db import EOMSDatabase
import json


def run():
    db = EOMSDatabase()

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        seen_pages = set()

        def handle_response(response):
            if "bills-of-lading-report" in response.url:

                try:
                    data = response.json()  # 🔥 safer than text parsing

                    page_num = data.get("current_page", None)

                    if page_num in seen_pages:
                        return

                    seen_pages.add(page_num)

                    bols = data.get("data", [])

                    print("\n🔥 PAGE CAPTURED:", page_num)
                    print("TOTAL BOLS:", len(bols))

                    db.insert_bols(bols)

                    print("💾 SAVED TO DATABASE")

                except Exception as e:
                    print("❌ Parse error:", e)

        page.on("response", handle_response)

        # 1. LOGIN
        page.goto("https://rms.reusability.com/login")

        print("\n👉 Login manually in browser")
        input("👉 Press ENTER after dashboard loads")

        # 2. TRIGGER UI
        page.goto("https://rms.reusability.com/bills-of-lading")

        print("\n🔥 Waiting for RMS to load data...")

        page.wait_for_timeout(15000)

        browser.close()


run()