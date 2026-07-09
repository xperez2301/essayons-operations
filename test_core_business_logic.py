"""FT6 hardening: unit tests for core EOMS business logic that previously had
zero test coverage.

These tests do not change any behavior. They lock down what the following
currently do, so future refactors (blueprint split, data-layer migration,
etc.) have a safety net to run against:

- BOL duplicate detection (bol_duplicate_key / is_duplicate_bol / track_bol_key)
- Route/hub distance math (miles_between / route_miles / order_nearest_from_hub
  / calculate_route_metrics / resolve_route_hub / assign_hub)
- RMS PDF text parsing (demangle_pdf_text / find_match / find_corner_post_qty
  / parse_city_state_zip / extract_date_from_text / normalize_due_date)
- Store closeout variance math, both as pure aggregation
  (completion_summary_for_stores) and through the live
  /api/store-closeout/<id> endpoint.
"""

import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "core-business-logic-test-secret")

import app as eoms_app


class CleanAndNumTests(unittest.TestCase):
    def test_clean_strips_and_stringifies(self):
        self.assertEqual(eoms_app.clean("  hello  "), "hello")
        self.assertEqual(eoms_app.clean(None), "")
        self.assertEqual(eoms_app.clean(42), "42")

    def test_num_parses_numbers_and_strips_commas(self):
        self.assertEqual(eoms_app.num("1,234.5"), 1234.5)
        self.assertEqual(eoms_app.num("42"), 42.0)

    def test_num_falls_back_to_default_on_bad_input(self):
        self.assertEqual(eoms_app.num(None), 0)
        self.assertEqual(eoms_app.num(""), 0)
        self.assertEqual(eoms_app.num("not-a-number"), 0)
        self.assertEqual(eoms_app.num(None, default=5), 5)

    def test_safe_part_strips_unsafe_characters_and_truncates(self):
        self.assertEqual(eoms_app.safe_part("Hello World!"), "HelloWorld")
        self.assertEqual(eoms_app.safe_part(""), "Unknown")
        self.assertEqual(eoms_app.safe_part(None), "Unknown")
        self.assertEqual(len(eoms_app.safe_part("A" * 100)), 35)


class BolDuplicateDetectionTests(unittest.TestCase):
    def test_bol_duplicate_key_uses_bol_and_origin(self):
        item = {"bol": " 951807 ", "origin": " MVNFRTX "}
        self.assertEqual(eoms_app.bol_duplicate_key(item), ("951807", "MVNFRTX"))

    def test_is_duplicate_bol_matches_on_bol_and_origin_pair(self):
        existing_keys = {("951807", "MVNFRTX")}
        existing_bols = {"951807"}
        self.assertTrue(
            eoms_app.is_duplicate_bol({"bol": "951807", "origin": "MVNFRTX"}, existing_keys, existing_bols)
        )

    def test_is_duplicate_bol_matches_on_bol_alone_even_if_origin_changed(self):
        # Guards against the same BOL coming back with a missing/changed origin.
        existing_keys = {("951807", "MVNFRTX")}
        existing_bols = {"951807"}
        self.assertTrue(
            eoms_app.is_duplicate_bol({"bol": "951807", "origin": "DIFFERENT"}, existing_keys, existing_bols)
        )

    def test_is_duplicate_bol_false_for_new_bol(self):
        existing_keys = {("951807", "MVNFRTX")}
        existing_bols = {"951807"}
        self.assertFalse(
            eoms_app.is_duplicate_bol({"bol": "999999", "origin": "NEWORIGIN"}, existing_keys, existing_bols)
        )

    def test_track_bol_key_adds_to_both_sets(self):
        existing_keys, existing_bols = set(), set()
        eoms_app.track_bol_key({"bol": "111", "origin": "ABC"}, existing_keys, existing_bols)
        self.assertIn(("111", "ABC"), existing_keys)
        self.assertIn("111", existing_bols)


