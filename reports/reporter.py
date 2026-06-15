import json
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()

SEVERITY_STYLE = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "dim",
}


class Reporter:
    def render(self, findings: dict):
        self._print_summary(findings)
        self._print_violations(findings)
        self._save_json(findings)

    def _print_summary(self, findings: dict):
        summary = findings["summary"]
        total = findings["total_scenarios"]
        n_violations = len(findings["violations"])
        n_passed = len(findings["passed_controls"])

        console.print()
        console.rule("[bold]Compliance Report")
        console.print(f"Frameworks: {', '.join(findings['frameworks'])}")
        console.print(f"Scenarios run: {total}")
        console.print(
            f"Controls: [green]{n_passed} passed[/green]  "
            f"[red]{n_violations} failed[/red]"
        )
        if any(summary.values()):
            console.print(
                f"Severity breakdown — "
                f"[bold red]critical: {summary['critical']}[/bold red]  "
                f"[red]high: {summary['high']}[/red]  "
                f"[yellow]medium: {summary['medium']}[/yellow]  "
                f"[dim]low: {summary['low']}[/dim]"
            )
        console.print()

    def _print_violations(self, findings: dict):
        if not findings["violations"]:
            console.print("[green]No compliance violations detected.[/green]")
            return

        table = Table(box=box.SIMPLE_HEAD, show_lines=True)
        table.add_column("Severity", style="bold", width=10)
        table.add_column("Control", width=20)
        table.add_column("Framework", width=12)
        table.add_column("Description", width=45)
        table.add_column("Scenario", width=25)

        for v in findings["violations"]:
            sev = v["severity"]
            table.add_row(
                f"[{SEVERITY_STYLE.get(sev, '')}]{sev.upper()}[/]",
                v["control"],
                v["framework"],
                v["description"],
                v["scenario"],
            )

        console.print(table)

    def _save_json(self, findings: dict):
        out_dir = Path(__file__).parent
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"faultline_report_{ts}.json"
        with open(out_path, "w") as f:
            json.dump(findings, f, indent=2)
        console.print(f"[dim]Report saved: {out_path}[/dim]")
