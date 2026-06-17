import os
import click
from runner.orchestrator import Orchestrator
from reports.reporter import Reporter
from reports.datadog import DatadogSubmitter


@click.group()
def cli():
    """faultline — fault injection agent for containerized services"""
    pass


@cli.command()
@click.option("--config", "-c", required=True, help="Path to target.yaml for the running container")
@click.option("--scenario", "-s", help="Path to a scenario YAML file")
@click.option("--domain", "-d", type=click.Choice(["infrastructure", "code", "cloud", "container", "security"]), help="Run all scenarios in a domain")
@click.option("--debug", is_flag=True, help="Output full sample data as JSON")
@click.option("--no-submit", is_flag=True, help="Skip Datadog submission even if DD_API_KEY is set")
def run(config, scenario, domain, debug, no_submit):
    """Attach to a running container and inject faults."""
    orchestrator = Orchestrator(config=config)

    if scenario:
        results = orchestrator.run_scenario(scenario)
    elif domain:
        results = orchestrator.run_domain(domain)
    else:
        raise click.UsageError("Provide --scenario or --domain")

    reporter = Reporter(debug=debug)
    reporter.render(results)

    if not no_submit and os.environ.get("DD_API_KEY"):
        import json
        from datetime import datetime
        if isinstance(results, dict):
            results = [results]
        payload = {
            "run_at": datetime.utcnow().isoformat() + "Z",
            "scenarios": results,
        }
        DatadogSubmitter().submit(payload)
    elif not no_submit and not os.environ.get("DD_API_KEY"):
        from rich.console import Console
        Console().print("[dim]DD_API_KEY not set — skipping Datadog submission[/dim]")


if __name__ == "__main__":
    cli()