class CompletionSummaryTests(unittest.TestCase):
    def test_completion_summary_computes_rack_and_piece_variance(self):
        stores = [
            {"expected_racks": 10, "collected_racks": 8, "collected_pieces": 150},
            {"expected_racks": 5, "collected_racks": 5, "collected_pieces": 95},
        ]
        summary = eoms_app.completion_summary_for_stores(stores)
        self.assertEqual(summary["stores"], 2)
        self.assertEqual(summary["expected_racks"], 15)
        self.assertEqual(summary["collected_racks"], 13)
        self.assertEqual(summary["variance"], -2)
        # expected_pieces falls back to expected_racks * PIECES_PER_RACK (19)
        # when a store has no explicit expected_pieces value.
        self.assertEqual(summary["expected_pieces"], 285)
        self.assertEqual(summary["collected_pieces"], 245)
        self.assertEqual(summary["pieces_variance"], -40)


class RouteMathTests(unittest.TestCase):
    def test_miles_between_same_point_is_zero(self):
        self.assertEqual(eoms_app.miles_between(29.5353, -98.4188, 29.5353, -98.4188), 0)

    def test_miles_between_is_symmetric(self):
        a = eoms_app.miles_between(29.5353, -98.4188, 30.0147, -95.4306)
        b = eoms_app.miles_between(30.0147, -95.4306, 29.5353, -98.4188)
        self.assertAlmostEqual(a, b, places=6)

    def test_miles_between_matches_independent_haversine_calc(self):
        # Independent haversine implementation (not calling the app's own
        # code) as a cross-check on San Antonio -> Houston hub distance.
        lat1, lng1, lat2, lng2 = 29.5353, -98.4188, 30.0147, -95.4306
        radius = 3958.8
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        expected = radius * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))
        self.assertAlmostEqual(eoms_app.miles_between(lat1, lng1, lat2, lng2), expected, places=6)

    def test_route_miles_zero_for_fewer_than_two_points(self):
        self.assertEqual(eoms_app.route_miles([]), 0)
        self.assertEqual(eoms_app.route_miles([{"lat": 1, "lng": 1}]), 0)

    def test_route_miles_zero_when_all_points_identical(self):
        points = [{"lat": 29.5353, "lng": -98.4188}] * 3
        self.assertEqual(eoms_app.route_miles(points), 0.0)

    def test_order_nearest_from_hub_picks_closest_store_first(self):
        hub_name = "San Antonio"
        near = {"id": "near", "lat": 29.6, "lng": -98.4}
        far = {"id": "far", "lat": 32.7767, "lng": -96.7970}  # Dallas coords
        ordered = eoms_app.order_nearest_from_hub(hub_name, [far, near])
        self.assertEqual([s["id"] for s in ordered], ["near", "far"])

    def test_calculate_route_metrics_basic_math(self):
        # Store sits exactly on the hub coordinates so mileage is exactly 0,
        # keeping this test focused on the racks/pieces/revenue/weight math.
        store = {"lat": 29.5353, "lng": -98.4188, "expected_racks": 10, "weight": 5000}
        metrics = eoms_app.calculate_route_metrics([store], "San Antonio")
        self.assertEqual(metrics["racks"], 10)
        self.assertEqual(metrics["pieces"], 190)  # 10 racks * 19 pieces/rack
        self.assertEqual(metrics["weight"], 5000)
        self.assertEqual(metrics["remaining_capacity"], 20001)  # 25001 - 5000
        self.assertEqual(metrics["mileage"], 0.0)
        self.assertEqual(metrics["revenue"], 180.5)  # 190 * 0.95
        self.assertEqual(metrics["driver_pay"], 57.0)  # 190 * 0.30
        self.assertEqual(metrics["status"], "SAFE")

    def test_calculate_route_metrics_flags_over_limit_status(self):
        store = {"lat": 29.5353, "lng": -98.4188, "expected_racks": 5, "weight": 26000}
        metrics = eoms_app.calculate_route_metrics([store], "San Antonio")
        self.assertEqual(metrics["status"], "OVER LIMIT")

    def test_resolve_route_hub_uses_valid_requested_hub(self):
        self.assertEqual(eoms_app.resolve_route_hub([], "Houston"), ("Houston", ""))

    def test_resolve_route_hub_infers_single_shared_hub(self):
        stores = [{"hub": "Dallas"}, {"hub": "Dallas"}]
        self.assertEqual(eoms_app.resolve_route_hub(stores, ""), ("Dallas", ""))

    def test_resolve_route_hub_requires_hub_when_missing(self):
        stores = [{"hub": "Manual Review"}]
        hub, error = eoms_app.resolve_route_hub(stores, "")
        self.assertEqual(hub, "")
        self.assertEqual(error, "Hub Required")

    def test_resolve_route_hub_errors_on_conflicting_hubs(self):
        stores = [{"hub": "Dallas"}, {"hub": "Houston"}]
        hub, error = eoms_app.resolve_route_hub(stores, "")
        self.assertEqual(hub, "")
        self.assertEqual(error, "Select one hub for this route.")


