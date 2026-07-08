from dataclasses import dataclass
from pathlib import Path
import yaml


@dataclass
class TargetConfig:
    container: str
    service: str
    health_probe: str = None
    health_path: str = None
    health_port: int = 8080
    health_process: str = None
    probes: dict = None


def load_target(targets_path: str, service: str) -> TargetConfig:
    raw = yaml.safe_load(Path(targets_path).read_text())
    services = raw.get("services", {})
    if service not in services:
        available = ", ".join(services.keys())
        raise ValueError(f"Service '{service}' not found in {targets_path}. Available: {available}")
    return _parse(service, services[service])


def load_targets_by_name(targets_path: str) -> dict[str, TargetConfig]:
    raw = yaml.safe_load(Path(targets_path).read_text())
    all_services = raw.get("services", {})
    return {name: _parse(name, all_services[name]) for name in all_services}


def load_targets(targets_path: str, services: list[str] = None) -> list[TargetConfig]:
    raw = yaml.safe_load(Path(targets_path).read_text())
    all_services = raw.get("services", {})
    if not all_services:
        raise ValueError(f"No services defined in {targets_path}")

    selected = services if services else list(all_services.keys())
    missing = [s for s in selected if s not in all_services]
    if missing:
        available = ", ".join(all_services.keys())
        raise ValueError(f"Services not found in {targets_path}: {', '.join(missing)}. Available: {available}")

    return [_parse(name, all_services[name]) for name in selected]


def _parse(name: str, raw: dict) -> TargetConfig:
    container = raw.get("container", name)
    return TargetConfig(
        container=container,
        service=raw.get("service", container),
        health_probe=raw.get("health_probe"),
        health_path=raw.get("health_path"),
        health_port=raw.get("port", 8080),
        health_process=raw.get("process"),
        probes=raw.get("probes") or {},
    )
