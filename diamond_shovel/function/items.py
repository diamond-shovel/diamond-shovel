import abc
from typing import Any


class ResultGraph:
    _nodes = []
    _edges = {}

    def set_relativity(self, node_1: 'Asset', node_2: 'Asset', relativity: float):
        if node_1 not in self._nodes:
            raise ValueError(f'Node {node_1} not in the node graph. Please add it first.')
        if node_2 not in self._nodes:
            raise ValueError(f'Node {node_2} not in the node graph. Please add it first.')

        if (node_2, node_1) in self._edges:
            self._edges[(node_2, node_1)] = relativity
            return

        self._edges[(node_1, node_2)] = relativity

    def add_node(self, node: 'Asset'):
        self._nodes.append(node)

    @property
    def nodes(self) -> list['Asset']:
        return self._nodes

    def replace_node(self, old: 'Asset', new: 'Asset'):
        if old not in self._nodes:
            raise ValueError(f'Node {old} not in the node graph. Please add it first.')
        if new in self._nodes:
            raise ValueError(f'Node {new} already exists in the node graph.')

        index = self._nodes.index(old)
        self._nodes[index] = new

        new_edges = {}
        for (node1, node2), rel in self._edges.items():
            if node1 == old:
                new_edges[(new, node2)] = rel
            elif node2 == old:
                new_edges[(node1, new)] = rel
            else:
                new_edges[(node1, node2)] = rel
        self._edges = new_edges

    def get_relationship(self, node_1: 'Asset', node_2: 'Asset') -> float:
        if node_1 not in self._nodes:
            raise ValueError(f'Node {node_1} not in the node graph. Please add it first.')
        if node_2 not in self._nodes:
            raise ValueError(f'Node {node_2} not in the node graph. Please add it first.')

        # do a simple dijkstra algorithm to find max relationship
        dist = {}
        for node in self._nodes:
            dist[node] = float('-inf')
        dist[node_1] = 1
        visited = set()
        queue = [node_1]
        while queue:
            current_node = queue.pop(0)
            if current_node in visited:
                continue
            visited.add(current_node)

            for neighbor, rel in self.get_connections(current_node).items():
                if neighbor not in visited:
                    new_dist = dist[current_node] * rel
                    if new_dist > dist[neighbor]:
                        dist[neighbor] = new_dist
                        queue.append(neighbor)

        return dist[node_2] if dist[node_2] != float('-inf') else 0.0

    def get_connections(self, node: 'Asset') -> dict['Asset', float]:
        return {
            **{node1: rel for (node1, node2), rel in self._edges.items() if node2 == node},
            **{node2: rel for (node1, node2), rel in self._edges.items() if node1 == node}
        }


class Asset(abc.ABC):
    host: 'Host'
    @abc.abstractmethod
    def __hash__(self):
        ...
    @abc.abstractmethod
    def jsonify(self):
        ...


class Host(Asset):
    host = None

    hostname: str

    def __hash__(self):
        return hash((type(self), self.hostname))

    def jsonify(self):
        return {'type': 'host', 'metadata': {'hostname': self.hostname}}


class Service(Asset):
    port: int
    protocol: str
    service_name: str
    version_str: str
    metadata: dict[str, Any]

    def __hash__(self):
        return hash((type(self), self.host, self.port, self.protocol, self.service_name, self.version_str))

    def jsonify(self):
        return {
            'type': 'service',
            'metadata': {
                'port': self.port,
                'protocol': self.protocol,
                'service_name': self.service_name,
                'version_str': self.version_str,
                **self.metadata
            }
        }


class Vulnerability:
    name: str
    description: str
    type: str
    severity: str
    metadata: dict[str, Any]

    def __hash__(self):
        return hash((type(self), self.name, self.type, self.severity))

    def jsonify(self):
        return {
            'type': 'vulnerability',
            'metadata': {
                'name': self.name,
                'description': self.description,
                'type': self.type,
                'severity': self.severity,
                **self.metadata
            }
        }
