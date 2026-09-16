"""
Show subcommands — display already-fetched module data.

Commands
--------
  show server  <IP>     -- all modules for one server + server metadata
  show servers          -- table of servers with module counts
  show module  <NAME>   -- which servers have this module loaded
  show analyze common   -- common/default modules (with optional filters)
  show analyze exclusive-- modules exclusive to a category
  show analyze compare  -- compare two categories
  show analyze matrix   -- presence matrix across a category dimension
"""

import os
import sys

import click
import pandas as pd
from rich.console import Console

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from analyze.loader import (
    get_merged_data, load_inventory, load_modules,
    get_latest_modules, filter_merged, check_modules_exist, get_fetched_ips,
)
from analyze.common_modules import (
    common_across_all, common_by_server_type, common_by_service,
    common_by_component, common_by_group, default_for_type,
)
from analyze.exclusive_modules import (
    exclusive_to_server_type, exclusive_to_service, exclusive_to_component,
    exclusive_to_group, compare_two, all_exclusive_by_col,
)
from display.formatter import (
    print_table, print_key_value, print_list, print_dataframe,
    output_list, output_compare, console,
)

_FMT_OPT = click.option("--fmt", default="table", type=click.Choice(["table", "json", "csv"]),
                         show_default=True, help="Output format.")
_INV_OPT = click.option("--inventory", default=config.DEFAULT_INVENTORY, show_default=True)


def _require_modules(servers_dir: str = config.SERVERS_DIR) -> None:
    if not check_modules_exist(servers_dir):
        console.print("[red]No module data found. Run [bold]modtool fetch[/bold] first.[/red]")
        raise SystemExit(1)


# ── show group ────────────────────────────────────────────────────────────────

@click.group("show")
def show_group():
    """Display fetched module data."""
    pass


@show_group.command("server")
@click.argument("ip")
@_FMT_OPT
@_INV_OPT
def cmd_show_server(ip, fmt, inventory):
    """Show all loaded modules for a specific server IP."""
    _require_modules()
    data = get_merged_data(inventory)
    server_data = data[data[config.COL_SERVER_IP] == ip]

    if server_data.empty:
        # Check if server is in inventory but not yet fetched
        inv = load_inventory(inventory)
        in_inv = inv[inv[config.COL_SERVER_IP] == ip]
        if in_inv.empty:
            console.print(f"[red]IP {ip!r} not found in inventory.[/red]")
        else:
            console.print(f"[yellow]Server {ip} is in inventory but has not been fetched yet.[/yellow]")
            row = in_inv.iloc[0]
            print_key_value({
                "Server Type": row.get(config.COL_SERVER_TYPE, "-"),
                "OS": row.get(config.COL_OS, "-"),
                "ZService": row.get(config.COL_ZSERVICE, "-"),
                "Component": row.get(config.COL_COMPONENT, "-"),
                "Group": row.get(config.COL_GROUP, "-"),
            }, title=f"Server info: {ip}")
        return

    row = server_data.iloc[0]
    meta = {
        "Server Type": row.get(config.COL_SERVER_TYPE, "-"),
        "OS": row.get(config.COL_OS, "-"),
        "ZService": row.get(config.COL_ZSERVICE, "-"),
        "Component": row.get(config.COL_COMPONENT, "-"),
        "Group": row.get(config.COL_GROUP, "-"),
        "RAM (GB)": row.get(config.COL_RAM, "-"),
        "Fetched at": row.get("fetched_at", "-"),
    }
    print_key_value(meta, title=f"Server: {ip}")

    modules = sorted(server_data["module"].dropna().unique().tolist())
    output_list(modules, title=f"Modules ({len(modules)})", fmt=fmt)


@show_group.command("servers")
@_FMT_OPT
@_INV_OPT
@click.option("--server-type", default=None, help="Filter by server type.")
@click.option("--service", default=None, help="Filter by ZService.")
@click.option("--component", default=None, help="Filter by Component.")
@click.option("--group", default=None, help="Filter by Group.")
@click.option("--fetched/--not-fetched", default=None,
              help="Show only servers that have (or haven't) been fetched.")
