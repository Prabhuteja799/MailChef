from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from mailchef_cli.client import ClientError, MailChefClient


def run_action(
    client: MailChefClient,
    console: Console,
    action: str,
    ids: list[str] | None,
    search: str | None,
    category: str | None = None,
    sender: str | None = None,
    after: str | None = None,
    before: str | None = None,
    unread: bool = False,
    limit: int = 100,
    label: str | None = None,
    always_confirm: bool = False,
) -> None:
    """Single explicit id + a safe action -> execute immediately. Anything
    else (bulk, search-resolved, or archive/trash) -> propose, show the
    affected emails, and only confirm if the user explicitly says yes.
    """
    body = {
        "action": action,
        "message_ids": ids or None,
        "search": search,
        "category": category,
        "sender": sender,
        "after": after,
        "before": before,
        "unread_only": unread,
        "limit": limit,
        "label_name": label,
    }

    if not always_confirm and ids and len(ids) == 1 and not search:
        try:
            result = client.post("/actions/execute", body)
            console.print(f"[green]Done:[/green] {action} applied to {result['message_count']} email(s).")
            return
        except ClientError as e:
            if e.status_code != 400:
                raise
            # Backend says this needs confirmation after all (e.g. archive) — fall through.

    proposal = client.post("/actions/propose", body)
    count = proposal["affected_count"]
    if count == 0:
        console.print("[yellow]No matching emails found — nothing to do.[/yellow]")
        return

    console.print(f"\nThis will [bold]{action}[/bold] {count} email(s):\n")
    console.print(_affected_table(proposal["affected"]))

    if not Confirm.ask(f"\nProceed with {action} on {count} email(s)?", default=False):
        client.post("/actions/cancel", {"proposal_id": proposal["proposal_id"]})
        console.print("[yellow]Cancelled.[/yellow]")
        return

    result = client.post("/actions/confirm", {"proposal_id": proposal["proposal_id"]})
    console.print(f"[green]Done:[/green] {action} applied to {result['message_count']} email(s).")


def _affected_table(affected: list[dict]) -> Table:
    table = Table(show_header=True, header_style="bold")
    table.add_column("From")
    table.add_column("Subject")
    table.add_column("Date")
    table.add_column("Category")
    for m in affected:
        table.add_row(m["from"], m["subject"], (m.get("date") or "")[:10], m.get("category") or "")
    return table
