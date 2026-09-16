"""
Fetch subcommands: pull lsmod output from servers and persist to disk.

Storage layout
---------------
  data/servers/<ip>.txt   -- one module per line, full snapshot for that server
  data/fetch_index.csv    -- ip, fetched_at, module_count (lightweight lookup index)

Commands
--------
  fetch all        -- all servers in the inventory
  fetch server IP  -- single server
  fetch filter     -- subset by --server-type / --service / --component / --group / --os-filter
"""

import csv
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import click
import pandas as pd
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from fetch.ssh import run_lsmod
from ip_manager.ip_manager import load_ip_status, save_ip_status

console = Console(stderr=True)

# ── Per-server file + fetch index helpers ───────────────────────────────────

INDEX_COLS = ["ip", "fetched_at", "module_count"]


def _server_file(ip: str) -> str:
    return os.path.join(config.SERVERS_DIR, f"{ip}.txt")


def _write_server_modules(ip: str, modules: list) -> None:
    """Overwrite the per-server file with the latest full module snapshot."""
    with open(_server_file(ip), "w") as f:
        for module in modules:
            f.write(module + "\n")


def _load_fetch_index() -> pd.DataFrame:
    if not os.path.exists(config.FETCH_INDEX_CSV):
        return pd.DataFrame(columns=INDEX_COLS)
    return pd.read_csv(config.FETCH_INDEX_CSV, dtype=str)


def _save_fetch_index(df: pd.DataFrame) -> None:
    df.to_csv(config.FETCH_INDEX_CSV, index=False)


def _upsert_index_row(index_df: pd.DataFrame, ip: str, timestamp: str, count: int) -> pd.DataFrame:
    """Update or append the index row for ip. Returns the updated DataFrame."""
    mask = index_df["ip"] == ip
    if mask.any():
        index_df.loc[mask, ["fetched_at", "module_count"]] = [timestamp, str(count)]
    else:
        new_row = pd.DataFrame([{"ip": ip, "fetched_at": timestamp, "module_count": str(count)}])
        index_df = pd.concat([index_df, new_row], ignore_index=True)
    return index_df


# ── Core fetch logic ─────────────────────────────────────────────────────────

def _fetch_one(ip: str, skip_ips: set) -> dict:
    """Fetch lsmod for a single IP. Returns result dict."""
    if ip in skip_ips:
        return {"ip": ip, "success": False, "reason": "skipped", "modules": []}
    result = run_lsmod(
        ip,
        config.SSH_USER,
        config.SSH_PASSWORDS,
        connect_timeout=config.SSH_CONNECT_TIMEOUT,
        cmd_timeout=config.SSH_CMD_TIMEOUT,
    )
    result["ip"] = ip
    return result


def _do_fetch(servers: pd.DataFrame, workers: int, skip_unreachable: bool,
              dry_run: bool, inventory_csv: str) -> None:
    """Fetch modules for a DataFrame of servers (must have COL_SERVER_IP column)."""
    ips = (
        servers[config.COL_SERVER_IP]
        .dropna()
        .str.strip()
        .unique()
        .tolist()
    )
    ips = [ip for ip in ips if ip and ip != config.MISSING_VALUE]

    if not ips:
        console.print("[yellow]No servers to fetch.[/yellow]")
        return

    skip_ips: set = set()
    if skip_unreachable:
        status_df = load_ip_status()
        skip_ips = set(status_df["ip"].tolist())

    if dry_run:
        console.print(f"[cyan]Dry run — would fetch {len(ips)} server(s):[/cyan]")
        for ip in ips:
            console.print(f"  {ip}")
        return

    console.print(f"[bold]Fetching modules from {len(ips)} server(s) "
                  f"using {workers} parallel workers...[/bold]")

    timestamp = datetime.now(timezone.utc).isoformat()
    counters = {"ok": 0, "unreachable": 0, "timeout": 0,
                "password_expired": 0, "proxy_error": 0, "auth_failed": 0, "skipped": 0}

    status_df = load_ip_status()
    index_df = _load_fetch_index()

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    )

    with progress:
        task = progress.add_task("Fetching", total=len(ips))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_fetch_one, ip, skip_ips): ip for ip in ips}
            for future in as_completed(futures):
                result = future.result()
                ip = result["ip"]
                reason = result["reason"]
                counters[reason] = counters.get(reason, 0) + 1

                if result["success"]:
                    _write_server_modules(ip, result["modules"])
                    index_df = _upsert_index_row(index_df, ip, timestamp, len(result["modules"]))
                elif reason not in ("skipped",):
                    # Record failure in ip_status
                    now_str = datetime.now(timezone.utc).isoformat()
                    mask = status_df["ip"] == ip
                    if mask.any():
                        status_df.loc[mask, ["reason", "last_checked"]] = [reason, now_str]
                    else:
                        new_row = pd.DataFrame([{
                            "ip": ip, "reason": reason,
                            "notes": "", "added_at": now_str, "last_checked": now_str
                        }])
                        status_df = pd.concat([status_df, new_row], ignore_index=True)

                progress.advance(task)

    save_ip_status(status_df)
    _save_fetch_index(index_df)

    console.print("\n[bold]Results:[/bold]")
    console.print(f"  [green]✓ Success      : {counters['ok']}[/green]")
    console.print(f"  [red]✗ Unreachable  : {counters['unreachable']}[/red]")
    console.print(f"  [yellow]⏱ Timeout      : {counters['timeout']}[/yellow]")
    console.print(f"  [yellow]🔑 Pwd Expired  : {counters['password_expired']}[/yellow]")
    console.print(f"  [yellow]⚡ Proxy Error  : {counters['proxy_error']}[/yellow]")
    console.print(f"  [red]✗ Auth Failed  : {counters['auth_failed']}[/red]")
    if counters["skipped"]:
        console.print(f"  [dim]⊘ Skipped      : {counters['skipped']}[/dim]")


