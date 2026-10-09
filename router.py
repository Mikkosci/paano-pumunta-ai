"""
Router module for Paano Pumunta AI
Uses Dijkstra's algorithm for finding optimal routes
"""

import json
import heapq
from typing import List, Dict, Optional, Tuple, Any
from collections import defaultdict


class Router:
    """Transit router using Dijkstra's algorithm"""
    
    def __init__(self, routes_data: List[Dict]):
        self.routes = routes_data
        self.graph = self._build_graph()
        self.nodes = self._extract_nodes()
        self.node_aliases = self._build_aliases()
        
    def _build_graph(self) -> Dict[str, Dict[str, Dict]]:
        """Build adjacency list graph from routes"""
        graph = defaultdict(dict)
        
        for route in self.routes:
            stops = route["stops"]
            route_name = route["name"]
            route_type = route["type"]
            
            for i in range(len(stops) - 1):
                stop1 = stops[i]
                stop2 = stops[i + 1]
                
                # Add forward direction
                if stop2 not in graph[stop1]:
                    graph[stop1][stop2] = {
                        "route": route_name,
                        "type": route_type,
                        "stops": [stop1, stop2],
                        "hops": 1,
                        "details": f"via {route_name}"
                    }
                else:
                    # Keep the first encountered route
                    pass
                
                # Add reverse direction
                if stop1 not in graph[stop2]:
                    graph[stop2][stop1] = {
                        "route": route_name,
                        "type": route_type,
                        "stops": [stop2, stop1],
                        "hops": 1,
                        "details": f"via {route_name} (reverse)"
                    }
        
        return dict(graph)
    
    def _extract_nodes(self) -> List[str]:
        """Extract all unique stops from routes"""
        nodes = set()
        for route in self.routes:
            for stop in route["stops"]:
                nodes.add(stop)
        return sorted(list(nodes))
    
    def _build_aliases(self) -> Dict[str, str]:
        """Build alias mapping for common names"""
        aliases = {}
        for node in self.nodes:
            # Add lowercase version
            aliases[node.lower()] = node
            # Add common abbreviations
            if "MRT" in node or "LRT" in node:
                aliases[node.replace(" MRT", "").replace(" LRT", "").lower()] = node
        return aliases
    
    def find_node(self, name: str) -> Optional[str]:
        """Find exact or alias match for a node"""
        if not name:
            return None
        
        name_lower = name.lower().strip()
        
        # Exact match
        if name in self.nodes:
            return name
        
        # Alias match
        if name_lower in self.node_aliases:
            return self.node_aliases[name_lower]
        
        # Partial match
        for node in self.nodes:
            if name_lower in node.lower() or node.lower() in name_lower:
                return node
        
        return None
    
    def parse_query(self, query: str) -> Dict[str, Any]:
        """Parse user query into structured format"""
        query_lower = query.lower()
        
        result = {
            "origin": None,
            "dest": None,
            "line": None,
            "preference": None,
            "avoid": None
        }
        
        # Check for line queries
        line_keywords = ["mrt", "lrt", "jeep", "uv", "bus", "halinan"]
        for keyword in line_keywords:
            if keyword in query_lower:
                result["line"] = keyword.upper()
                break
        
        # Extract origin and destination
        # Look for "galing" (from) and "hanggang"/"to" (to)
        if "galing" in query_lower:
            parts = query.split("galing")
            if len(parts) > 1:
                origin_part = parts[1].split("hanggang")[0].split("to")[0].strip()
                dest_part = parts[1].split("hanggang")[-1].split("to")[-1].strip() if "hanggang" in query_lower else ""
                
                result["origin"] = self.find_node(origin_part)
                if dest_part:
                    result["dest"] = self.find_node(dest_part)
        
        # Try direct extraction
        if not result["origin"] or not result["dest"]:
            # Split by common separators
            separators = ["to", "hanggang", "punta", "papunta"]
            for sep in separators:
                if sep in query_lower:
                    parts = query.split(sep)
                    if len(parts) >= 2:
                        if not result["origin"]:
                            result["origin"] = self.find_node(parts[0].strip())
                        if not result["dest"]:
                            result["dest"] = self.find_node(parts[1].strip())
        
        # Check for preferences
        if "diretso" in query_lower or "direct" in query_lower:
            result["preference"] = "direct"
        elif "less" in query_lower or "kaunti" in query_lower:
            result["preference"] = "fewest_stops"
        
        # Check for avoidances
        if "iwas" in query_lower or "avoid" in query_lower:
            if "mrt" in query_lower or "train" in query_lower:
                result["avoid"] = "train"
            elif "jeep" in query_lower:
                result["avoid"] = "jeep"
            elif "uv" in query_lower:
                result["avoid"] = "uv"
        
        return result
    
    def plan(self, origin: str, dest: str, preference: str = None) -> List[Dict]:
        """Find optimal routes using Dijkstra's algorithm"""
        origin_node = self.find_node(origin)
        dest_node = self.find_node(dest)
        
        if not origin_node or not dest_node:
            return []
        
        if origin_node == dest_node:
            return []
        
        # Dijkstra's algorithm
        distances = {node: float('inf') for node in self.nodes}
        distances[origin_node] = 0
        previous = {node: None for node in self.nodes}
        visited = set()
        pq = [(0, origin_node)]
        
        while pq:
            current_dist, current_node = heapq.heappop(pq)
            
            if current_node in visited:
                continue
            visited.add(current_node)
            
            if current_node == dest_node:
                break
            
            for neighbor, info in self.graph.get(current_node, {}).items():
                if neighbor in visited:
                    continue
                
                # Calculate distance (number of stops)
                edge_weight = info["hops"]
                new_dist = current_dist + edge_weight
                
                if new_dist < distances[neighbor]:
                    distances[neighbor] = new_dist
                    previous[neighbor] = {
                        "from": current_node,
                        "route": info["route"],
                        "type": info["type"],
                        "details": info["details"]
                    }
                    heapq.heappush(pq, (new_dist, neighbor))
        
        # Reconstruct path
        if distances[dest_node] == float('inf'):
            return []
        
        path = []
        current = dest_node
        while current != origin_node:
            prev_info = previous[current]
            path.append({
                "from": prev_info["from"],
                "to": current,
                "route": prev_info["route"],
                "type": prev_info["type"],
                "details": prev_info["details"]
            })
            current = prev_info["from"]
        
        path.reverse()
        
        # Convert to itinerary format
        itinerary = self._convert_to_itinerary(path, origin_node, dest_node)
        
        # Apply preference
        if preference == "fewest_stops":
            itinerary.sort(key=lambda x: sum(len(leg["stops"]) for leg in x["legs"]))
        elif preference == "direct":
            itinerary.sort(key=lambda x: x["transfers"])
        
        return itinerary
    
    def _convert_to_itinerary(self, path: List[Dict], origin: str, dest: str) -> List[Dict]:
        """Convert path to itinerary format"""
        if not path:
            return []
        
        # Group consecutive stops by route
        legs = []
        current_route = None
        current_leg_stops = []
        
        for step in path:
            if step["route"] != current_route:
                # Save previous leg
                if current_leg_stops:
                    legs.append({
                        "type": current_route_type,
                        "route": current_route,
                        "stops": current_leg_stops,
                        "hops": len(current_leg_stops) - 1,
                        "details": step["details"],
                        "to": step["to"] if len(path) > path.index(step) + 1 else dest
                    })
                
                # Start new leg
                current_route = step["route"]
                current_route_type = step["type"]
                current_leg_stops = [step["from"]]
            
            current_leg_stops.append(step["to"])
        
        # Add last leg
        if current_leg_stops:
            legs.append({
                "type": current_route_type,
                "route": current_route,
                "stops": current_leg_stops,
                "hops": len(current_leg_stops) - 1,
                "details": path[-1]["details"] if path else "",
                "to": dest
            })
        
        # Calculate totals
        total_mins = sum(leg["hops"] * 3 for leg in legs)  # Rough estimate: 3 min per stop
        total_transfers = len(legs) - 1
        
        modes = list(set(leg["type"] for leg in legs))
        
        return [{
            "modes": modes,
            "legs": legs,
            "origin": origin,
            "destination": dest,
            "mins": total_mins,
            "transfers": total_transfers,
            "fare": 0  # No fare info
        }]
    
    def line_info(self, line_name: str) -> Optional[Dict]:
        """Get information about a specific transit line"""
        line_name_lower = line_name.lower()
        
        for route in self.routes:
            if line_name_lower in route["name"].lower() or line_name_lower in route["type"].lower():
                return route
        
        return None


