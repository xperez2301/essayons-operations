class RMSAdapter:
    """
    RMS business logic layer.

    This sits BETWEEN AutoGrabService and BrowserService.
    """

    def __init__(self, browser_service):
        self.browser = browser_service

    # -----------------------------
    # SESSION
    # -----------------------------
    def is_logged_in(self) -> bool:
        status = self.browser.rms_session_status()
        return status.get("logged_in", False)

    def ensure_logged_in(self):
        status = self.browser.rms_session_status()
        if not status.get("logged_in"):
            raise RuntimeError("RMS session expired. Manual login required.")

    def get_session_status(self):
        return self.browser.rms_session_status()

    # -----------------------------
    # NAVIGATION
    # -----------------------------
    def go_to_bols(self):
        self.browser.goto_bills_of_lading()

    def go_home(self):
        self.browser.goto_rms_home()

    # -----------------------------
    # PAGE SIZE HANDLER
    # -----------------------------
    def set_page_size_1000(self, page):
        try:
            dropdowns = page.query_selector_all("select")

            for dropdown in dropdowns:
                options = dropdown.query_selector_all("option")

                for option in options:
                    text = option.inner_text().lower()

                    if "1000" in text or "all" in text:
                        option.click()
                        page.wait_for_timeout(3000)
                        return True

        except Exception:
            pass

        return False

    # -----------------------------
    # PUBLIC ENTRY POINT
    # -----------------------------
    def capture_bols(self):
        """
        Primary entry point used by RMSService.
        """
        return self.scan_queue()

    # -----------------------------
    # MAIN RMS PIPELINE
    # -----------------------------
    def scan_queue(self):
        self.ensure_logged_in()
        self.go_to_bols()

        list_page = self.browser.current_page()
        list_page.wait_for_timeout(2000)

        self.set_page_size_1000(list_page)
        list_page.wait_for_timeout(3000)

        bol_ids = self.collect_bol_ids(list_page)
        results = self.capture_print_pages(bol_ids)

        return {
            "ok": True,
            "message": "RMS stable scan complete",
            "count": len(results),
            "data": results,
        }

    # -----------------------------
    # BOL COLLECTION
    # -----------------------------
    def collect_bol_ids(self, list_page):
        bol_ids = set()

        try:
            links = list_page.query_selector_all("a")

            for link in links:
                try:
                    href = link.get_attribute("href") or ""
                    text = link.inner_text().strip()

                    if "bills-of-lading/" in href:
                        parts = href.split("bills-of-lading/")
                        if len(parts) > 1:
                            candidate = parts[-1].split("/")[0].split("?")[0]
                            if candidate.isdigit():
                                bol_ids.add(candidate)

                    elif text.isdigit() and len(text) >= 5:
                        bol_ids.add(text)

                except Exception:
                    continue

        except Exception:
            pass

        return list(bol_ids)

    # -----------------------------
    # PRINT PAGE CAPTURE
    # -----------------------------
    def capture_print_pages(self, bol_ids, limit=20):
        results = []

        for bol_id in bol_ids[:limit]:
            print_page = None

            try:
                print_url = (
                    f"https://rms.reusability.com/bills-of-lading/{bol_id}/print"
                )

                print_page = self.browser.context.new_page()
                print_page.goto(print_url)
                print_page.wait_for_timeout(3000)

                content = print_page.inner_text("body")

                results.append(
                    {
                        "bol_id": bol_id,
                        "url": print_url,
                        "content": content[:3000],
                    }
                )

            except Exception:
                pass

            finally:
                if print_page:
                    try:
                        print_page.close()
                    except Exception:
                        pass

        return results