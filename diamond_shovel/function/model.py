from typing import Any, Callable

from diamond_shovel.utils import json_util


class Vulnerability(json_util.JsonExportable):
    def __init__(self, name: str, description: str, severity: str, references: list[str]):
        self.name = name
        self.description = description
        self.severity = severity
        self.references = references

    def export(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "severity": self.severity,
            "references": self.references,
            "hash": hash(self),
            "type": "diamond_shovel.function.task.Vulnerability"
        }

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Vulnerability):
            return False
        return (self.name == other.name)

    def __hash__(self) -> int:
        return hash(self.name)


class Asset(json_util.JsonExportable):
    def __init__(self, owner: 'Company', host: str, port: int, layer4_protocol: int):
        self.owner = owner

        self.host = host
        self.port = port
        self.layer4_protocol = layer4_protocol

        self.identified_service = None
        self.signature = []

        self.suggested_techniques = []
        self.vulnerabilities = []

    def export(self):
        return {
            "host": self.host,
            "port": self.port,
            "layer4_protocol": self.layer4_protocol,
            "identified_service": self.identified_service,
            "signature": self.signature,
            "suggested_techniques": self.suggested_techniques,
            "vulnerabilities": [vuln.export() for vuln in self.vulnerabilities],
            "hash": hash(self),
            "type": "diamond_shovel.function.task.Asset"
        }

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Asset):
            return False
        return (self.host == other.host and
                self.port == other.port and
                self.layer4_protocol == other.layer4_protocol)

    def __hash__(self) -> int:
        return hash(self.host + str(self.port) + str(self.layer4_protocol))


class Company(json_util.JsonExportable):
    def __init__(self, company_name: str):
        self.company_name = company_name
        self._assigned_task = None

    def get_relation_to(self, target: Any, filt: Callable[[Any], bool] = lambda: True) -> float:
        return self._assigned_task.asset_graph.traverse(self, target, filt)

    def export(self):
        return {
            "company_name": self.company_name,
            "hash": hash(self),
            "type": "diamond_shovel.function.task.Company"
        }

    def __eq__(self, other):
        if not isinstance(other, Company):
            return False
        return (self.company_name == other.company_name)

    def __hash__(self):
        return hash(self.company_name)
