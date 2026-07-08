import time
from pathlib import Path
from rich.console import Console
from runner.sandbox import Sandbox
from runner.fault import FaultInjector, FaultNotApplied
from runner.telemetry import TelemetryCollector
from runner.result import ScenarioResult
from runner.target import TargetConfig, load_target
from scenarios.loader import load_scenario, SingleFaultScenario

console = Console()


class Orchestrator:
    def run_scenario(self, target_path: str, scenario_path: str) -> list[ScenarioResult]:
        target = load_target(target_path)
        return [self._execute(target, load_scenario(scenario_path))]

    def run_domain(self, target_path: str, domain: str) -> list[ScenarioResult]:
        target = load_target(target_path)
        domain_path = Path(__file__).parent.parent / "scenarios" / domain
        results = []
        for scenario_file in sorted(domain_path.glob("*.yaml")):
            console.rule(f"[bold]{scenario_file.stem}")
            results.append(self._execute(target, load_scenario(str(scenario_file))))
        return results

    def _execute(self, target: TargetConfig, scenario: SingleFaultScenario) -> ScenarioResult:
        console.print(f"\n[bold cyan]Scenario:[/bold cyan] {scenario.name}")
        console.print(f"[dim]{scenario.description}[/dim]\n")

        sandbox = Sandbox(target.container)
        sandbox.attach()

        telemetry = TelemetryCollector(
            scenario.name,
            sandbox.runtime,
            sandbox.container_name,
            health_probe=target.health_probe,
            health_path=target.health_path,
            health_port=target.health_port,
            health_process=target.health_process,
        )

        console.print("[dim]Pre-flight: checking target health...[/dim]")
        if not telemetry.probe_once():
            raise RuntimeError(
                f"Pre-flight failed: container '{target.container}' is not healthy before fault injection. "
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
                    target=target.container,
                    service=target.service,
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
                target=target.container,
                service=target.service,
                metrics=metrics,
                compliance_tags=scenario.compliance_tags,
            )

        finally:
            telemetry.stop()

        return result
