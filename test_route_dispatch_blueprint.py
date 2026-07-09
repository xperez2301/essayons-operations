"""FT6: proves the Route/Dispatch blueprint extraction (routes/route_dispatch.py)
preserved the critical, safety-relevant behaviors from the old inline app.py
routes - especially the CLOSEOUT_REQUIRED completion gate (blocks a route from
being marked Completed if any stop hasn't been dispatcher-closed), the
over-payload/hub-required assignment guards, city-based access restriction,
status-preservation on dispatch, and the Driver-role view restriction on
route-view/route-print. These are the highest-stakes rules in this extraction:
getting the closeout gate or payload check wrong could let an incomplete or
overweight route slip through in a live dispatch operation."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "route-dispatch-blueprint-test-secret")

import app as eoms_app
from routes import route_dispatch as rd_module


class RouteDispatchRoutesRegisteredTests(unittest.TestCase):
    def test_all_nineteen_routes_registered(self):
        rules = {r.rule for r in eoms_app.app.url_map.iter_rules()}
        expected = {
            "/api/dispatch-map-debug", "/api/geocode-stores", "/dispatch-map", "/route-builder",
            "/api/dispatch-board-live", "/api/send-route-sms", "/api/routes", "/api/route/<route_id>",
            "/api/preview-route", "/api/assign-route", "/api/dispatch-route", "/api/update-route-driver",
            "/api/complete-route", "/route-view/<route_id>", "/route-print/<route_id>",
            "/api/unassign-route", "/api/delete-route", "/api/store-status", "/api/unassign-store",
        }
        self.assertTrue(expected.issubset(rules))

    def test_api_bol_untouched_by_this_extraction(self):
        # /api/bol/<store_id> is a separate, out-of-scope endpoint (general BOL
        # editing) that must still be registered from app.py itself.
        rules = {r.rule for r in eoms_app.app.url_map.iter_rules()}
        self.assertIn("/api/bol/<store_id>", rules)


class RouteDispatchTestBase(unittest.TestCase):
    def setUp(self):
        self.client = eoms_app.app.test_client()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.stores_path = Path(self.temp_dir.name) / "stores.json"
        self.routes_path = Path(self.temp_dir.name) / "routes.json"

        # Patch the file-path constants on BOTH app.py and routes/route_dispatch.py.
        # route_dispatch.py did `from app import STORES_FILE, ROUTES_FILE`, which
        # binds the value into its own module namespace at import time - patching
        # only eoms_app.STORES_FILE would leave route_dispatch's own copy (used by
        # its direct read_json(STORES_FILE) calls) pointed at the real data files.
        self.patches = [
            patch.object(eoms_app, "STORES_FILE", self.stores_path),
            patch.object(eoms_app, "ROUTES_FILE", self.routes_path),
            patch.object(rd_module, "STORES_FILE", self.stores_path),
            patch.object(rd_module, "ROUTES_FILE", self.routes_path),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp_dir.cleanup()

    def write_stores(self, stores):
        self.stores_path.write_text(json.dumps(stores), encoding="utf-8")

    def write_routes(self, routes):
        self.routes_path.write_text(json.dumps(routes), encoding="utf-8")

    def read_stores(self):
        return json.loads(self.stores_path.read_text(encoding="utf-8"))

    def read_routes(self):
        return json.loads(self.routes_path.read_text(encoding="utf-8"))

    def call(self, method, path, json_body=None, username="admin", role="Admin", assigned_cities=None):
        with self.client.session_transaction() as session:
            session["logged_in"] = True
            session["username"] = username
        user = {
            "username": username, "display_name": username, "role": role,
            "active": True, "assigned_cities": assigned_cities if assigned_cities is not None else ["All"],
        }
        # Patch current_user on both app.py and route_dispatch.py: functions
        # DEFINED in app.py (current_role, filter_stores_for_user, etc.) look up
        # current_user via app.py's own globals at call time, so patching
        # eoms_app.current_user is enough for those. But route_dispatch.py calls
        # current_user() directly in a few handlers (route_view, api_route_detail,
        # api_send_route_sms) using its own `from app import current_user` binding,
        # which needs its own patch.
        with patch.object(eoms_app, "current_user", return_value=user), \
             patch.object(rd_module, "current_user", return_value=user):
            fn = getattr(self.client, method)
            if json_body is not None:
                return fn(path, json=json_body)
            return fn(path)


def make_store(store_id, **overrides):
    store = {
        "id": store_id,
        "bol": store_id,
        "status": "Unassigned",
        "city": "San Antonio",
        "hub": "San Antonio",
        "lat": 29.53,
        "lng": -98.40,
        "expected_racks": 5,
        "weight": 500,
        "dispatcher_closeout_status": "",
    }
    store.update(overrides)
    return store


class AssignRouteTests(RouteDispatchTestBase):
    def test_requires_hub_when_none_resolvable(self):
        self.write_stores([make_store("s1", hub="")])
        self.write_routes([])
        resp = self.call("post", "/api/assign-route", {"driver": "Bob", "store_ids": ["s1"], "mode": "optimized"})
        payload = resp.get_json()
        self.assertFalse(payload["ok"])
        self.assertTrue(payload.get("hub_required"))

    def test_rejects_stores_outside_allowed_cities(self):
        # store_city_allowed() checks city, hub, dispatch_group, and origin_city -
        # override all the location-ish fields so this genuinely isolates the
        # city-access check rather than accidentally matching on "hub".
        self.write_stores([make_store("s1", city="Dallas", hub="Houston")])
        self.write_routes([])
        resp = self.call(
            "post", "/api/assign-route",
            {"driver": "Bob", "store_ids": ["s1"], "mode": "optimized"},
            role="Dispatcher", assigned_cities=["San Antonio"],
        )
        self.assertEqual(resp.status_code, 403)

    def test_rejects_over_weight_route(self):
        self.write_stores([make_store("s1", weight=30000)])
        self.write_routes([])
        resp = self.call("post", "/api/assign-route", {"driver": "Bob", "store_ids": ["s1"], "mode": "optimized"})
        payload = resp.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("25,001", payload["message"])

    def test_successful_assign_creates_route_and_updates_store(self):
        self.write_stores([make_store("s1")])
        self.write_routes([])
        resp = self.call(
            "post", "/api/assign-route",
            {"driver": "Bob", "driver_phone": "555-1000", "store_ids": ["s1"], "mode": "optimized"},
        )
        payload = resp.get_json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["route"]["route_number"].startswith("RT-"))

        stores = self.read_stores()
        updated = next(s for s in stores if s["id"] == "s1")
        self.assertEqual(updated["status"], "Assigned")
        self.assertEqual(updated["assigned_driver"], "Bob")
        self.assertEqual(updated["driver_status"], "Pending")
        self.assertEqual(updated["dispatcher_closeout_status"], "")

        routes = self.read_routes()
        self.assertEqual(len(routes), 1)


class DispatchRouteTests(RouteDispatchTestBase):
    def make_route(self, **overrides):
        route = {
            "id": "route-1", "route_number": "RT-00001", "driver": "Bob",
            "store_ids": ["s1", "s2"], "hub": "San Antonio",
            "metrics": {"weight": 1000}, "status": "Assigned",
        }
        route.update(overrides)
        return route

    def test_requires_driver_before_dispatch(self):
        self.write_routes([self.make_route(driver="")])
        self.write_stores([make_store("s1"), make_store("s2")])
        resp = self.call("post", "/api/dispatch-route", {"route_id": "route-1"})
        payload = resp.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("driver", payload["message"].lower())

    def test_rejects_over_payload(self):
        self.write_routes([self.make_route(metrics={"weight": 30000})])
        self.write_stores([make_store("s1"), make_store("s2")])
        resp = self.call("post", "/api/dispatch-route", {"route_id": "route-1"})
        payload = resp.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("25,001", payload["message"])

    def test_dispatch_preserves_recovered_and_exception_store_status(self):
        self.write_routes([self.make_route()])
        self.write_stores([
            make_store("s1", status="Recovered"),
            make_store("s2", status="Exception"),
        ])
        resp = self.call("post", "/api/dispatch-route", {"route_id": "route-1"})
        self.assertTrue(resp.get_json()["ok"])

        stores = self.read_stores()
        s1 = next(s for s in stores if s["id"] == "s1")
        s2 = next(s for s in stores if s["id"] == "s2")
        self.assertEqual(s1["status"], "Recovered")
        self.assertEqual(s2["status"], "Exception")

        routes = self.read_routes()
        self.assertEqual(routes[0]["status"], "Dispatched")

    def test_dispatch_sets_assigned_status_for_normal_stores(self):
        self.write_routes([self.make_route()])
        self.write_stores([make_store("s1", status="Assigned"), make_store("s2", status="Assigned")])
        resp = self.call("post", "/api/dispatch-route", {"route_id": "route-1"})
        self.assertTrue(resp.get_json()["ok"])
        stores = self.read_stores()
        self.assertTrue(all(s["status"] == "Assigned" for s in stores))


class CompleteRouteTests(RouteDispatchTestBase):
    def make_route(self):
        return {
            "id": "route-1", "route_number": "RT-00001", "driver": "Bob",
            "store_ids": ["s1", "s2"], "status": "Dispatched",
        }

    def test_blocked_when_any_stop_not_dispatcher_closed(self):
        self.write_routes([self.make_route()])
        self.write_stores([
            make_store("s1", dispatcher_closeout_status="Closed"),
            make_store("s2", dispatcher_closeout_status=""),
        ])
        resp = self.call("post", "/api/complete-route", {"route_id": "route-1"})
        payload = resp.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["code"], "CLOSEOUT_REQUIRED")
        self.assertEqual(len(payload["missing"]), 1)

        # Nothing should have been persisted - the route must still show its
        # original (pre-completion) status on disk.
        routes = self.read_routes()
        self.assertEqual(routes[0]["status"], "Dispatched")
        stores = self.read_stores()
        self.assertTrue(all(s["status"] != "Completed" for s in stores))

    def test_succeeds_when_all_stops_dispatcher_closed(self):
        self.write_routes([self.make_route()])
        self.write_stores([
            make_store("s1", dispatcher_closeout_status="Closed"),
            make_store("s2", dispatcher_closeout_status="Closed"),
        ])
        resp = self.call("post", "/api/complete-route", {"route_id": "route-1"})
        payload = resp.get_json()
        self.assertTrue(payload["ok"])

        routes = self.read_routes()
        self.assertEqual(routes[0]["status"], "Completed")
        stores = self.read_stores()
        self.assertTrue(all(s["status"] == "Completed" for s in stores))

    def test_route_not_found(self):
        self.write_routes([])
        self.write_stores([])
        resp = self.call("post", "/api/complete-route", {"route_id": "nope"})
        payload = resp.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("not found", payload["message"].lower())


class UnassignRouteVsUnassignStoreTests(RouteDispatchTestBase):
    def test_unassign_route_clears_all_stores_and_removes_route(self):
        self.write_routes([{"id": "route-1", "route_number": "RT-00001", "store_ids": ["s1", "s2"]}])
        self.write_stores([make_store("s1", status="Assigned"), make_store("s2", status="Assigned")])
        resp = self.call("post", "/api/unassign-route", {"route_id": "route-1"})
        self.assertTrue(resp.get_json()["ok"])

        stores = self.read_stores()
        self.assertTrue(all(s["status"] == "Unassigned" for s in stores))
        self.assertTrue(all(s["assigned_driver"] == "" for s in stores))
        self.assertEqual(self.read_routes(), [])

    def test_unassign_store_only_removes_one_store_and_recalculates_metrics(self):
        stops = [make_store("s1", status="Assigned"), make_store("s2", status="Assigned")]
        self.write_routes([{
            "id": "route-1", "route_number": "RT-00001", "hub": "San Antonio",
            "store_ids": ["s1", "s2"], "stops": stops,
        }])
        self.write_stores(stops)

        resp = self.call("post", "/api/unassign-store", {"store_id": "s1"})
        self.assertTrue(resp.get_json()["ok"])

        stores = self.read_stores()
        s1 = next(s for s in stores if s["id"] == "s1")
        s2 = next(s for s in stores if s["id"] == "s2")
        self.assertEqual(s1["status"], "Unassigned")
        self.assertEqual(s2["status"], "Assigned")  # untouched

        routes = self.read_routes()
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0]["store_ids"], ["s2"])
        self.assertIn("metrics", routes[0])

    def test_unassign_last_store_prunes_the_route_entirely(self):
        stops = [make_store("s1", status="Assigned")]
        self.write_routes([{
            "id": "route-1", "route_number": "RT-00001", "hub": "San Antonio",
            "store_ids": ["s1"], "stops": stops,
        }])
        self.write_stores(stops)

        resp = self.call("post", "/api/unassign-store", {"store_id": "s1"})
        self.assertTrue(resp.get_json()["ok"])
        self.assertEqual(self.read_routes(), [])


class DeleteRouteTests(RouteDispatchTestBase):
    def test_delete_missing_route_returns_404(self):
        self.write_routes([])
        self.write_stores([])
        resp = self.call("post", "/api/delete-route", {"route_id": "nope"})
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(resp.get_json()["ok"])


class RouteViewPrintDriverRestrictionTests(RouteDispatchTestBase):
    """The global app.py `enforce_login` before_request hook already restricts
    Driver-role sessions to /driver and /api/driver/* paths, so a Driver never
    actually reaches route_view/route_print through a real request - the
    in-handler ownership check (current_role()=='Driver' and username/display
    name match) is a pre-existing belt-and-suspenders check underneath that
    gate, unchanged from the original app.py. We verify it directly at the
    function level (bypassing routing/enforce_login) so the moved logic is
    still exercised."""

    def test_driver_cannot_view_a_route_assigned_to_someone_else(self):
        self.write_routes([{"id": "route-1", "route_number": "RT-00001", "driver": "OtherDriver"}])
        self.write_stores([])
        user = {"username": "bob", "display_name": "bob", "role": "Driver", "active": True, "assigned_cities": ["San Antonio"]}
        with eoms_app.app.test_request_context("/route-view/route-1"):
            with patch.object(rd_module, "current_user", return_value=user), \
                 patch.object(rd_module, "current_role", return_value="Driver"):
                resp = rd_module.route_view("route-1")
        self.assertEqual(resp[1], 403)

    def test_driver_can_view_their_own_route(self):
        self.write_routes([{"id": "route-1", "route_number": "RT-00001", "driver": "bob", "stops": []}])
        self.write_stores([])
        user = {"username": "bob", "display_name": "bob", "role": "Driver", "active": True, "assigned_cities": ["San Antonio"]}
        with eoms_app.app.test_request_context("/route-view/route-1"):
            with patch.object(rd_module, "current_user", return_value=user), \
                 patch.object(rd_module, "current_role", return_value="Driver"):
                resp = rd_module.route_view("route-1")
        # A successful render returns a plain string/Response, not a (body, status) tuple.
        self.assertNotIsInstance(resp, tuple)

    def test_missing_route_returns_404_text(self):
        self.write_routes([])
        self.write_stores([])
        resp = self.call("get", "/route-view/nope")
        self.assertEqual(resp.status_code, 404)


class StoreStatusTests(RouteDispatchTestBase):
    def test_invalid_status_rejected(self):
        self.write_stores([make_store("s1")])
        resp = self.call("post", "/api/store-status", {"store_id": "s1", "status": "Not A Real Status"})
        payload = resp.get_json()
        self.assertFalse(payload["ok"])

    def test_valid_status_update_applies(self):
        self.write_stores([make_store("s1")])
        resp = self.call("post", "/api/store-status", {"store_id": "s1", "status": "Need Review"})
        payload = resp.get_json()
        self.assertTrue(payload["ok"])
        stores = self.read_stores()
        self.assertEqual(stores[0]["status"], "Need Review")

    def test_missing_store_returns_message(self):
        self.write_stores([])
        resp = self.call("post", "/api/store-status", {"store_id": "nope", "status": "Assigned"})
        payload = resp.get_json()
        self.assertFalse(payload["ok"])


if __name__ == "__main__":
    unittest.main()