# ── Click commands ────────────────────────────────────────────────────────────

@click.group("fetch")
def fetch_group():
    """Fetch kernel modules from servers via SSH and store to CSV."""
    pass


_common_opts = [
    click.option("--workers", "-w", default=config.DEFAULT_WORKERS, show_default=True,
                 help="Parallel SSH workers."),
    click.option("--skip-unreachable", is_flag=True, default=True, show_default=True,
                 help="Skip IPs already marked unreachable/failed."),
    click.option("--dry-run", is_flag=True, default=False,
                 help="Print what would be fetched without connecting."),
    click.option("--inventory", default=config.DEFAULT_INVENTORY, show_default=True,
                 help="Path to the server inventory CSV."),
]


def _add_common_opts(cmd):
    for opt in reversed(_common_opts):
        cmd = opt(cmd)
    return cmd


def _apply_os_filter(df: pd.DataFrame, os_filter: str) -> pd.DataFrame:
    """
    'all'   -- no filtering
    'linux' -- excludes config.EXCLUDED_OS_PREFIXES (FreeBSD, CentOS, ...)
    other   -- treated as an OS-name prefix, e.g. 'Debian'
    """
    if os_filter.lower() == "all":
        return df
    if os_filter.lower() == "linux":
        mask = pd.Series(True, index=df.index)
        for prefix in config.EXCLUDED_OS_PREFIXES:
            mask &= ~df[config.COL_OS].str.startswith(prefix, na=False)
        return df[mask]
    return df[df[config.COL_OS].str.startswith(os_filter, na=False)]


@fetch_group.command("all")
@_add_common_opts
@click.option("--os-filter", default="linux",
              help=f"OS family filter: 'linux' (default, excludes {', '.join(config.EXCLUDED_OS_PREFIXES)}), "
                   "'all', or a prefix like 'Debian'.")
def fetch_all(workers, skip_unreachable, dry_run, inventory, os_filter):
    """Fetch modules from ALL servers in the inventory."""
    df = pd.read_csv(inventory, dtype=str).fillna(config.MISSING_VALUE)
    df = _apply_os_filter(df, os_filter)
    console.print(f"[cyan]Inventory filtered to {len(df)} server(s) (os-filter={os_filter!r}).[/cyan]")
    _do_fetch(df, workers, skip_unreachable, dry_run, inventory)


@fetch_group.command("server")
@click.argument("ip")
@click.option("--workers", "-w", default=1)
@click.option("--inventory", default=config.DEFAULT_INVENTORY)
def fetch_server(ip, workers, inventory):
    """Fetch modules from a SINGLE server by IP."""
    df = pd.DataFrame({config.COL_SERVER_IP: [ip]})
    _do_fetch(df, workers=1, skip_unreachable=False, dry_run=False, inventory_csv=inventory)


@fetch_group.command("filter")
@_add_common_opts
@click.option("--server-type", "server_type", default=None,
              help=f"Filter by server type: {', '.join(config.ALL_SERVER_TYPES)}")
@click.option("--service", default=None, help="Filter by ZService name.")
@click.option("--component", default=None, help="Filter by Component name.")
@click.option("--group", default=None, help="Filter by Group name.")
@click.option("--os-filter", default="linux",
              help=f"OS family filter: 'linux' (default, excludes {', '.join(config.EXCLUDED_OS_PREFIXES)}), "
                   "'all', or prefix like 'Debian'.")
def fetch_filter(workers, skip_unreachable, dry_run, inventory,
                 server_type, service, component, group, os_filter):
    """Fetch modules from a filtered subset of servers."""
    df = pd.read_csv(inventory, dtype=str).fillna(config.MISSING_VALUE)
    df = _apply_os_filter(df, os_filter)

    if server_type:
        df = df[df[config.COL_SERVER_TYPE].str.upper() == server_type.upper()]
    if service:
        df = df[df[config.COL_ZSERVICE] == service]
    if component:
        df = df[df[config.COL_COMPONENT] == component]
    if group:
        df = df[df[config.COL_GROUP] == group]

    console.print(f"[cyan]Filter matched {len(df)} server(s).[/cyan]")
    _do_fetch(df, workers, skip_unreachable, dry_run, inventory)
