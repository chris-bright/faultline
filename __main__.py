import os
import click
from version import __version__
from config import load_config
from runner.orchestrator import Orchestrator
from reports.reporter import Reporter
from reports.datadog import DatadogSubmitter


@click.group()
@click.version_option(__version__, prog_name="faultline")
def cli():
    """faultline — fault injection agent for containerized services"""
    pass


@cli.command()
@click.option("--targets", "-t", default="targets.yaml", show_default=True,
              help="Path to targets.yaml")
@click.option("--service", "-s", multiple=True,
              help="Service name(s) to target (default: all services in targets.yaml)")
@click.option("--scenario", "-c", help="Path to a scenario YAML file")
@click.option("--domain", "-d", type=click.Choice(["infrastructure", "code", "cloud", "container", "security"]),
              help="Run all scenarios in a domain")
@click.option("--debug", is_flag=True, help="Output full sample data as JSON")
@click.option("--no-submit", is_flag=True, help="Skip Datadog submission")
@click.option("--submission-mode", type=click.Choice(["agent", "agentless"]), default=None,
              help="Override submission mode from faultline.yaml (agent=DogStatsD, agentless=direct HTTP)")
@click.option("--faultline-config", default="faultline.yaml", show_default=True,
              help="Path to faultline.yaml config file")
def run(targets, service, scenario, domain, debug, no_submit, submission_mode, faultline_config):
    """Attach to running containers and inject faults."""
    fl_config = load_config(faultline_config)

    mode = submission_mode or fl_config.datadog.submission_mode
    effective_debug = debug or fl_config.output.debug

    services = list(service) if service else None
    orchestrator = Orchestrator()

    if scenario:
        results = orchestrator.run_scenario(targets, scenario, services)
    elif domain:
        results = orchestrator.run_domain(targets, domain, services)
    else:
        raise click.UsageError("Provide --scenario or --domain")

    reporter = Reporter(debug=effective_debug, results_dir=fl_config.output.results_dir)
    reporter.render(results)

    if no_submit:
        return

    if mode == "agent":
        DatadogSubmitter(
            mode="agent",
            agent_host=fl_config.datadog.agent_host,
            agent_port=fl_config.datadog.agent_port,
        ).submit(results)
    elif mode == "agentless":
        if not os.environ.get("DD_API_KEY"):
            from rich.console import Console
            Console().print("[dim]DD_API_KEY not set — skipping Datadog submission[/dim]")
            return
        DatadogSubmitter(
            mode="agentless",
            site=fl_config.datadog.site,
        ).submit(results)


if __name__ == "__main__":
    cli()
