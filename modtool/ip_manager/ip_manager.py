"""
IP management subcommands.

Tracks servers that failed SSH for various reasons so they can be
skipped or retried later.

Storage: data/ip_status.csv
  ip, reason, notes, added_at, last_checked

Commands
--------
  ip list               -- list all tracked IPs (optionally by reason)
  ip add  <IP>          -- add an IP with a reason
  ip remove <IP>        -- remove an IP from tracking
  ip bulk-add           -- import IPs from a text file
  ip classify           -- auto-populate from the legacy txt files
  ip retry              -- show IPs that should be retried (timeout/proxy)
  ip clear              -- clear all entries (or by reason)
"""

import os
import sys
from datetime import datetime, timezone

import click
import pandas as pd
from rich.console import Console

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from display.formatter import print_dataframe, print_key_value, console

STATUS_COLS = ["ip", "reason", "notes", "added_at", "last_checked"]

# Reasons that make sense to retry automatically
RETRYABLE_REASONS = {config.REASON_TIMEOUT, config.REASON_PROXY_ERROR}


def load_ip_status(path: str = config.IP_STATUS_CSV) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame(columns=STATUS_COLS)
    df = pd.read_csv(path, dtype=str).fillna("")
    for col in STATUS_COLS:
        if col not in df.columns:
            df[col] = ""
    return df[STATUS_COLS]


