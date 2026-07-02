from pathlib import Path
from playwright.sync_api import sync_playwright


class BrowserService:
    """
    Browser automation infrastructure for EOMS.
    """

    RMS_BASE_URL = "https://rms.reusability.com"
    RMS_LOGIN_URL = "https://rms.reusability.com/login"
    RMS_BOL_URL = "https://rms.reusability.com/bills-of-lading"

    def __init__(self, profile_dir=None, browser_channel="msedge", headless=False):
        self.profile_dir = Path(profile_dir or "browser_profiles/rms_edge_profile")
        self.browser_channel = browser_channel
        self.headless = headless

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.attached_cdp = False

    def launch(self):
        """
        Legacy isolated Playwright Edge profile.
        Kept as fallback only.
        """
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

        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self

    def attach_to_edge_cdp(self, cdp_url="http://127.0.0.1:9222"):
        """
        Attach to an already-open Microsoft Edge session using CDP.
        This allows EOMS to use the user's real authenticated RMS session.
        """
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(cdp_url)

        if not self.browser.contexts:
            raise RuntimeError("No Edge browser contexts found through CDP.")

        self.context = self.browser.contexts[0]
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.attached_cdp = True

        return self

    def current_page(self):
        if not self.page:
            raise RuntimeError("Browser has not been launched or attached.")
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
            "attached_cdp": self.attached_cdp,
            "current_url": self.page.url if self.page else None,
        }

    def shutdown(self):
        try:
            if self.context and not self.attached_cdp:
                try:
                    self.context.close()
                except Exception:
                    pass

            if self.browser and self.attached_cdp:
                try:
                    self.browser.close()
                except Exception:
                    pass
        finally:
            self.browser = None
            self.context = None
            self.page = None
            self.attached_cdp = False

            if self.playwright:
                try:
                    self.playwright.stop()
                except Exception:
                    pass

            self.playwright = None