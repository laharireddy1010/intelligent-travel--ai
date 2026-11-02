from __future__ import annotations

import heapq
import itertools
import math
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)


# Coordinates are used only for admissible straight-line A* heuristics and the
# local SVG map; road distances and costs come from the network below.
CITIES = {
    "Madanapalle": (13.55, 78.50),
    "Tirupati": (13.63, 79.42),
    "Bengaluru": (12.97, 77.59),
    "Chennai": (13.08, 80.27),
    "Hyderabad": (17.39, 78.49),
    "Vijayawada": (16.51, 80.65),
    "Kochi": (9.93, 76.27),
    "Munnar": (10.09, 77.06),
    "Mysuru": (12.30, 76.64),
    "Coimbatore": (11.02, 76.96),
}

# Undirected road links: distance in km, approximate road speed in km/h,
# and sample road/toll cost in INR per km.
ROADS = [
    ("Madanapalle", "Tirupati", 110, 58, 8.0),
    ("Madanapalle", "Bengaluru", 120, 62, 9.0),
    ("Madanapalle", "Chennai", 190, 65, 10.0),
    ("Madanapalle", "Hyderabad", 510, 68, 9.0),
    ("Madanapalle", "Vijayawada", 430, 65, 9.0),
    ("Tirupati", "Chennai", 135, 68, 10.0),
    ("Tirupati", "Bengaluru", 250, 65, 9.0),
    ("Tirupati", "Vijayawada", 380, 65, 9.0),
    ("Tirupati", "Hyderabad", 560, 68, 9.0),
    ("Bengaluru", "Chennai", 350, 78, 11.0),
    ("Bengaluru", "Hyderabad", 570, 76, 10.0),
    ("Bengaluru", "Kochi", 550, 65, 11.0),
    ("Bengaluru", "Mysuru", 145, 70, 9.0),
    ("Bengaluru", "Coimbatore", 365, 70, 10.0),
    ("Chennai", "Hyderabad", 630, 75, 10.0),
    ("Chennai", "Vijayawada", 450, 72, 10.0),
    ("Chennai", "Kochi", 690, 68, 11.0),
    ("Hyderabad", "Vijayawada", 275, 78, 10.0),
    ("Hyderabad", "Kochi", 1000, 68, 10.0),
    ("Vijayawada", "Kochi", 900, 65, 11.0),
    ("Vijayawada", "Bengaluru", 650, 70, 10.0),
    ("Kochi", "Munnar", 130, 45, 8.0),
    ("Kochi", "Coimbatore", 190, 60, 9.0),
    ("Munnar", "Coimbatore", 160, 48, 8.0),
    ("Munnar", "Chennai", 560, 62, 10.0),
    ("Mysuru", "Kochi", 390, 58, 10.0),
    ("Mysuru", "Coimbatore", 200, 58, 9.0),
]
GRAPH: dict[str, list[dict]] = {city: [] for city in CITIES}
for city_a, city_b, distance, speed, rate in ROADS:
    edge = {"distance": distance, "duration": distance / speed, "cost": distance * rate}
    GRAPH[city_a].append({"city": city_b, **edge})
    GRAPH[city_b].append({"city": city_a, **edge})

METRICS = {"distance": "distance", "cost": "cost", "time": "duration"}
HEURISTIC_SCALE = {"distance": 1.0, "cost": 6.0, "time": 1 / 120}


def straight_line(city_a: str, city_b: str) -> float:
    """Return great-circle distance in kilometers."""
    lat1, lon1 = map(math.radians, CITIES[city_a])
    lat2, lon2 = map(math.radians, CITIES[city_b])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def heuristic(city: str, targets: list[str], metric: str) -> float:
    if not targets:
        return 0
    scale = HEURISTIC_SCALE[metric]
    return (straight_line(city, targets[0]) + sum(
        straight_line(a, b) for a, b in zip(targets, targets[1:])
    )) * scale


def _advance_waypoints(city: str, index: int, waypoints: list[str]) -> int:
    while index < len(waypoints) and city == waypoints[index]:
        index += 1
    return index