class AssignHubTests(unittest.TestCase):
    def test_assign_hub_respects_houston_dispatch_group(self):
        # assign_hub only special-cases Houston via a literal "houston"
        # substring match (unlike the "susatxus" literal alias below), so
        # the dispatch group needs to actually contain that word.
        hub, reason = eoms_app.assign_hub(0, 0, dispatch_group="Houston Metro")
        self.assertEqual(hub, "Houston")
        self.assertEqual(reason, "Dispatch Group")

    def test_assign_hub_respects_san_antonio_dispatch_group_alias(self):
        hub, reason = eoms_app.assign_hub(0, 0, dispatch_group="SUSATXUS")
        self.assertEqual(hub, "San Antonio")
        self.assertEqual(reason, "Dispatch Group")

    def test_assign_hub_falls_back_to_nearest_hub_within_100_miles(self):
        hub, reason = eoms_app.assign_hub(29.5353, -98.4188, dispatch_group="")
        self.assertEqual(hub, "San Antonio")
        self.assertIn("Nearest Hub", reason)

    def test_assign_hub_returns_manual_review_when_too_far(self):
        # El Paso, TX is several hundred miles from every hub.
        hub, reason = eoms_app.assign_hub(31.7619, -106.4850, dispatch_group="")
        self.assertEqual(hub, "Manual Review")
        self.assertIn("Outside 100 mi", reason)


class TextAndDateParsingTests(unittest.TestCase):
    def test_demangle_pdf_text_fixes_known_split_words(self):
        result = eoms_app.demangle_pdf_text("Addr ess: 123 Main St, Cont act: John")
        self.assertEqual(result, "Address: 123 Main St, Contact: John")

    def test_demangle_pdf_text_passes_through_falsy_values(self):
        self.assertIsNone(eoms_app.demangle_pdf_text(None))
        self.assertEqual(eoms_app.demangle_pdf_text(""), "")

    def test_find_match_returns_group_or_default(self):
        self.assertEqual(eoms_app.find_match(r"Name:\s*(\w+)", "Name: John"), "John")
        self.assertEqual(eoms_app.find_match(r"Name:\s*(\w+)", "no match here", default="N/A"), "N/A")

    def test_find_corner_post_qty_matches_primary_pattern(self):
        text = '84" Corner Post Only R-CPH84 5 100 250\n'
        self.assertEqual(eoms_app.find_corner_post_qty(text), 250)

    def test_find_corner_post_qty_falls_back_to_loose_line_scan(self):
        text = "Some 84 corner post note 999"
        self.assertEqual(eoms_app.find_corner_post_qty(text), 999)

    def test_find_corner_post_qty_returns_zero_when_absent(self):
        self.assertEqual(eoms_app.find_corner_post_qty("nothing relevant here"), 0)

    def test_parse_city_state_zip_with_comma(self):
        self.assertEqual(eoms_app.parse_city_state_zip("Houston, TX 77073"), ("Houston", "TX", "77073"))

    def test_parse_city_state_zip_with_texas_spelled_out(self):
        self.assertEqual(eoms_app.parse_city_state_zip("Dallas Texas 75201"), ("Dallas", "TX", "75201"))

    def test_parse_city_state_zip_unparseable_defaults_to_tx(self):
        self.assertEqual(eoms_app.parse_city_state_zip("Random text"), ("Random text", "TX", ""))

    def test_extract_date_from_text_slash_format(self):
        self.assertEqual(eoms_app.extract_date_from_text("Due: 07/15/2026 please"), "07/15/2026")

    def test_extract_date_from_text_iso_format(self):
        self.assertEqual(eoms_app.extract_date_from_text("Due: 2026-07-15"), "2026-07-15")

    def test_extract_date_from_text_no_date_found(self):
        self.assertEqual(eoms_app.extract_date_from_text("no date here"), "")

    def test_normalize_due_date_converts_iso_to_slash_format(self):
        self.assertEqual(eoms_app.normalize_due_date("2026-07-15"), "07/15/2026")

    def test_normalize_due_date_keeps_slash_format_as_is(self):
        self.assertEqual(eoms_app.normalize_due_date("7/5/2026"), "07/05/2026")

    def test_normalize_due_date_empty_stays_empty(self):
        self.assertEqual(eoms_app.normalize_due_date(""), "")

    def test_normalize_due_date_invalid_date_returned_unchanged(self):
        # Matches the slash-date shape but 13/45 isn't a real date; strptime
        # raises and the function returns the original value untouched.
        self.assertEqual(eoms_app.normalize_due_date("13/45/2026"), "13/45/2026")


