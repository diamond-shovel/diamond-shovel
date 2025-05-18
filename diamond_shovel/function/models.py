import dataclasses
import enum

from diamond_shovel.utils.func import json_util


@dataclasses.dataclass
class AssetGraph:
    nodes: list['Asset']

json_util.put_encoder(AssetGraph, lambda graph: {
    '__type__': 'AssetGraph',
    'nodes': graph.nodes,
})

@dataclasses.dataclass
class Asset:
    owner: AssetGraph

@dataclasses.dataclass
class Domain(Asset):
    name: str
    type: str
    value: str

json_util.put_encoder(Domain, lambda domain: {
    '__type__': 'Domain',
    'name': domain.name,
    'type': domain.type,
    'value': domain.value,
})

@dataclasses.dataclass
class Host(Asset):
    address: str

json_util.put_encoder(Host, lambda host: {
    '__type__': 'Host',
    'address': host.address,
})

class ServiceProtocol(enum.Enum):
    TCP = 'tcp',
    UDP = 'udp'

@dataclasses.dataclass
class Service(Asset):
    name: str
    port: int
    protocol: ServiceProtocol
    type: str
    data: dict

json_util.put_encoder(Service, lambda service: {
    '__type__': 'Service',
    'name': service.name,
    'port': service.port,
    'protocol': service.protocol.value,
    'type': service.type,
    'data': service.data,
})

class VulnerabilitySeverity(enum.Enum):
    LOW = 'low',
    MEDIUM = 'medium',
    HIGH = 'high',
    INFO = 'info',
    CRITICAL = 'critical'

    @classmethod
    def reverse_map(cls, value):
        return {
            'low': VulnerabilitySeverity.LOW,
            'medium': VulnerabilitySeverity.MEDIUM,
            'high': VulnerabilitySeverity.HIGH,
            'critical': VulnerabilitySeverity.CRITICAL,
            'info': VulnerabilitySeverity.INFO,
        }[value]

@dataclasses.dataclass
class Vulnerability:
    # structure from nuclei templates, go see their document or some example
    # other plugin should also fit their own discovery into this structure
    name: str
    description: str
    severity: VulnerabilitySeverity
    impact: str
    remediation: str
    reference: list[str]
    classification: dict
    metadata: dict
    tags: list[str]

    discovered_location: Service

json_util.put_encoder(Vulnerability, lambda vulnerability: {
    '__type__': 'Vulnerability',
    'name': vulnerability.name,
    'description': vulnerability.description,
    'severity': vulnerability.severity.value,
    'impact': vulnerability.impact,
    'remediation': vulnerability.remediation,
    'reference': vulnerability.reference,
    'classification': vulnerability.classification,
    'metadata': vulnerability.metadata,
    'tags': vulnerability.tags,
})
