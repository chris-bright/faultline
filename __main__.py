import click
from runner.orchestrator import Orchestrator
from reports.reporter import Reporter


@click.group()
def cli():
    """faultline — fault injection agent for containerized services"""
    pass


@cli.command()
@click.option("--config", "-c", required=True, help="Path to target.yaml for the running container")
@click.option("--scenario", "-s", help="Path to a scenario YAML file")
@click.option("--domain", "-d", type=click.Choice(["infrastructure", "code", "cloud", "container", "security"]), help="Run all scenarios in a domain")
@click.option("--debug", is_flag=True, help="Output full sample data as JSON")
def run(config, scenario, domain, debug):
    """Attach to a running container and inject faults."""
    orchestrator = Orchestrator(config=config)

    if scenario:
        results = orchestrator.run_scenario(scenario)
    elif domain:
        results = orchestrator.run_domain(domain)
    else:
        raise click.UsageError("Provide --scenario or --domain")

    Reporter(debug=debug).render(results)


if __name__ == "__main__":
    cli()
