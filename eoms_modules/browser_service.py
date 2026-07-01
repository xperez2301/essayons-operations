from pathlib import Path
from playwright.sync_api import sync_playwright


class BrowserService:
    """
    Browser automation infrastructure for EOMS.

    Owns:
    - Browser selection
    - Persistent profile
    - Startup/shutdown
    - Current page access
    - RMS navigation helpers
    """

    RMS_BASE_URL = "https://rms.reusability.com"
    RMS_LOGIN_URL = "https://rms.reusability.com/login"

    # ✅ FIXED ROUTE (THIS WAS THE BUG)
    RMS_BOL_URL = "https://rms.reusability.com/bills-of-lading"

    def __init__(self, profile_dir=None, browser_channel="msedge", headless=False):
        self.profile_dir = Path(profile_dir or "browser_profiles/rms_edge_profile")
        self.browser_channel = browser_channel
        self.headless = headless

        self.playwright = None
        self.context = None
        self.page = None

    def launch(self):
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        self.playwright = sync_playwright().start()

        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            channel=self.browser_channel,
            headless=self.headless,
            viewport={"width": 1400, "height": 900},
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        self.page = (
            self.context.pages[0]
            if self.context.pages
            else self.context.new_page()
        )

        return self

    def current_page(self):
        if not self.page:
            raise RuntimeError("Browser has not been launched.")
        return self.page

    def goto(self, url, wait_until="networkidle"):
        page = self.current_page()
        page.goto(url, wait_until=wait_until)
        return page

    def goto_rms_home(self):
        return self.goto(self.RMS_BASE_URL)

    def goto_rms_login(self):
        return self.goto(self.RMS_LOGIN_URL)

    def goto_bills_of_lading(self):
        return self.goto(self.RMS_BOL_URL)

    def is_rms_login_page(self):
        page = self.current_page()

        url = page.url.lower()

        try:
            title = page.title().lower()
        except Exception:
            title = ""

        return "login" in url or "sign in" in title

    def rms_session_status(self):
        page = self.goto_rms_home()

        if self.is_rms_login_page():
            return {
                "ok": False,
                "logged_in": False,
                "url": page.url,
                "message": "RMS session expired or login required.",
            }

        return {
            "ok": True,
            "logged_in": True,
            "url": page.url,
            "message": "RMS session appears active.",
        }

    def screenshot(self, path):
        page = self.current_page()
        page.screenshot(path=str(path), full_page=True)
        return str(path)

    def browser_info(self):
        return {
            "browser_channel": self.browser_channel,
            "headless": self.headless,
            "profile_dir": str(self.profile_dir),
            "current_url": self.page.url if self.page else None,
        }

    def shutdown(self):
        try:
            if self.context:
                try:
                    self.context.close()
                except Exception:
                    pass
        finally:
            self.context = None
            self.page = None

            if self.playwright:
                try:
                    self.playwright.stop()
                except Exception:
                    pass

            self.playwright = None