def astar(start: str, destination: str, waypoints: list[str] | None = None,
          preference: str = "distance", blocked_edges: set[frozenset[str]] | None = None) -> dict:
    """A* over city, waypoint-progress, and visited-city states."""
    if preference not in METRICS:
        raise ValueError("Preference must be distance, cost, or time.")
    if start not in GRAPH or destination not in GRAPH:
        raise ValueError("Choose cities from the available road network.")
    stops = list(waypoints or []) + [destination]
    if any(city not in GRAPH for city in stops):
        raise ValueError("One or more selected stops are not in the road network.")
    if start == destination and not waypoints:
        return {"path": [start], "explored": [start], "steps": [], "total": _zero_totals()}

    start_index = _advance_waypoints(start, 0, stops)
    start_state = (start, start_index, frozenset((start,)))
    serial = itertools.count()
    queue = [(heuristic(start, stops[start_index:], preference), 0.0, next(serial), start_state)]
    best_cost = {start_state: 0.0}
    parent: dict[tuple, tuple] = {}
    parent_edge: dict[tuple, dict] = {}
    explored: list[str] = []
    steps: list[dict] = []
    blocked_edges = blocked_edges or set()
    goal_state = None

    while queue:
        _, current_cost, _, state = heapq.heappop(queue)
        if current_cost > best_cost.get(state, math.inf) + 1e-9:
            continue
        city, index, visited = state
        explored.append(city)
        steps.append({"city": city, "g": round(current_cost, 2),
                      "h": round(heuristic(city, stops[index:], preference), 2),
                      "f": round(current_cost + heuristic(city, stops[index:], preference), 2)})
        if index == len(stops):
            goal_state = state
            break
        for edge in GRAPH[city]:
            next_city = edge["city"]
            if frozenset((city, next_city)) in blocked_edges:
                continue
            next_index = _advance_waypoints(next_city, index, stops)
            if next_city in visited and not (next_city == destination and next_index == len(stops)):
                continue
            next_state = (next_city, next_index, visited | {next_city})
            new_cost = current_cost + edge[METRICS[preference]]
            if new_cost + 1e-9 >= best_cost.get(next_state, math.inf):
                continue
            best_cost[next_state] = new_cost
            parent[next_state] = state
            parent_edge[next_state] = edge
            h = heuristic(next_city, stops[next_index:], preference)
            heapq.heappush(queue, (new_cost + h, new_cost, next(serial), next_state))

    if goal_state is None:
        raise ValueError(f"No route found from {start} through the selected stops to {destination}.")
    states = [goal_state]
    while states[-1] != start_state:
        states.append(parent[states[-1]])
    states.reverse()
    path = [state[0] for state in states]
    total = _zero_totals()
    for state in states[1:]:
        edge = parent_edge[state]
        for key in total:
            total[key] += edge[key]
    total = {key: round(value, 2) for key, value in total.items()}
    return {"path": path, "explored": explored, "steps": steps, "total": total}


def _zero_totals() -> dict:
    return {"distance": 0.0, "duration": 0.0, "cost": 0.0}


def route_alternatives(start: str, destination: str, waypoints: list[str],
                       preference: str, limit: int = 3) -> list[dict]:
    """Generate distinct valid alternatives by rerunning A* with route edges blocked."""
    first = astar(start, destination, waypoints, preference)
    candidates = {tuple(first["path"]): first}
    for a, b in zip(first["path"], first["path"][1:]):
        try:
            route = astar(start, destination, waypoints, preference, {frozenset((a, b))})
        except ValueError:
            continue
        candidates.setdefault(tuple(route["path"]), route)
    key = METRICS[preference]
    return sorted(candidates.values(), key=lambda route: (route["total"][key], route["total"]["distance"]))[:limit]


def _ao_star_route(start: str, destination: str, waypoints: list[str], preference: str) -> dict:
    """Run AO* over OR city states and AND road-edge-plus-continuation options."""
    metric = METRICS[preference]
    if start not in GRAPH or destination not in GRAPH:
        raise ValueError("Choose cities from the available road network.")
    stops = waypoints + [destination]
    if any(city not in GRAPH for city in stops):
        raise ValueError("One or more selected stops are not in the road network.")
    start_index = _advance_waypoints(start, 0, stops)
    if start_index == len(stops):
        return {"path": [start], "total": _zero_totals(), "expansions": []}

    root = (start, start_index, frozenset((start,)))
    states: dict[tuple, dict] = {}
    expansions: list[tuple] = []

    def state_for(city: str, index: int, visited: frozenset[str]) -> tuple:
        key = (city, index, visited)
        if key not in states:
            is_goal = index == len(stops)
            estimate = 0 if is_goal else heuristic(city, stops[index:], preference)
            states[key] = {
                "city": city, "index": index, "visited": visited, "value": estimate,
                "expanded": is_goal, "solved": is_goal, "options": [], "selected": None,
            }
        return key

    def expand(key: tuple) -> None:
        node = states[key]
        node["expanded"] = True
        expansions.append(key)
        for edge in GRAPH[node["city"]]:
            next_city = edge["city"]
            next_index = _advance_waypoints(next_city, node["index"], stops)
            if next_city in node["visited"] and not (
                    next_city == destination and next_index == len(stops)):
                continue
            child = state_for(next_city, next_index, node["visited"] | {next_city})
            node["options"].append({"edge": edge, "child": child})
        if not node["options"]:
            node["value"] = math.inf
            node["solved"] = True

    def back_up_costs() -> None:
        # Every AND option adds one edge and a child OR state. Visited sets
        # grow strictly, so descending set size is a valid backup order.
        for node in sorted(states.values(), key=lambda item: len(item["visited"]), reverse=True):
            if not node["expanded"] or not node["options"]:
                continue
            for option in node["options"]:
                child = states[option["child"]]
                option["value"] = option["edge"][metric] + child["value"]
                option["solved"] = child["solved"]
            node["selected"] = min(range(len(node["options"])),
                                   key=lambda index: node["options"][index]["value"])
            selected = node["options"][node["selected"]]
            node["value"] = selected["value"]
            node["solved"] = selected["solved"]

    root = state_for(start, start_index, frozenset((start,)))
    while not states[root]["solved"]:
        key = root
        visited_policy: set[tuple] = set()
        while states[key]["expanded"] and states[key]["options"]:
            if key in visited_policy:
                raise RuntimeError("AO* selected a cyclic partial solution.")
            visited_policy.add(key)
            option = states[key]["options"][states[key]["selected"]]
            key = option["child"]
            if not states[key]["expanded"]:
                break
        if states[key]["expanded"]:
            raise ValueError(f"No route found from {start} to {destination}.")
        expand(key)
        back_up_costs()

    if math.isinf(states[root]["value"]):
        raise ValueError(f"No route found from {start} to {destination}.")

    path = [start]
    key = root
    total = _zero_totals()
    while states[key]["index"] != len(stops):
        node = states[key]
        option = node["options"][node["selected"]]
        edge = option["edge"]
        next_city = edge["city"]
        path.append(next_city)
        for name in total:
            total[name] += edge[name]
        key = option["child"]

    return {
        "path": path,
        "total": {name: round(value, 2) for name, value in total.items()},
        "expansions": [{
            "city": states[key]["city"],
            "choices": len(states[key]["options"]),
            "selected": states[key]["options"][states[key]["selected"]]["edge"]["city"],
            "estimate": round(states[key]["value"], 2),
        } for key in expansions if states[key]["options"] and states[key]["solved"]],
    }


