import dataclasses
import enum


@dataclasses.dataclass
class AssetGraph:
    nodes: list['Asset']

@dataclasses.dataclass
class Asset:
    owner: AssetGraph

@dataclasses.dataclass
class Domain(Asset):
    name: str
    type: str
    value: str

@dataclasses.dataclass
class Host(Asset):
    address: str

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
