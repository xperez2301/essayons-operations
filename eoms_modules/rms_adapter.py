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

            for d in dropdowns:
                options = d.query_selector_all("option")

                for opt in options:
                    text = opt.inner_text().lower()

                    if "1000" in text or "all" in text:
                        opt.click()
                        page.wait_for_timeout(3000)
                        return
        except:
            pass

    # -----------------------------
    # MAIN RMS PIPELINE (STABLE VERSION)
    # -----------------------------
    def scan_queue(self):
        self.go_to_bols()

        list_page = self.browser.current_page()

        list_page.wait_for_timeout(2000)

        self.set_page_size_1000(list_page)

        list_page.wait_for_timeout(3000)

        # -----------------------------
        # PHASE 1: COLLECT ALL BOL IDS
        # -----------------------------
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

                except:
                    continue

        except:
            pass

        bol_ids = list(bol_ids)

        results = []

        # -----------------------------
        # PHASE 2: OPEN EACH PRINT PAGE (ISOLATED)
        # -----------------------------
        for bol_id in bol_ids[:20]:

            print_page = None

            try:
                print_url = (
                    f"https://rms.reusability.com/bills-of-lading/{bol_id}/print"
                )

                print_page = self.browser.context.new_page()

                print_page.goto(print_url)
                print_page.wait_for_timeout(3000)

                content = print_page.inner_text("body")

                results.append({
                    "bol_id": bol_id,
                    "url": print_url,
                    "content": content[:3000]
                })

            except:
                pass

            finally:
                if print_page:
                    try:
                        print_page.close()
                    except:
                        pass

        return {
            "ok": True,
            "message": "RMS stable scan complete",
            "count": len(results),
            "data": results
        }

    # -----------------------------
    # SESSION INFO
    # -----------------------------
    def get_session_status(self):
        return self.browser.rms_session_status()