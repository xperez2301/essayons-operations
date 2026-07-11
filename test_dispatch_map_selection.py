import unittest
from pathlib import Path


class DispatchMapSelectionScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = Path("static/js/dispatch_map.js").read_text(encoding="utf-8")
        cls.css = Path("static/css/eoms-design-system.css").read_text(encoding="utf-8")

    def test_selected_bols_remain_visible_in_ready_list(self):
        self.assertIn("const selectionManager = {", self.script)
        self.assertIn(
            "function visibleUnassignedStores(){ return stores.filter(s => canSelectStore(s) && storeMatchesSearch(s)); }",
            self.script,
        )
        self.assertIn('selectedOrder.includes(store.id) ? "checked" : ""', self.script)
        self.assertIn('label.classList.add("active-store")', self.script)
        self.assertNotIn("selectedOrder.push", self.script)

    def test_selected_markers_are_highlighted_not_hidden(self):
        self.assertIn("function syncSelectedMarkerState()", self.script)
        self.assertIn("setMarkerVisible(marker, true)", self.script)
        self.assertNotIn("setMarkerVisible(markers[id], !selectedOrder.includes(id))", self.script)
        self.assertIn("is-selected", self.script)
        self.assertIn(".azure-stop-marker.is-selected", self.css)

    def test_marker_click_toggles_selection_and_ineligible_stores_are_guarded(self):
        self.assertIn("function canSelectStore(store)", self.script)
        self.assertIn("focusStoreCard(store.id, {toggle: true})", self.script)
        self.assertIn(".azure-stop-marker.is-ineligible", self.css)


if __name__ == "__main__":
    unittest.main()
