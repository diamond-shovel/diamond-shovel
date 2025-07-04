import abc
import uuid
from typing import Any, Type

_asset_type_registry: dict[str, Type['Asset']] = {}
_loot_type_registry: dict[str, Type['Loot']] = {}


def register_asset_type(asset_type: Type['Asset']):
    """
    Register a new asset type.
    :param asset_type: The class of the asset type to register.
    """
    if not issubclass(asset_type, Asset):
        raise TypeError("asset_type must be a subclass of Asset")
    _asset_type_registry[asset_type.__name__] = asset_type


def register_loot_type(loot_type: Type['Loot']):
    """
    Register a new loot type.
    :param loot_type: The class of the loot
    type to register.
    """
    if not issubclass(loot_type, Loot):
        raise TypeError("loot_type must be a subclass of Loot")
    _loot_type_registry[loot_type.__name__] = loot_type


def decode_asset(data: dict) -> 'Asset':
    """
    Decode a dictionary into an Asset instance.
    :param data: The dictionary containing asset data.
    :return: An instance of the corresponding Asset subclass.
    """
    asset_type_name = data.get('__type__')
    if asset_type_name not in _asset_type_registry:
        raise ValueError(f"Unknown asset type: {asset_type_name}")

    asset_class = _asset_type_registry[asset_type_name]
    return asset_class(data['metadata'])


def decode_loot(data: dict) -> 'Loot':
    """
    Decode a dictionary into a Loot instance.
    :param data: The dictionary containing loot data.
    :return: An instance of the corresponding Loot subclass.
    """
    loot_type_name = data.get('__type__')
    if loot_type_name not in _loot_type_registry:
        raise ValueError(f"Unknown loot type: {loot_type_name}")

    loot_class = _loot_type_registry[loot_type_name]
    return loot_class(uuid.UUID(data['discovered_asset']), data.get('metadata', {}))


class Asset(abc.ABC):
    id = uuid.uuid4()
    metadata: dict[str, Any]

    def __init__(self, metadata: dict[str, Any] | None = None):
        """
        Initialize the Asset with optional metadata.
        :param metadata: A dictionary containing asset metadata.
        """
        if metadata is None:
            metadata = {}
        self.metadata = metadata

    @abc.abstractmethod
    def __hash__(self):
        ...

    def jsonify(self):
        return {'__type__': type(self).__name__, 'metadata': self.jsonify_metadata()}

    @abc.abstractmethod
    def jsonify_metadata(self):
        """
        Return a dictionary representation of the asset's metadata.
        This method should be implemented by subclasses to provide
        specific metadata details.
        """
        ...


class Company(Asset):
    name: str

    def __init__(self, name_or_metadata: str | dict[str, Any], metadata: dict[str, Any] = None):
        if isinstance(name_or_metadata, dict):
            self.name = name_or_metadata.pop('name')
            super().__init__(name_or_metadata)

        self.name = name_or_metadata
        if metadata is None:
            metadata = {}
        super().__init__(metadata)

    def __hash__(self):
        return hash((type(self), self.name))

    def jsonify_metadata(self):
        return {'name': self.name, **self.metadata}


class Domain(Asset):
    domain: str

    def __init__(self, domain_or_metadata: str | dict[str, Any], metadata: dict[str, Any] = None):
        if isinstance(domain_or_metadata, dict):
            self.domain = domain_or_metadata.pop('domain')
            super().__init__(domain_or_metadata)

        self.domain = domain_or_metadata
        if metadata is None:
            metadata = {}
        super().__init__(metadata)

    def __hash__(self):
        return hash((type(self), self.domain))

    def jsonify_metadata(self):
        return {'domain': self.domain, **self.metadata}


class Host(Asset):
    host = None

    hostname: str

    def __init__(self, hostname_or_metadata: str | dict[str, Any], metadata: dict[str, Any] = None):
        if isinstance(hostname_or_metadata, dict):
            self.hostname = hostname_or_metadata.pop('hostname')
            super().__init__(hostname_or_metadata)

        self.hostname = hostname_or_metadata
        if metadata is None:
            metadata = {}
        super().__init__(metadata)

    def __hash__(self):
        return hash((type(self), self.hostname))

    def jsonify_metadata(self):
        return {'hostname': self.hostname, **self.metadata}


class Service(Asset):
    host: uuid.UUID
    port: int
    protocol: str
    service_name: str
    metadata: dict[str, Any]

    def __init__(self, metadata: dict[str, Any] | None = None):
        if metadata is None:
            super().__init__(metadata)
            return

        self.host = metadata.pop('host')
        self.port = metadata.pop('port')
        self.protocol = metadata.pop('protocol')
        self.service_name = metadata.pop('service_name')
        super().__init__(metadata)

    def __hash__(self):
        return hash((type(self), self.host, self.port, self.protocol, self.service_name))

    def jsonify_metadata(self):
        return {
                'host': self.host,
                'port': self.port,
                'protocol': self.protocol,
                'service_name': self.service_name,
                **self.metadata
        }


class Loot(abc.ABC):
    id = uuid.uuid4()
    discovered_asset_id: uuid.UUID
    metadata: dict[str, Any]

    def __init__(self, discovered_asset_id: uuid.UUID, metadata: dict[str, Any] | None = None):
        """
        Initialize the Loot with the ID of the discovered asset.
        :param discovered_asset_id: The UUID of the asset where this loot was discovered.
        """
        self.discovered_asset_id = discovered_asset_id

        if metadata is None:
            metadata = {}
        self.metadata = metadata

    @abc.abstractmethod
    def __hash__(self):
        ...

    def jsonify(self):
        return {
            '__type__': type(self).__name__,
            'discovered_asset': self.discovered_asset_id
        }

    @abc.abstractmethod
    def jsonify_metadata(self):
        """
        Return a dictionary representation of the loot's metadata.
        This method should be implemented by subclasses to provide
        specific metadata details.
        """
        ...


class Vulnerability(Loot):
    name: str
    description: str
    type: str
    severity: str

    def __init__(self, discovered_asset_id: uuid.UUID, metadata: dict[str, Any] | None = None):
        """
        Initialize the Vulnerability with the ID of the discovered asset and metadata.
        :param discovered_asset_id: The UUID of the asset where this vulnerability was discovered.
        :param metadata: A dictionary containing vulnerability metadata.
        """
        if metadata is None:
            metadata = {}

        self.name = metadata.pop('name', None)
        self.description = metadata.pop('description', None)
        self.type = metadata.pop('type', None)
        self.severity = metadata.pop('severity', None)

        super().__init__(discovered_asset_id, metadata)

    def __hash__(self):
        return hash((type(self), self.name, self.type, self.severity))

    def jsonify_metadata(self):
        return {
                'name': self.name,
                'description': self.description,
                'type': self.type,
                'severity': self.severity,
                **self.metadata
        }