@click.option("--limit", default=200, show_default=True, help="Max rows to display.")
def cmd_show_servers(fmt, inventory, server_type, service, component, group, fetched, limit):
    """List servers with their module counts."""
    inv = load_inventory(inventory)
    fetched_ips = get_fetched_ips()

    if server_type:
        inv = inv[inv[config.COL_SERVER_TYPE].str.upper() == server_type.upper()]
    if service:
        inv = inv[inv[config.COL_ZSERVICE] == service]
    if component:
        inv = inv[inv[config.COL_COMPONENT] == component]
    if group:
        inv = inv[inv[config.COL_GROUP] == group]

    if fetched is True:
        inv = inv[inv[config.COL_SERVER_IP].isin(fetched_ips)]
    elif fetched is False:
        inv = inv[~inv[config.COL_SERVER_IP].isin(fetched_ips)]

    if check_modules_exist():
        mods = get_latest_modules(load_modules())
        mod_counts = mods.groupby("server_ip")["module"].count().reset_index()
        mod_counts.columns = ["server_ip", "module_count"]
        inv = inv.merge(mod_counts, left_on=config.COL_SERVER_IP, right_on="server_ip", how="left")
        inv["module_count"] = inv["module_count"].fillna(0).astype(int)
        inv = inv.drop(columns=["server_ip"], errors="ignore")
    else:
        inv["module_count"] = 0

    display_cols = [
        config.COL_SERVER_IP, config.COL_SERVER_TYPE, config.COL_OS,
        config.COL_ZSERVICE, config.COL_COMPONENT, config.COL_GROUP, "module_count"
    ]
    existing = [c for c in display_cols if c in inv.columns]
    print_dataframe(inv[existing].head(limit), title=f"Servers ({len(inv)} total)", fmt=fmt)


@show_group.command("module")
@click.argument("module_name")
@_FMT_OPT
@_INV_OPT
@click.option("--server-type", default=None)
@click.option("--service", default=None)
@click.option("--component", default=None)
@click.option("--group", default=None)
def cmd_show_module(module_name, fmt, inventory, server_type, service, component, group):
    """Show which servers have a specific module loaded."""
    _require_modules()
    data = get_merged_data(inventory)
    data = filter_merged(data, server_type, service, component, group)
    subset = data[data["module"] == module_name]

    if subset.empty:
        console.print(f"[yellow]Module {module_name!r} not found in any fetched server.[/yellow]")
        return

    display_cols = [config.COL_SERVER_IP, config.COL_SERVER_TYPE, config.COL_OS,
                    config.COL_ZSERVICE, config.COL_COMPONENT, config.COL_GROUP]
    existing = [c for c in display_cols if c in subset.columns]
    df = subset[existing].drop_duplicates().reset_index(drop=True)
    console.print(f"[bold]{module_name}[/bold] is loaded on [cyan]{len(df)}[/cyan] server(s).")
    print_dataframe(df, title=f"Servers with module: {module_name}", fmt=fmt)


# ── show analyze subgroup ─────────────────────────────────────────────────────

@show_group.group("analyze")
def analyze_group():
    """Analyze module patterns across categories."""
    pass


def _filter_opts(cmd):
    opts = [
        click.option("--server-type", default=None),
        click.option("--service", default=None),
        click.option("--component", default=None),
        click.option("--group", default=None),
    ]
    for o in reversed(opts):
        cmd = o(cmd)
    return cmd


@analyze_group.command("common")
@_FMT_OPT
@_INV_OPT
@_filter_opts
@click.option("--threshold", default=1.0, show_default=True,
              help="Min fraction of servers that must have the module (0.0–1.0).")
@click.option("--exclude-global", is_flag=True, default=False,
              help="When filtering by a category, subtract modules common across ALL servers.")
def cmd_analyze_common(fmt, inventory, server_type, service, component, group,
                        threshold, exclude_global):
    """
    Find common (default) modules within a set of servers.

    Without filters: modules common across ALL fetched servers.
    With --server-type/--service/etc.: common within that category.
    With --exclude-global: removes modules that are also universal across all servers,
    showing what's 'extra default' for the category.
    """
    _require_modules()
    data = get_merged_data(inventory)

    # Determine label and compute modules
    if server_type:
        label = f"server-type={server_type}"
        mods = common_by_server_type(data, server_type, threshold)
        if exclude_global:
            global_mods = set(common_across_all(data, threshold=1.0))
            mods = [m for m in mods if m not in global_mods]
    elif service:
        label = f"service={service}"
        mods = common_by_service(data, service, threshold)
        if exclude_global:
            global_mods = set(common_across_all(data, threshold=1.0))
            mods = [m for m in mods if m not in global_mods]
    elif component:
        label = f"component={component}"
        mods = common_by_component(data, component, threshold)
        if exclude_global:
            global_mods = set(common_across_all(data, threshold=1.0))
            mods = [m for m in mods if m not in global_mods]
    elif group:
        label = f"group={group}"
        mods = common_by_group(data, group, threshold)
        if exclude_global:
            global_mods = set(common_across_all(data, threshold=1.0))
            mods = [m for m in mods if m not in global_mods]
    else:
        label = "all servers"
        mods = common_across_all(data, threshold)

    suffix = " (excluding global defaults)" if exclude_global else ""
    title = f"Common modules in [{label}] @ threshold={threshold}{suffix}"
    output_list(mods, title=title, fmt=fmt)


@analyze_group.command("exclusive")
@_FMT_OPT
@_INV_OPT
@click.option("--server-type", default=None)
@click.option("--service", default=None)
@click.option("--component", default=None)
@click.option("--group", default=None)
@click.option("--all-values", is_flag=True, default=False,
              help="Compute exclusive modules for every value in the chosen dimension.")