class StoreCloseoutEndpointTests(unittest.TestCase):
    """Exercises the live /api/store-closeout/<id> endpoint end-to-end
    (routing, auth, file I/O) rather than just the pure math, since the
    variance flags are computed inline in the route handler itself."""

    def setUp(self):
        self.client = eoms_app.app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.stores_path = Path(self.temp_dir.name) / "stores.json"
        self.routes_path = Path(self.temp_dir.name) / "routes.json"

        self.store = {
            "id": "store-1",
            "bol": "12345",
            "expected_racks": 10,
            "expected_pieces": None,
        }
        self.stores_path.write_text(json.dumps([self.store]), encoding="utf-8")
        self.routes_path.write_text(json.dumps([]), encoding="utf-8")

        self.stores_patch = patch.object(eoms_app, "STORES_FILE", self.stores_path)
        self.routes_patch = patch.object(eoms_app, "ROUTES_FILE", self.routes_path)
        self.stores_patch.start()
        self.routes_patch.start()

    def tearDown(self):
        self.stores_patch.stop()
        self.routes_patch.stop()
        self.temp_dir.cleanup()

    def authenticated_post(self, path, json_body):
        with self.client.session_transaction() as session:
            session["logged_in"] = True
            session["username"] = "admin"
        with patch.object(
            eoms_app, "current_user",
            return_value={"username": "admin", "role": "Admin", "active": True, "assigned_cities": ["All"]},
        ):
            return self.client.post(path, json=json_body)

    def test_closeout_update_flags_variance_review_when_short(self):
        response = self.authenticated_post(
            "/api/store-closeout/store-1",
            {"collected_racks": 8},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["store"]["variance"], -2)
        # abs(variance) >= 2 flips the review flag on.
        self.assertTrue(payload["store"]["variance_review"])

    def test_closeout_update_no_review_flag_when_within_tolerance(self):
        response = self.authenticated_post(
            "/api/store-closeout/store-1",
            {"collected_racks": 9},
        )
        payload = response.get_json()
        self.assertEqual(payload["store"]["variance"], -1)
        self.assertFalse(payload["store"]["variance_review"])

    def test_closeout_update_rejects_negative_rack_count(self):
        response = self.authenticated_post(
            "/api/store-closeout/store-1",
            {"collected_racks": -1},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])

    def test_closeout_update_computes_pieces_variance_against_rack_fallback(self):
        # expected_pieces is None on this store, so it falls back to
        # expected_racks (10) * PIECES_PER_RACK (19) = 190.
        response = self.authenticated_post(
            "/api/store-closeout/store-1",
            {"collected_pieces": 150},
        )
        payload = response.get_json()
        self.assertEqual(payload["store"]["pieces_variance"], -40)

    def test_closeout_update_missing_store_returns_404(self):
        response = self.authenticated_post(
            "/api/store-closeout/does-not-exist",
            {"collected_racks": 5},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