def load_data(filepath: str) -> List[Dict]:
    """Load route data from JSON file"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: File {filepath} not found")
        return []
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in {filepath}")
        return []


def describe_itinerary(origin: str, dest: str, itinerary: Dict) -> str:
    """Describe an itinerary in plain text"""
    if not itinerary or "legs" not in itinerary:
        return "Walang makitang ruta."
    
    lines = []
    lines.append(f" mula {origin} papuntang {dest}:")
    
    for i, leg in enumerate(itinerary["legs"], 1):
        mode_icon = {"Train": "🚆", "Jeepney": "🚌", "UV Express": "🚐", "Walk": "🚶"}.get(leg["type"], "🚏")
        lines.append(f"\n{i}. {mode_icon} {leg['type']} - {leg['route']}")
        lines.append(f"   Hinto: {' → '.join(leg['stops'])}")
        lines.append(f"   Detalye: {leg['details']}")
        
        if i < len(itinerary["legs"]):
            next_leg = itinerary["legs"][i]
            lines.append(f"   🔄 Lipat sa: {next_leg['to']}")
    
    lines.append(f"\nKabuuang oras: ~{itinerary['mins']} minutos")
    lines.append(f"Kabuuang lipat: {itinerary['transfers']}")
    
    return "\n".join(lines)


def describe_plan(origin: str, dest: str, options: List[Dict]) -> str:
    """Describe multiple route options"""
    if not options:
        return "Walang natagpuang ruta."
    
    lines = []
    for i, opt in enumerate(options[:3], 1):  # Show top 3 options
        lines.append(f"\n【Opsyon {i}】")
        lines.append(describe_itinerary(origin, dest, opt))
    
    return "\n".join(lines)
