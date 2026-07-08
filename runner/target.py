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


def load_target(path: str) -> TargetConfig:
    raw = yaml.safe_load(Path(path).read_text())
    container = raw.get("container")
    if not container:
        raise ValueError(f"target.yaml must specify 'container': {path}")
    return TargetConfig(
        container=container,
        service=raw.get("service", container),
        health_probe=raw.get("health_probe"),
        health_path=raw.get("health_path"),
        health_port=raw.get("port", 8080),
        health_process=raw.get("process"),
    )
