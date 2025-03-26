import queue
from typing import Callable, Any

from diamond_shovel.utils import json_util


class Graph(json_util.JsonExportable):
    def __init__(self):
        self.edges = []
        self._nodes = {}

    def add_edge(self, src, dist, weight: float):
        if weight < 0:
            weight = 0
        if weight > 1:
            weight = 1

        if src not in self._nodes:
            self._nodes[src] = {}
        if dist not in self._nodes:
            self._nodes[dist] = {}

        edge = {'src': hash(src), 'dist': hash(dist), 'weight': weight}
        self.edges.append(edge)

        if src not in self._nodes:
            self._nodes[src] = {}
        if dist not in self._nodes:
            self._nodes[dist] = {}

        self._nodes[src][dist] = weight
        self._nodes[dist][src] = weight

    def export(self):
        return {
            'edges': self.edges,
            'nodes': {hash(node): node for node in self._nodes.keys()},
        }

    def traverse(self, src, dist, filt: Callable[[Any], bool] = lambda x: True) -> float:
        if src not in self._nodes or dist not in self._nodes:
            raise ValueError(f"Node {src} or {dist} not found in the graph.")

        # We use queue for bfs.
        to_visit = queue.Queue()
        to_visit.put((src, 0))
        visited = set()

        while not to_visit.empty():
            node, weight = to_visit.get()
            if node == dist:
                return weight

            visited.add(node)
            [to_visit.put((neighbor, weight * edge_weight)) for neighbor, edge_weight in self._nodes[node].items() if filt(neighbor) and neighbor not in visited]

        raise ValueError("No path to target found in the graph.")

    def stored(self, obj: Any) -> Any:
        if obj not in self._nodes:
            self._nodes[obj] = {}
        return next(iter([k for k in self._nodes.keys() if k == obj]))

    def find_matching(self, src: Any, predicate: Callable[[Any], bool]) -> list[tuple[Any, float]]:
        if src not in self._nodes:
            raise ValueError(f"Node {src} not found in the graph.")

        # We use queue for bfs.
        to_visit = queue.Queue()
        to_visit.put((src, 1))
        visited = set()

        while not to_visit.empty():
            node, weight = to_visit.get()

            visited.add(node)
            [to_visit.put((neighbor, weight * edge_weight)) for neighbor, edge_weight in self._nodes[node].items() if neighbor not in visited]

        return sorted([(node, weight) for node, weight in visited if predicate(node)], lambda body, weight: weight, reverse=True)
