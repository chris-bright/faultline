import click
from runner.orchestrator import Orchestrator
from evaluator.compliance import ComplianceEvaluator
from reports.reporter import Reporter


@click.group()
def cli():
    """faultline — controlled fault injection + compliance evaluation"""
    pass


@cli.command()
@click.option("--scenario", "-s", help="Path to a scenario YAML file")
@click.option("--domain", "-d", type=click.Choice(["infrastructure", "code", "cloud", "container", "security"]), help="Run all scenarios in a domain")
@click.option("--target", "-t", default="simple_api", help="Target service to test against")
@click.option("--report", is_flag=True, help="Generate compliance report after run")
@click.option("--framework", "-f", multiple=True, default=["cis-docker", "soc2"], help="Compliance frameworks to evaluate against")
def run(scenario, domain, target, report, framework):
    """Run fault scenarios against a target and optionally evaluate compliance."""
    orchestrator = Orchestrator(target=target)

    if scenario:
        results = orchestrator.run_scenario(scenario)
    elif domain:
        results = orchestrator.run_domain(domain)
    else:
        raise click.UsageError("Provide --scenario or --domain")

    if report:
        evaluator = ComplianceEvaluator(frameworks=list(framework))
        findings = evaluator.evaluate(results)
        Reporter().render(findings)


@cli.command()
@click.option("--target", "-t", default="simple_api")
def scaffold(target):
    """Scaffold and verify the target environment without running faults."""
    orchestrator = Orchestrator(target=target)
    orchestrator.scaffold_only()


if __name__ == "__main__":
    cli()
