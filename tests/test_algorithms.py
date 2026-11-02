import unittest

import app


class TravelSearchTests(unittest.TestCase):
    def test_astar_returns_connected_route_and_totals(self):
        result = app.astar("Madanapalle", "Kochi", preference="distance")
        self.assertEqual(result["path"][0], "Madanapalle")
        self.assertEqual(result["path"][-1], "Kochi")
        self.assertGreater(result["total"]["distance"], 0)
        self.assertGreater(len(result["explored"]), 0)
        self.assertTrue(all(any(edge["city"] == b for edge in app.GRAPH[a])
                            for a, b in zip(result["path"], result["path"][1:])))

    def test_astar_honors_ordered_waypoints(self):
        result = app.astar("Madanapalle", "Kochi", ["Tirupati"], "cost")
        self.assertLess(result["path"].index("Tirupati"), result["path"].index("Kochi"))

    def test_alternative_routes_do_not_repeat_cities(self):
        routes = app.route_alternatives("Madanapalle", "Kochi", ["Tirupati"], "distance")
        self.assertTrue(all(len(route["path"]) == len(set(route["path"])) for route in routes))
        self.assertTrue(all("Tirupati" in route["path"] for route in routes))

    def test_preference_changes_search_objective(self):
        for preference in ("distance", "cost", "time"):
            result = app.astar("Madanapalle", "Chennai", preference=preference)
            self.assertGreater(result["total"][app.METRICS[preference]], 0)

    def test_ao_star_solves_required_legs(self):
        result = app.ao_star("Madanapalle", "Kochi", ["Tirupati"], "distance")
        self.assertEqual(result["path"][0], "Madanapalle")
        self.assertEqual(result["path"][-1], "Kochi")
        self.assertIn("Tirupati", result["path"])
        self.assertEqual(len(result["path"]), len(set(result["path"])))
        self.assertEqual(result["steps"][0]["type"], "AND expansion")
        self.assertTrue(all(step["type"] == "OR decision" for step in result["steps"][1:]))
        self.assertTrue(all(segment["expansions"] for segment in result["alternatives"]))
        for preference in app.METRICS:
            ao_result = app.ao_star("Madanapalle", "Kochi", ["Tirupati"], preference)
            a_result = app.astar("Madanapalle", "Kochi", ["Tirupati"], preference)
            self.assertEqual(
                ao_result["total"][app.METRICS[preference]],
                a_result["total"][app.METRICS[preference]],
            )

    def test_flask_api_plans_trip_and_rejects_bad_city(self):
        client = app.app.test_client()
        response = client.post("/api/plan", json={
            "start": "Madanapalle", "destination": "Kochi", "preference": "distance"
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("astar", response.get_json())
        self.assertIn("ao", response.get_json())
        with_stop = client.post("/api/plan", json={
            "start": "Madanapalle", "destination": "Kochi",
            "waypoints": ["Tirupati"], "preference": "cost"
        }).get_json()
        self.assertIn("Tirupati", with_stop["astar"]["path"])
        self.assertIn("Tirupati", with_stop["ao"]["path"])
        invalid = client.post("/api/plan", json={
            "start": "Atlantis", "destination": "Kochi", "preference": "distance"
        })
        self.assertEqual(invalid.status_code, 400)
        malformed = client.post("/api/plan", json=["Madanapalle", "Kochi"])
        self.assertEqual(malformed.status_code, 400)


if __name__ == "__main__":
    unittest.main()
