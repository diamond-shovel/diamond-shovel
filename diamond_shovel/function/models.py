import enum
from datetime import datetime


class AssetGraph:
    nodes: list['Asset']

class Asset:
    owner: AssetGraph

class Domain(Asset):
    name: str
    type: str
    value: str

class Host(Asset):
    address: str

class ServiceProtocol(enum.Enum):
    TCP = 'tcp',
    UDP = 'udp'

class Service(Asset):
    name: str
    port: int
    protocol: ServiceProtocol

class WebService(Service):
    endpoint: str
    title: str
    scheme: str
    content_type: str
    method: str
    time: datetime
    reserve_dns_a_record: str
    discovered_technique: str
    word_count: int
    line_count: int
    status_code: int
    content_length: int
    failed: str
    final_url_dest: str
    chained_status_code: str
    reserve_dns_cname_record: str
    jarm_hash: str
    favicon_hash: str
    favicon_url: str
    favicon_path: str
    location: str
    reserve_dns_aaaa_record: str