def cmd_analyze_exclusive(fmt, inventory, server_type, service, component, group, all_values):
    """
    Find modules exclusive to a specific category (not in any other server).

    --all-values: iterate over every value in the chosen dimension and show each.
    """
    _require_modules()
    data = get_merged_data(inventory)

    if all_values:
        if server_type or not (service or component or group):
            col, dim = config.COL_SERVER_TYPE, "server-type"
        elif service:
            col, dim = config.COL_ZSERVICE, "service"
        elif component:
            col, dim = config.COL_COMPONENT, "component"
        else:
            col, dim = config.COL_GROUP, "group"
        results = all_exclusive_by_col(data, col)
        for val, mods in results.items():
            if mods:
                output_list(mods, title=f"Exclusive to {dim}={val!r}", fmt=fmt)
        return

    if server_type:
        mods = exclusive_to_server_type(data, server_type)
        label = f"server-type={server_type}"
    elif service:
        mods = exclusive_to_service(data, service)
        label = f"service={service}"
    elif component:
        mods = exclusive_to_component(data, component)
        label = f"component={component}"
    elif group:
        mods = exclusive_to_group(data, group)
        label = f"group={group}"
    else:
        console.print("[red]Provide at least one of: --server-type, --service, --component, --group[/red]")
        raise SystemExit(1)

    output_list(mods, title=f"Modules exclusive to [{label}]", fmt=fmt)


@analyze_group.command("compare")
@_FMT_OPT
@_INV_OPT
@click.option("--server-type-a", default=None)
@click.option("--server-type-b", default=None)
@click.option("--service-a", default=None)
@click.option("--service-b", default=None)
@click.option("--component-a", default=None)
@click.option("--component-b", default=None)
@click.option("--group-a", default=None)
@click.option("--group-b", default=None)
def cmd_analyze_compare(fmt, inventory,
                         server_type_a, server_type_b,
                         service_a, service_b,
                         component_a, component_b,
                         group_a, group_b):
    """
    Compare modules between two categories.

    Examples:
      modtool show analyze compare --server-type-a KVM --server-type-b VM
      modtool show analyze compare --service-a Crm --service-b ZMail
    """
    _require_modules()
    data = get_merged_data(inventory)

    if server_type_a and server_type_b:
        col = config.COL_SERVER_TYPE
        df = data.copy(); df[col] = df[col].str.upper()
        result = compare_two(df, col, server_type_a.upper(), server_type_b.upper())
        label_a, label_b = server_type_a, server_type_b
    elif service_a and service_b:
        result = compare_two(data, config.COL_ZSERVICE, service_a, service_b)
        label_a, label_b = service_a, service_b
    elif component_a and component_b:
        result = compare_two(data, config.COL_COMPONENT, component_a, component_b)
        label_a, label_b = component_a, component_b
    elif group_a and group_b:
        result = compare_two(data, config.COL_GROUP, group_a, group_b)
        label_a, label_b = group_a, group_b
    else:
        console.print("[red]Provide --*-a and --*-b for the same dimension.[/red]")
        raise SystemExit(1)

    output_compare(result, label_a, label_b, fmt=fmt)


@analyze_group.command("matrix")
@_INV_OPT
@click.option("--by", default="server-type",
              type=click.Choice(["server-type", "service", "component", "group"]),
              show_default=True, help="Dimension for the matrix rows.")
@click.option("--top-modules", "top_n", default=30, show_default=True,
              help="Number of top modules (by prevalence) to include as columns.")
def cmd_analyze_matrix(inventory, by, top_n):
    """
    Show a module-presence matrix: rows=category, columns=top modules.
    A cell shows the % of servers in that category that have the module.
    """
    _require_modules()
    data = get_merged_data(inventory)

    col_map = {
        "server-type": config.COL_SERVER_TYPE,
        "service": config.COL_ZSERVICE,
        "component": config.COL_COMPONENT,
        "group": config.COL_GROUP,
    }
    col = col_map[by]

    # Pick top_n modules by total server count
    top = (
        data.groupby("module")[config.COL_SERVER_IP].nunique()
        .sort_values(ascending=False)
        .head(top_n)
        .index.tolist()
    )

    data_top = data[data["module"].isin(top)]
    rows = []
    for val in sorted(data[col].dropna().unique()):
        if val == config.MISSING_VALUE:
            continue
        subset = data_top[data_top[col] == val]
        total_servers = data[data[col] == val][config.COL_SERVER_IP].nunique()
        row = [val, total_servers]
        for mod in top:
            cnt = subset[subset["module"] == mod][config.COL_SERVER_IP].nunique()
            pct = round(100 * cnt / max(total_servers, 1))
            row.append(f"{pct}%")
        rows.append(row)

    headers = [by, "servers"] + top
    print_table(headers, rows, title=f"Module presence matrix (by {by}, top {top_n} modules)")
