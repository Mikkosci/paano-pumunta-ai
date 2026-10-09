"""Deterministic router for Paano Pumunta AI.

Dijkstra over (stop, route) states so transfers are counted correctly.
This is the ONLY component that chooses routes. No fares anywhere.
"""
import difflib
import heapq
import json
import re
from typing import Any, Dict, List, Optional

PREFERENCES = ("fastest", "fewest_stops", "fewest_transfers")

MODE_LABELS = {
    "fastest": "Pinakamabilis",
    "fewest_stops": "Pinakakaunting hinto",
    "fewest_transfers": "Pinakakaunting lipat",
}

# rough minutes per hop by vehicle type -- estimates, not schedules
MINS_PER_HOP = {"Train": 3, "Bus": 4, "Jeepney": 5, "UV Express": 5, "Walk": 5}
DEFAULT_MINS_PER_HOP = 5
TRANSFER_MINS = 5

TYPE_ICON = {"Train": "🚆", "Bus": "🚌", "Jeepney": "🚙", "UV Express": "🚐", "Walk": "🚶"}

# words users type -> what they match in a route's name or type
AVOID_SYNONYMS = {
    "train": ["train"],
    "tren": ["train"],
    "jeep": ["jeep"],
    "jeepney": ["jeep"],
    "dyip": ["jeep"],
    "uv": ["uv"],
    "bus": ["bus"],
    "carousel": ["carousel"],
}

_ABBREV = [(r"\bavenue\b", "ave"), (r"\bboulevard\b", "blvd"), (r"\bstreet\b", "st")]


def _norm(text: str) -> str:
    t = text.lower().strip()
    t = re.sub(r"[^\w\s&-]", " ", t)
    for pat, rep in _ABBREV:
        t = re.sub(pat, rep, t)
    return re.sub(r"\s+", " ", t).strip()


