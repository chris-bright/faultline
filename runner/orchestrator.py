import time
import yaml
from pathlib import Path
from rich.console import Console
from runner.sandbox import Sandbox
from runner.fault import FaultInjector, FaultNotApplied
from runner.telemetry import TelemetryCollector
from runner.result import ScenarioResult
from scenarios.loader import load_scenario, SingleFaultScenario

console = Console()


class Orchestrator:
    def __init__(self, config: str):
        config_path = Path(config)
        if not config_path.exists():
            raise FileNotFoundError(f"Target config not found: {config_path}")
        self.target_config = yaml.safe_load(config_path.read_text())
        self.container_name = self.target_config.get("container")
        if not self.container_name:
            raise ValueError(f"target.yaml must specify 'container' — the name of the running container to attach to")
        self.service = self.target_config.get("service", self.container_name)
        self.health_probe = self.target_config.get("health_probe")
        self.health_path = self.target_config.get("health_path")
        self.health_port = self.target_config.get("port", 8080)
        self.health_process = self.target_config.get("process")

    def run_scenario(self, scenario_path: str) -> list[ScenarioResult]:
        return [self._execute(load_scenario(scenario_path))]

    def run_domain(self, domain: str) -> list[ScenarioResult]:
        domain_path = Path(__file__).parent.parent / "scenarios" / domain
        results = []
        for scenario_file in sorted(domain_path.glob("*.yaml")):
            console.rule(f"[bold]{scenario_file.stem}")
            results.append(self._execute(load_scenario(str(scenario_file))))
        return results

    def _execute(self, scenario: SingleFaultScenario) -> ScenarioResult:
        console.print(f"\n[bold cyan]Scenario:[/bold cyan] {scenario.name}")
        console.print(f"[dim]{scenario.description}[/dim]\n")

        sandbox = Sandbox(self.container_name)
        sandbox.attach()

        telemetry = TelemetryCollector(
            scenario.name,
            sandbox.runtime,
            sandbox.container_name,
            health_probe=self.health_probe,
            health_path=self.health_path,
            health_port=self.health_port,
            health_process=self.health_process,
        )

        console.print("[dim]Pre-flight: checking target health...[/dim]")
        if not telemetry.probe_once():
            raise RuntimeError(
                f"Pre-flight failed: container '{self.container_name}' is not healthy before fault injection. "
                "Fix the target before running scenarios."
            )
        console.print("[dim]Pre-flight: OK[/dim]")

        try:
            telemetry.start()

            console.print("[yellow]Collecting baseline...[/yellow]")
            time.sleep(scenario.baseline_seconds)

            injector = FaultInjector(sandbox)
            fault_dict = {"type": scenario.fault.type, **scenario.fault.params}
            console.print(f"[red]Injecting fault:[/red] {scenario.fault.type}")
            try:
                injector.inject(fault_dict)
            except FaultNotApplied as e:
                telemetry.stop()
                console.print(f"[bold red]SKIP:[/bold red] {e}")
                return ScenarioResult(
                    scenario=scenario.name,
                    domain=scenario.domain,
                    fault_type=scenario.fault.type,
                    target=self.container_name,
                    service=self.service,
                    skipped=True,
                    compliance_tags=scenario.compliance_tags,
                )
            telemetry.mark_fault()

            console.print(f"[yellow]Observing for {scenario.observation_seconds}s...[/yellow]")
            time.sleep(scenario.observation_seconds)

            injector.recover(fault_dict)
            console.print("[yellow]Checking recovery...[/yellow]")
            time.sleep(scenario.recovery_seconds)

            metrics = telemetry.collect()
            result = ScenarioResult(
                scenario=scenario.name,
                domain=scenario.domain,
                fault_type=scenario.fault.type,
                target=self.container_name,
                service=self.service,
                metrics=metrics,
                compliance_tags=scenario.compliance_tags,
            )

        finally:
            telemetry.stop()

        return result