def save_ip_status(df: pd.DataFrame, path: str = config.IP_STATUS_CSV) -> None:
    df[STATUS_COLS].to_csv(path, index=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Click commands ────────────────────────────────────────────────────────────

@click.group("ip")
def ip_group():
    """Manage server IPs that failed during fetch (unreachable, timeout, etc.)."""
    pass


@ip_group.command("list")
@click.option("--reason", default="all",
              type=click.Choice(config.ALL_REASONS + ["all"]),
              show_default=True, help="Filter by failure reason.")
@click.option("--fmt", default="table", type=click.Choice(["table", "json", "csv"]))
def cmd_list(reason, fmt):
    """List all tracked IPs with their failure reasons."""
    df = load_ip_status()
    if df.empty:
        console.print("[dim]No IPs tracked yet.[/dim]")
        return
    if reason and reason != "all":
        df = df[df["reason"] == reason]

    # Count summary
    counts = df["reason"].value_counts().to_dict()
    console.print(f"[bold]Total: {len(df)}[/bold]  |  " +
                  "  ".join(f"{r}: {c}" for r, c in counts.items()))
    print_dataframe(df, title="IP Status", fmt=fmt)


@ip_group.command("add")
@click.argument("ip")
@click.option("--reason", required=True,
              type=click.Choice(config.ALL_REASONS), help="Failure reason.")
@click.option("--notes", default="", help="Optional notes.")
def cmd_add(ip, reason, notes):
    """Add a single IP to the status list."""
    ip = ip.strip()
    df = load_ip_status()
    now = _now()
    mask = df["ip"] == ip
    if mask.any():
        df.loc[mask, ["reason", "notes", "last_checked"]] = [reason, notes, now]
        console.print(f"[yellow]Updated[/yellow] {ip} → reason={reason}")
    else:
        new_row = pd.DataFrame([{"ip": ip, "reason": reason,
                                  "notes": notes, "added_at": now, "last_checked": now}])
        df = pd.concat([df, new_row], ignore_index=True)
        console.print(f"[green]Added[/green] {ip} → reason={reason}")
    save_ip_status(df)


@ip_group.command("remove")
@click.argument("ip")
def cmd_remove(ip):
    """Remove an IP from the status list."""
    ip = ip.strip()
    df = load_ip_status()
    before = len(df)
    df = df[df["ip"] != ip]
    save_ip_status(df)
    if len(df) < before:
        console.print(f"[green]Removed[/green] {ip}")
    else:
        console.print(f"[yellow]{ip} was not in the list.[/yellow]")


@ip_group.command("bulk-add")
@click.argument("file", type=click.Path(exists=True))
@click.option("--reason", required=True, type=click.Choice(config.ALL_REASONS))
@click.option("--notes", default="", help="Notes applied to all IPs.")
def cmd_bulk_add(file, reason, notes):
    """Add IPs from a plain-text file (one IP per line)."""
    with open(file) as f:
        ips = [line.strip() for line in f if line.strip()]

    df = load_ip_status()
    now = _now()
    added = updated = 0
    for ip in ips:
        mask = df["ip"] == ip
        if mask.any():
            df.loc[mask, ["reason", "notes", "last_checked"]] = [reason, notes, now]
            updated += 1
        else:
            new_row = pd.DataFrame([{"ip": ip, "reason": reason,
                                      "notes": notes, "added_at": now, "last_checked": now}])
            df = pd.concat([df, new_row], ignore_index=True)
            added += 1
    save_ip_status(df)
    console.print(f"[green]Added {added}[/green], [yellow]updated {updated}[/yellow] IPs "
                  f"from {file!r} with reason={reason!r}.")


@ip_group.command("classify")
@click.option("--from-dir", default=None,
              help="Directory containing the legacy .txt files "
                   "(unreachable_ips.txt, timeout_ip.txt, etc.). Defaults to parent of modtool/.")
def cmd_classify(from_dir):
    """
    Auto-import IPs from the legacy text files produced by the old get_modules.sh script:
      unreachable_ips.txt, timeout_ip.txt, password_expired_ips.txt, proxy_error_ips.txt
    """
    base = from_dir or str(config.BASE_DIR.parent)
    file_reason_map = {
        "unreachable_ips.txt": config.REASON_UNREACHABLE,
        "timeout_ip.txt": config.REASON_TIMEOUT,
        "password_expired_ips.txt": config.REASON_PASSWORD_EXPIRED,
        "proxy_error_ips.txt": config.REASON_PROXY_ERROR,
    }
    df = load_ip_status()
    now = _now()
    total_added = total_updated = 0

    for fname, reason in file_reason_map.items():
        fpath = os.path.join(base, fname)
        if not os.path.exists(fpath):
            console.print(f"[dim]  {fname} not found, skipping.[/dim]")
            continue
        with open(fpath) as f:
            ips = [line.strip() for line in f if line.strip()]
        added = updated = 0
        for ip in ips:
            mask = df["ip"] == ip
            if mask.any():
                df.loc[mask, ["reason", "last_checked"]] = [reason, now]
                updated += 1
            else:
                new_row = pd.DataFrame([{
                    "ip": ip, "reason": reason,
                    "notes": f"imported from {fname}",
                    "added_at": now, "last_checked": now
                }])
                df = pd.concat([df, new_row], ignore_index=True)
                added += 1
        total_added += added
        total_updated += updated
        console.print(f"  [cyan]{fname}[/cyan] → {reason}: added {added}, updated {updated}")

    save_ip_status(df)
    console.print(f"\n[green]Total added: {total_added}[/green], "
                  f"[yellow]updated: {total_updated}[/yellow]")


@ip_group.command("retry")
@click.option("--reason", default=None,
              type=click.Choice(list(RETRYABLE_REASONS) + ["all"]),
              help="Filter to specific retryable reason (timeout or proxy_error). "
                   "Default: all retryable.")
@click.option("--fmt", default="table", type=click.Choice(["table", "json", "csv"]))
def cmd_retry(reason, fmt):
    """
    Show IPs worth retrying (timeout / proxy_error).

    Use the output to run:
      modtool ip list --reason timeout | awk '{print $1}' > retry.txt
      modtool fetch filter ...   (or iterate manually)
    """
    df = load_ip_status()
    if df.empty:
        console.print("[dim]No IPs tracked.[/dim]")
        return

    if reason and reason != "all":
        retryable = df[df["reason"] == reason]
    else:
        retryable = df[df["reason"].isin(RETRYABLE_REASONS)]

    if retryable.empty:
        console.print("[green]No retryable IPs found.[/green]")
        return

    console.print(f"[bold]{len(retryable)}[/bold] IP(s) eligible for retry.")
    print_dataframe(retryable, title="Retryable IPs", fmt=fmt)


@ip_group.command("clear")
@click.option("--reason", default=None, type=click.Choice(config.ALL_REASONS),
              help="Clear only IPs with this reason. Omit to clear all.")
@click.confirmation_option(prompt="This will delete tracked IPs. Continue?")
def cmd_clear(reason):
    """Clear IP status entries."""
    df = load_ip_status()
    if reason:
        before = len(df)
        df = df[df["reason"] != reason]
        removed = before - len(df)
        save_ip_status(df)
        console.print(f"[green]Removed {removed} IPs with reason={reason!r}.[/green]")
    else:
        save_ip_status(pd.DataFrame(columns=STATUS_COLS))
        console.print("[green]Cleared all IP status entries.[/green]")


@ip_group.command("stats")
def cmd_stats():
    """Show a summary count of tracked IPs by reason."""
    df = load_ip_status()
    if df.empty:
        console.print("[dim]No IPs tracked.[/dim]")
        return
    counts = df["reason"].value_counts()
    data = {r: int(counts.get(r, 0)) for r in config.ALL_REASONS}
    data["total"] = len(df)
    print_key_value(data, title="IP Status Summary")