class Router:
    def __init__(self, routes_data: List[Dict]):
        self.routes = routes_data
        self.nodes = sorted({s for r in self.routes for s in r["stops"]})
        # stop -> list of (neighbor, route dict); keeps every parallel route
        self.adj: Dict[str, List[tuple]] = {n: [] for n in self.nodes}
        for route in self.routes:
            stops = route["stops"]
            for a, b in zip(stops, stops[1:]):
                self.adj[a].append((b, route))
                self.adj[b].append((a, route))
        self._norm_nodes = {_norm(n): n for n in self.nodes}

    # ------------------------------------------------------------ places
    def resolve_place(self, name: str) -> Optional[str]:
        """Map free text to a known stop, tolerating case, abbreviations and typos."""
        if not name or not name.strip():
            return None
        q = _norm(name)
        if q in self._norm_nodes:
            return self._norm_nodes[q]
        # whole-word containment, e.g. "Antipolo" -> "Antipolo Simbahan"
        words = set(q.split())
        hits = [n for k, n in self._norm_nodes.items()
                if re.search(r"\b" + re.escape(k) + r"\b", q)
                or (words and words <= set(k.split()))]
        if hits:
            return min(hits, key=len)
        close = difflib.get_close_matches(q, list(self._norm_nodes), n=1, cutoff=0.8)
        return self._norm_nodes[close[0]] if close else None

    find_node = resolve_place  # backwards-compatible name

    # ------------------------------------------------------------ rules parser
    def parse_query(self, query: str) -> Dict[str, Any]:
        """Rules-based fallback parser. Returns origin, dest, line, preference, avoid."""
        ql = query.lower()
        result = {"origin": None, "dest": None, "line": None, "preference": None, "avoid": []}

        m = re.search(r"\b(?:galing(?:\s+sa)?|mula(?:\s+sa)?|from)\s+(.+?)\s+"
                      r"(?:hanggang(?:\s+sa)?|papuntang|papunta(?:\s+sa)?|to)\s+(.+)", query, re.I)
        if not m:
            m = re.search(r"(.+?)\s+(?:to|hanggang|papuntang|papunta(?:\s+sa)?)\s+(.+)", query, re.I)
        if m:
            result["origin"] = self._resolve_fragment(m.group(1))
            result["dest"] = self._resolve_fragment(m.group(2))

        for route in self.routes:
            if route["type"] != "Walk" and route["name"].lower() in ql:
                result["line"] = route["name"]
                break
        else:
            for kw in ("mrt", "lrt", "jeep", "uv", "bus"):
                if re.search(r"\b" + kw, ql):
                    result["line"] = kw.upper()
                    break

        if re.search(r"\b(diretso|direkta|direktso|direct|kaunting lipat|less transfers?)\b", ql):
            result["preference"] = "fewest_transfers"
        elif re.search(r"\b(kaunting hinto|fewer stops|less stops)\b", ql):
            result["preference"] = "fewest_stops"
        elif re.search(r"\b(mabilis|mabilisan|fastest|quick)\b", ql):
            result["preference"] = "fastest"

        m = re.search(r"\b(?:iwas|iwasan|walang|avoid|no|ayaw ng)\s+(\w[\w-]*)", ql)
        if m:
            result["avoid"] = [m.group(1)]
            # "walang jeep" is a constraint, not a question about the jeep line
            if result["line"] and result["line"].lower() in m.group(1):
                result["line"] = None
        return result

    def _resolve_fragment(self, text: str) -> Optional[str]:
        text = re.split(r"[?,.!]| na | iwas | pero | kung ", text)[0]
        words = text.split()
        # try longest trailing / leading sub-phrases so filler words don't break matching
        for size in range(len(words), 0, -1):
            for start in range(0, len(words) - size + 1):
                hit = self.resolve_place(" ".join(words[start:start + size]))
                if hit:
                    return hit
        return None

    # ------------------------------------------------------------ routing
    def _avoided(self, route: Dict, avoid: List[str]) -> bool:
        if route["type"] == "Walk":
            return False
        hay = (route["name"] + " " + route["type"]).lower()
        for term in avoid or []:
            t = term.lower().strip()
            for needle in AVOID_SYNONYMS.get(t, [t]):
                if needle and needle in hay:
                    return True
        return False

    def find_path(self, origin: str, dest: str, preference: str = "fastest",
                  avoid: Optional[List[str]] = None) -> Optional[Dict]:
        """Best single itinerary for one preference, or None."""
        o, d = self.resolve_place(origin), self.resolve_place(dest)
        if not o or not d or o == d:
            return None

        def cost(mins, hops, boards):
            if preference == "fewest_stops":
                return (hops, boards, mins)
            if preference == "fewest_transfers":
                return (boards, mins, hops)
            return (mins, boards, hops)

        start = (o, None)
        best = {start: cost(0, 0, 0)}
        prev: Dict[tuple, tuple] = {}
        pq = [(best[start], 0, 0, 0, o, None)]
        counter = 0
        goal = None
        while pq:
            c, mins, hops, boards, stop, rname = heapq.heappop(pq)
            if c > best.get((stop, rname), c):
                continue
            if stop == d:
                goal = (stop, rname)
                break
            for nxt, route in self.adj[stop]:
                if self._avoided(route, avoid):
                    continue
                is_walk = route["type"] == "Walk"
                switching = route["name"] != rname
                step = MINS_PER_HOP.get(route["type"], DEFAULT_MINS_PER_HOP)
                if switching and boards > 0 and not is_walk:
                    step += TRANSFER_MINS
                nb = boards + (1 if switching and not is_walk else 0)
                nh = hops + (0 if is_walk else 1)
                nm = mins + step
                nc = cost(nm, nh, nb)
                key = (nxt, route["name"])
                if nc < best.get(key, (float("inf"),)):
                    best[key] = nc
                    prev[key] = ((stop, rname), route)
                    counter += 1
                    heapq.heappush(pq, (nc, nm, nh, nb, nxt, route["name"]))
        if goal is None:
            return None

        edges = []
        cur = goal
        while cur in prev:
            parent, route = prev[cur]
            edges.append((parent[0], cur[0], route))
            cur = parent
        edges.reverse()
        return self._to_itinerary(edges, o, d)

    def _to_itinerary(self, edges, origin, dest) -> Dict:
        legs = []
        for a, b, route in edges:
            if legs and legs[-1]["route"] == route["name"]:
                legs[-1]["stops"].append(b)
            else:
                legs.append({"type": route["type"], "route": route["name"],
                             "stops": [a, b], "details": route.get("details", "")})
        for leg in legs:
            leg["hops"] = len(leg["stops"]) - 1
            leg["mins"] = leg["hops"] * MINS_PER_HOP.get(leg["type"], DEFAULT_MINS_PER_HOP)
            leg["to"] = leg["stops"][-1]
        rides = [l for l in legs if l["type"] != "Walk"]
        transfers = max(len(rides) - 1, 0)
        return {
            "origin": origin,
            "destination": dest,
            "legs": legs,
            "stops": sum(l["hops"] for l in rides),
            "transfers": transfers,
            "mins": sum(l["mins"] for l in legs) + transfers * TRANSFER_MINS,
            "modes": [],
        }

    def plan(self, origin: str, dest: str, avoid: Optional[List[str]] = None,
             preference: Optional[str] = None) -> List[Dict]:
        """Distinct best itineraries for each preference.

        Each option's "modes" lists the preferences it wins. If `preference`
        is given, the option that wins it comes first.
        """
        options: List[Dict] = []
        for pref in PREFERENCES:
            it = self.find_path(origin, dest, pref, avoid)
            if not it:
                continue
            sig = [(l["route"], tuple(l["stops"])) for l in it["legs"]]
            same = next((o for o in options
                         if [(l["route"], tuple(l["stops"])) for l in o["legs"]] == sig), None)
            if same:
                same["modes"].append(pref)
            else:
                it["modes"] = [pref]
                options.append(it)
        if preference in PREFERENCES:
            options.sort(key=lambda o: preference not in o["modes"])
        return options

    # ------------------------------------------------------------ lines
    def line_info(self, line_name: str) -> Optional[Dict]:
        if not line_name:
            return None
        q = line_name.lower()
        rides = [r for r in self.routes if r["type"] != "Walk"]
        for r in rides:
            if r["name"].lower() == q:
                return r
        for r in rides:
            if q in r["name"].lower() or q in r["type"].lower():
                return r
        return None


