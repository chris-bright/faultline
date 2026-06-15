import click
from runner.orchestrator import Orchestrator
from reports.reporter import Reporter


@click.group()
def cli():
    """faultline — controlled fault injection + compliance evaluation"""
    pass


@cli.command()
@click.option("--scenario", "-s", help="Path to a scenario YAML file")
@click.option("--domain", "-d", type=click.Choice(["infrastructure", "code", "cloud", "container", "security"]), help="Run all scenarios in a domain")
@click.option("--target", "-t", default="simple_api", help="Target service to test against")
@click.option("--debug", is_flag=True, help="Output full sample data as JSON")
def run(scenario, domain, target, debug):
    """Run fault scenarios against a target and output results."""
    orchestrator = Orchestrator(target=target)

    if scenario:
        results = orchestrator.run_scenario(scenario)
    elif domain:
        results = orchestrator.run_domain(domain)
    else:
        raise click.UsageError("Provide --scenario or --domain")

    Reporter(debug=debug).render(results)


@cli.command()
@click.option("--target", "-t", default="simple_api")
def scaffold(target):
    """Scaffold and verify the target environment without running faults."""
    orchestrator = Orchestrator(target=target)
    orchestrator.scaffold_only()


if __name__ == "__main__":
    cli()
