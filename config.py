import os
import yaml
from pathlib import Path
from dataclasses import dataclass, field

DEFAULT_CONFIG_PATH = "faultline.yaml"


@dataclass
class DatadogConfig:
    submission_mode: str = "agentless"  # agent | agentless
    site: str = "datadoghq.com"
    agent_host: str = "localhost"
    agent_port: int = 8125


@dataclass
class OutputConfig:
    debug: bool = False
    results_dir: str = "/tmp/faultline"


@dataclass
class FaultlineConfig:
    datadog: DatadogConfig = field(default_factory=DatadogConfig)
    output: OutputConfig = field(default_factory=OutputConfig)


def load_config(path: str = DEFAULT_CONFIG_PATH) -> FaultlineConfig:
    config = FaultlineConfig()
    config.datadog.site = os.environ.get("DD_SITE", "datadoghq.com")

    config_path = Path(path)
    if not config_path.exists():
        return config

    raw = yaml.safe_load(config_path.read_text()) or {}

    dd = raw.get("datadog", {})
    config.datadog = DatadogConfig(
        submission_mode=dd.get("submission_mode", "agentless"),
        site=dd.get("site", os.environ.get("DD_SITE", "datadoghq.com")),
        agent_host=dd.get("agent_host", "localhost"),
        agent_port=int(dd.get("agent_port", 8125)),
    )

    out = raw.get("output", {})
    config.output = OutputConfig(
        debug=bool(out.get("debug", False)),
        results_dir=out.get("results_dir", "/tmp/faultline"),
    )

    return config