def load_data(filepath: str) -> List[Dict]:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: File {filepath} not found")
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {filepath}: {e}")
    return []


def describe_itinerary(origin: str, dest: str, itinerary: Dict) -> str:
    """Deterministic Taglish description. Never mentions fares."""
    if not itinerary or not itinerary.get("legs"):
        return "Walang makitang ruta."
    lines = [f"Mula {origin} papuntang {dest}:"]
    legs = itinerary["legs"]
    for i, leg in enumerate(legs, 1):
        icon = TYPE_ICON.get(leg["type"], "🚏")
        if leg["type"] == "Walk":
            lines.append(f"{i}. {icon} Maglakad mula {leg['stops'][0]} papuntang {leg['to']}.")
        else:
            lines.append(f"{i}. {icon} Sumakay ng {leg['route']} ({leg['type']}) mula "
                         f"{leg['stops'][0]} hanggang {leg['to']} -- {leg['hops']} hinto, "
                         f"~{leg['mins']} min.")
        if i < len(legs) and leg["type"] != "Walk":
            nxt = legs[i]["type"]
            lines.append(f"   🔄 Lipat sa {leg['to']}." if nxt != "Walk" else f"   ⬇️ Bumaba sa {leg['to']}.")
    lines.append(f"Kabuuan: ~{itinerary['mins']} min (rough estimate), "
                 f"{itinerary['stops']} hinto, {itinerary['transfers']} lipat.")
    return "\n".join(lines)


def describe_plan(origin: str, dest: str, options: List[Dict]) -> str:
    if not options:
        return "Walang natagpuang ruta."
    return "\n\n".join(f"【Opsyon {i}】\n" + describe_itinerary(origin, dest, opt)
                       for i, opt in enumerate(options[:3], 1))
