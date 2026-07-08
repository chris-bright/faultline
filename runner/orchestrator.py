import time
import uuid
from pathlib import Path
from rich.console import Console
from runner.sandbox import Sandbox
from runner.fault import FaultInjector, FaultNotApplied
from runner.telemetry import TelemetryCollector
from runner.result import ScenarioResult
from runner.target import TargetConfig, load_targets, load_targets_by_name
from scenarios.loader import load_scenario, SingleFaultScenario, StepBasedScenario

console = Console()


class Orchestrator:
    def run_scenario(self, targets_path: str, scenario_path: str,
                     services: list[str] = None) -> list[ScenarioResult]:
        run_id = str(uuid.uuid4())
        console.print(f"[dim]run_id: {run_id}[/dim]")
        scenario = load_scenario(scenario_path)

        if isinstance(scenario, StepBasedScenario):
            all_targets = load_targets_by_name(targets_path)
            return self._execute_step_scenario(scenario, run_id, all_targets)

        targets = load_targets(targets_path, services)
        return [self._execute(target, scenario, run_id) for target in targets]

    def run_domain(self, targets_path: str, domain: str,
                   services: list[str] = None) -> list[ScenarioResult]:
        run_id = str(uuid.uuid4())
        console.print(f"[dim]run_id: {run_id}[/dim]")
        domain_path = Path(__file__).parent.parent / "scenarios" / domain
        results = []
        for scenario_file in sorted(domain_path.glob("*.yaml")):
            console.rule(f"[bold]{scenario_file.stem}")
            scenario = load_scenario(str(scenario_file))

            if isinstance(scenario, StepBasedScenario):
                all_targets = load_targets_by_name(targets_path)
                results.extend(self._execute_step_scenario(scenario, run_id, all_targets))
            else:
                targets = load_targets(targets_path, services)
                for target in targets:
                    results.append(self._execute(target, scenario, run_id))

        return results

    def _execute_step_scenario(self, scenario: StepBasedScenario, run_id: str,
                                all_targets: dict[str, TargetConfig]) -> list[ScenarioResult]:
        console.print(f"\n[bold cyan]Step scenario:[/bold cyan] {scenario.name}  "
                      f"[dim]targets: {', '.join(scenario.targets)}[/dim]")
        console.print(f"[dim]{scenario.description}[/dim]\n")

        missing = [t for t in scenario.targets if t not in all_targets]
        if missing:
            raise ValueError(f"Targets not found in targets.yaml: {', '.join(missing)}")

        targets = [all_targets[name] for name in scenario.targets]

        sandboxes = {t.container: Sandbox(t.container) for t in targets}
        for sb in sandboxes.values():
            sb.attach()

        collectors = {
            t.container: TelemetryCollector(
                scenario.name,
                sandboxes[t.container].runtime,
                t.container,
                health_probe=t.health_probe,
                health_path=t.health_path,
                health_port=t.health_port,
                health_process=t.health_process,
            )
            for t in targets
        }

        injectors = {t.container: FaultInjector(sandboxes[t.container]) for t in targets}

        console.print("[dim]Pre-flight: checking all targets...[/dim]")
        for t in targets:
            if not collectors[t.container].probe_once():
                raise RuntimeError(
                    f"Pre-flight failed: '{t.container}' is not healthy before fault injection."
                )
        console.print("[dim]Pre-flight: OK[/dim]")

        step_summary = _build_step_summary(scenario.steps)
        started_at = time.time()

        for collector in collectors.values():
            collector.start()

        active_faults: dict[str, dict] = {}
        skipped_targets: set[str] = set()

        try:
            for step in scenario.steps:
                if step.action == "baseline":
                    console.print(f"[yellow]Baseline ({step.seconds}s)...[/yellow]")
                    time.sleep(step.seconds)

                elif step.action == "inject":
                    fault_dict = {"type": step.fault.type, **step.fault.params}
                    console.print(f"[red]Injecting fault:[/red] {step.fault.type} → {step.target}")
                    try:
                        injectors[step.target].inject(fault_dict)
                        collectors[step.target].mark_fault()
                        active_faults[step.target] = fault_dict
                    except FaultNotApplied as e:
                        console.print(f"[bold red]SKIP ({step.target}):[/bold red] {e}")
                        skipped_targets.add(step.target)

                elif step.action == "wait":
                    console.print(f"[yellow]Waiting {step.seconds}s...[/yellow]")
                    time.sleep(step.seconds)

                elif step.action == "recover":
                    if step.target in active_faults:
                        injectors[step.target].recover(active_faults.pop(step.target))
                        console.print(f"[yellow]Recovering {step.target}...[/yellow]")

        finally:
            for collector in collectors.values():
                collector.stop()

        fault_types = [s.fault.type for s in scenario.steps if s.action == "inject"]
        fault_type_str = ",".join(fault_types) if fault_types else "unknown"

        results = []
        for t in targets:
            metrics = collectors[t.container].collect()
            results.append(ScenarioResult(
                scenario=scenario.name,
                domain=scenario.domain,
                fault_type=fault_type_str,
                target=t.container,
                service=t.service,
                run_id=run_id,
                skipped=t.container in skipped_targets,
                metrics=metrics,
                compliance_tags=scenario.compliance_tags,
                started_at=started_at,
                step_summary=step_summary,
            ))

        return results

    def _execute(self, target: TargetConfig, scenario: SingleFaultScenario,
                 run_id: str) -> ScenarioResult:
        console.print(f"\n[bold cyan]Scenario:[/bold cyan] {scenario.name}  "
                      f"[dim]→ {target.service}[/dim]")
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

        step_summary = [
            f"baseline {scenario.baseline_seconds}s",
            f"inject {scenario.fault.type}",
            f"observe {scenario.observation_seconds}s",
            "recover",
            f"wait {scenario.recovery_seconds}s",
        ]
        started_at = time.time()

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
                    run_id=run_id,
                    skipped=True,
                    compliance_tags=scenario.compliance_tags,
                    started_at=started_at,
                    step_summary=step_summary,
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
                run_id=run_id,
                metrics=metrics,
                compliance_tags=scenario.compliance_tags,
                started_at=started_at,
                step_summary=step_summary,
            )

        finally:
            telemetry.stop()

        return result


def _build_step_summary(steps) -> list[str]:
    lines = []
    for step in steps:
        if step.action == "baseline":
            lines.append(f"baseline {step.seconds}s")
        elif step.action == "inject":
            lines.append(f"inject {step.fault.type} → {step.target}")
        elif step.action == "wait":
            lines.append(f"wait {step.seconds}s")
        elif step.action == "recover":
            lines.append(f"recover {step.target}")
    return lines
