from pathlib import Path
from playwright.sync_api import sync_playwright


class BrowserService:
    def __init__(self, profile_dir=None, headless=False):
        self.profile_dir = Path(profile_dir or "browser_profiles/rms_edge_profile")
        self.headless = headless
        self.playwright = None
        self.context = None
        self.page = None

    def launch(self):
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        self.playwright = sync_playwright().start()

        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            channel="msedge",
            headless=self.headless,
            viewport={"width": 1400, "height": 900},
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self.page

    def shutdown(self):
        try:
            if self.context:
                self.context.close()
        finally:
            if self.playwright:
                self.playwright.stop()