"""AgentAnvil CLI — quality gates and evaluations for LLM agents."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(
    name="agentanvil",
    help="Testing and evaluation platform for LLM agents.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def version() -> None:
    """Show the installed version."""
    from agentanvil import __version__

    console.print(f"agentanvil {__version__}")


@app.command()
def validate(
    contract: Path = typer.Argument(..., help="Path to contract YAML file."),
) -> None:
    """Validate a contract YAML file."""
    from agentanvil.core.contracts import AgentContract

    try:
        c = AgentContract.from_yaml(contract)
        console.print(f"[green]✓[/green] Contract [bold]{c.name}[/bold] v{c.version} is valid.")
        console.print(f"  {len(c.policies)} policies · {len(c.tasks)} tasks")
    except Exception as exc:
        console.print(f"[red]✗[/red] Invalid contract: {exc}")
        raise typer.Exit(1) from exc


@app.command()
def run(
    agent: Path = typer.Argument(..., help="Path to agent directory or file."),
    contract: Path = typer.Option(..., "--contract", "-c", help="Path to contract YAML."),
    threshold: float = typer.Option(0.85, "--threshold", "-t", help="Pass threshold (0-1)."),
    budget: float = typer.Option(10.0, "--budget", "-b", help="Max spend in USD."),
) -> None:
    """Run a full evaluation of an agent against a contract."""
    console.print(f"[bold]AgentAnvil[/bold] · evaluating [cyan]{agent}[/cyan]")
    console.print(f"Contract : {contract}")
    console.print(f"Threshold: {threshold}  Budget: ${budget:.2f}")
    console.print()
    console.print("[yellow]Full evaluation pipeline not yet implemented.[/yellow]")
    console.print("Use [bold]agentanvil validate[/bold] to check your contract.")


@app.command()
def proxy(
    log_dir: Path = typer.Option(Path("recordings"), "--log-dir", help="Where session logs go."),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address (no auth: keep it local)."),
    port: int = typer.Option(8090, "--port", "-p", help="Port to listen on."),
    timeout: float = typer.Option(600.0, "--timeout", help="Upstream timeout in seconds."),
) -> None:
    """Record and replay OpenAI-compatible LLM calls at the HTTP boundary."""
    from agentanvil.record_replay.proxy import ProxyServer

    if host not in ("127.0.0.1", "localhost", "::1"):
        console.print("[yellow]Warning:[/yellow] the proxy has no authentication.")
    server = ProxyServer((host, port), log_dir, timeout=timeout)
    shown = f"[{host}]" if ":" in host else host
    console.print(f"[bold]AgentAnvil proxy[/bold] on http://{shown}:{port} · logs in {log_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("Stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    app()