def ao_star(start: str, destination: str, waypoints: list[str], preference: str) -> dict:
    """Find an AO* solution graph while satisfying all ordered journey legs."""
    route = _ao_star_route(start, destination, waypoints, preference)
    targets = waypoints + [destination]
    leg_paths = []
    offset = 0
    for target in targets:
        end = len(route["path"]) - 1 if target == destination else route["path"].index(target, offset + 1)
        leg_paths.append(route["path"][offset:end + 1])
        offset = end

    steps: list[dict] = []
    selected_routes = []
    for leg_index, path in enumerate(leg_paths, 1):
        leg_total = _zero_totals()
        for city_a, city_b in zip(path, path[1:]):
            edge = next(edge for edge in GRAPH[city_a] if edge["city"] == city_b)
            for name in leg_total:
                leg_total[name] += edge[name]
        relevant = [item for item in route["expansions"] if item["city"] in path]
        selected_routes.append({
            "path": path,
            "total": {name: round(value, 2) for name, value in leg_total.items()},
            "expansions": relevant,
        })
        steps.append({
            "type": "OR decision",
            "message": f"Leg {leg_index}: AO* selected this segment after expanding {len(relevant)} OR state(s) and backing up AND costs.",
            "choices": relevant,
            "selected": path,
            "cost": leg_total[METRICS[preference]],
        })

    steps.insert(0, {
        "type": "AND expansion",
        "message": f"The journey requires all {len(leg_paths)} requested leg(s); AO* sums their selected solution costs.",
        "selected": route["path"],
        "cost": route["total"][METRICS[preference]],
    })
    return {
        "path": route["path"],
        "total": route["total"],
        "steps": steps,
        "alternatives": selected_routes,
    }


def _validated_request(data: dict) -> tuple[str, str, list[str], str]:
    start = data.get("start")
    destination = data.get("destination")
    waypoints = data.get("waypoints", [])
    preference = data.get("preference", "distance")
    if not isinstance(start, str) or not isinstance(destination, str):
        raise ValueError("Select both a starting city and a destination.")
    if not isinstance(waypoints, list) or not all(isinstance(city, str) for city in waypoints):
        raise ValueError("Stops must be a list of city names.")
    if len(set(waypoints)) != len(waypoints) or any(
            city in (start, destination) for city in waypoints):
        raise ValueError("Optional stops must be unique and different from the start and destination.")
    if not isinstance(preference, str) or preference not in METRICS:
        raise ValueError("Choose shortest distance, lowest cost, or fastest journey.")
    if start == destination and not waypoints:
        raise ValueError("Starting city and destination must be different.")
    return start, destination, waypoints, preference


@app.get("/")
def home():
    return render_template("index.html", cities=sorted(CITIES))


@app.get("/api/network")
def network():
    return jsonify({
        "cities": [{"name": city, "lat": coord[0], "lon": coord[1]} for city, coord in CITIES.items()],
        "roads": [{"from": a, "to": b, "distance": d} for a, b, d, _, _ in ROADS],
    })


@app.post("/api/plan")
def plan():
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object.")
        start, destination, waypoints, preference = _validated_request(data)
        optimal = astar(start, destination, waypoints, preference)
        alternatives = route_alternatives(start, destination, waypoints, preference)
        ao_result = ao_star(start, destination, waypoints, preference)
        return jsonify({
            "astar": optimal,
            "alternatives": alternatives,
            "ao": ao_result,
            "preference": preference,
        })
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


if __name__ == "__main__":
    app.run(debug=True)
