import functools
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from mailchef_cli.actions import run_action
from mailchef_cli.client import ClientError, MailChefClient
from mailchef_cli.config import load_config, save_config

app = typer.Typer(help="MailChef — your personal email assistant.", no_args_is_help=True)
console = Console()

ACTION_HELP = "Explicit message id(s). Omit to target emails via --search instead."


def _client() -> MailChefClient:
    try:
        return MailChefClient(load_config())
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


def _guard(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            fn(*args, **kwargs)
        except ClientError as e:
            console.print(f"[red]Error ({e.status_code}):[/red] {e}")
            raise typer.Exit(1)

    return wrapped


@app.command()
def configure(
    backend_url: str = typer.Option(..., prompt="Backend URL (e.g. https://mailchef-backend.fly.dev)"),
    token: str = typer.Option(..., prompt="API token (MAILCHEF_API_TOKEN from the backend .env)", hide_input=True),
) -> None:
    """Save the backend URL and API token to ~/.mailchef/config.json."""
    save_config(backend_url, token)
    console.print('[green]Saved.[/green] Try `mailchef digest` or `mailchef ask "..."` next.')


@app.command()
@_guard
def ask(question: str) -> None:
    """Ask a natural-language question about your inbox."""
    client = _client()
    with console.status("Thinking..."):
        result = client.post("/query", {"question": question})
    _print_answer(result)


@app.command()
@_guard
def chat() -> None:
    """Interactive chat. Plain text asks a question; /commands run actions."""
    client = _client()
    console.print(
        "[bold]MailChef[/bold] — ask about your inbox in plain text, or use "
        "/digest, /search <q>, /sync, /archive <q>, /trash <q>, /mark-read <q>, "
        "/star <q>, /exit.\n"
    )
    while True:
        try:
            line = console.input("[bold cyan]> [/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in ("/exit", "/quit"):
            break
        try:
            _handle_chat_line(client, line)
        except ClientError as e:
            console.print(f"[red]Error ({e.status_code}):[/red] {e}")


def _handle_chat_line(client: MailChefClient, line: str) -> None:
    if not line.startswith("/"):
        with console.status("Thinking..."):
            result = client.post("/query", {"question": line})
        _print_answer(result)
        return

    parts = line.split(maxsplit=1)
    cmd, rest = parts[0], parts[1] if len(parts) > 1 else ""

    if cmd == "/digest":
        _print_digest(client.get("/digest/latest"))
    elif cmd == "/sync":
        console.print(client.post("/sync/run"))
    elif cmd == "/search":
        _print_search(client.get("/search", {"q": rest, "limit": 20}))
    elif cmd in ("/archive", "/trash", "/mark-read", "/mark-unread", "/star", "/unstar"):
        action = cmd[1:].replace("-", "_")
        run_action(
            client, console, action, ids=None, search=rest,
            always_confirm=(action in ("archive", "trash")),
        )
    else:
        console.print(
            "[yellow]Unknown command. Try /digest, /search <q>, /archive <q>, "
            "/trash <q>, /mark-read <q>, /star <q>, /sync, /exit[/yellow]"
        )


@app.command()
@_guard
def digest(now: bool = typer.Option(False, "--now", help="Regenerate instead of showing the last one.")) -> None:
    """Show the latest morning digest, or generate a fresh one with --now."""
    client = _client()
    if now:
        with console.status("Syncing, classifying, and generating your digest..."):
            result = client.post("/digest/run")
        _print_digest(result["digest"])
    else:
        _print_digest(client.get("/digest/latest"))


@app.command()
@_guard
def search(
    query: str,
    category: Optional[str] = typer.Option(None),
    sender: Optional[str] = typer.Option(None),
    after: Optional[str] = typer.Option(None),
    before: Optional[str] = typer.Option(None),
    unread: bool = typer.Option(False, "--unread"),
    limit: int = typer.Option(20),
) -> None:
    """Hybrid (semantic + keyword) search over your inbox."""
    client = _client()
    results = client.get(
        "/search",
        {
            "q": query, "category": category, "sender": sender,
            "after": after, "before": before, "unread_only": unread, "limit": limit,
        },
    )
    _print_search(results)


@app.command()
@_guard
def sync() -> None:
    """Pull new mail from Gmail into MailChef's local index."""
    client = _client()
    with console.status("Syncing..."):
        console.print(client.post("/sync/run"))


@app.command()
@_guard
def classify() -> None:
    """Classify any unclassified mail into your configured categories."""
    client = _client()
    with console.status("Classifying..."):
        console.print(client.post("/classify/run"))


@app.command()
@_guard
def index() -> None:
    """Embed newly synced mail into the vector store."""
    client = _client()
    with console.status("Indexing..."):
        console.print(client.post("/index/run"))


@app.command()
@_guard
def labels() -> None:
    """List your Gmail labels (for use with label-add/label-remove)."""
    client = _client()
    rows = client.get("/labels")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("ID")
    for label in rows:
        table.add_row(label["name"], label["id"])
    console.print(table)


def _action_command(action: str, always_confirm: bool):
    @_guard
    def command(
        ids: Optional[list[str]] = typer.Argument(None, help=ACTION_HELP),
        search: Optional[str] = typer.Option(None, "--search", help="Resolve targets via search instead of ids."),
        category: Optional[str] = typer.Option(None),
        sender: Optional[str] = typer.Option(None),
        after: Optional[str] = typer.Option(None),
        before: Optional[str] = typer.Option(None),
        unread: bool = typer.Option(False, "--unread"),
        limit: int = typer.Option(100),
    ) -> None:
        client = _client()
        run_action(
            client, console, action, ids, search, category, sender, after, before,
            unread, limit, label=None, always_confirm=always_confirm,
        )

    return command


def _label_action_command(action: str):
    @_guard
    def command(
        label: str = typer.Option(..., "--label", help="Gmail label name (see `mailchef labels`)."),
        ids: Optional[list[str]] = typer.Argument(None, help=ACTION_HELP),
        search: Optional[str] = typer.Option(None, "--search"),
        category: Optional[str] = typer.Option(None),
        sender: Optional[str] = typer.Option(None),
        after: Optional[str] = typer.Option(None),
        before: Optional[str] = typer.Option(None),
        unread: bool = typer.Option(False, "--unread"),
        limit: int = typer.Option(100),
    ) -> None:
        client = _client()
        run_action(
            client, console, action, ids, search, category, sender, after, before,
            unread, limit, label=label, always_confirm=False,
        )

    return command


app.command(name="mark-read", help="Mark email(s) as read. Single id runs immediately; bulk/search asks first.")(
    _action_command("mark_read", always_confirm=False)
)
app.command(name="mark-unread", help="Mark email(s) as unread. Single id runs immediately; bulk/search asks first.")(
    _action_command("mark_unread", always_confirm=False)
)
app.command(name="star", help="Star email(s). Single id runs immediately; bulk/search asks first.")(
    _action_command("star", always_confirm=False)
)
app.command(name="unstar", help="Unstar email(s). Single id runs immediately; bulk/search asks first.")(
    _action_command("unstar", always_confirm=False)
)
app.command(name="archive", help="Requires confirmation — always shows affected emails first.")(
    _action_command("archive", always_confirm=True)
)
app.command(name="trash", help="Requires confirmation — always shows affected emails first.")(
    _action_command("trash", always_confirm=True)
)
app.command(name="label-add", help="Add a label. Single id runs immediately; bulk/search asks first.")(
    _label_action_command("add_label")
)
app.command(name="label-remove", help="Remove a label. Single id runs immediately; bulk/search asks first.")(
    _label_action_command("remove_label")
)


def _print_answer(result: dict) -> None:
    console.print(f"\n{result['answer']}\n")
    if result.get("sources"):
        table = Table(title="Sources", show_header=True, header_style="bold")
        table.add_column("From")
        table.add_column("Subject")
        table.add_column("Date")
        for s in result["sources"]:
            table.add_row(s["from"], s["subject"], (s.get("date") or "")[:10])
        console.print(table)


def _print_search(results: list[dict]) -> None:
    if not results:
        console.print("[yellow]No matching emails.[/yellow]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("From")
    table.add_column("Subject")
    table.add_column("Date")
    table.add_column("Category")
    table.add_column("Unread")
    for m in results:
        table.add_row(
            m["id"], m["from"], m["subject"], (m.get("date") or "")[:10],
            m.get("category") or "", "yes" if m.get("unread") else "",
        )
    console.print(table)


def _print_digest(d: dict) -> None:
    console.print(Markdown(d["content_markdown"]))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
