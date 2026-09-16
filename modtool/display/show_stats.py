"""
Stats subcommands — cumulative statistics about the DC and module data.

Commands
--------
  stats summary       -- DC-wide overview (inventory + modules)
  stats coverage      -- fetch coverage per server type
  stats by-type       -- per server-type breakdown
  stats by-service    -- per ZService breakdown
  stats by-component  -- per Component breakdown
  stats by-group      -- per Group breakdown
  stats top-modules   -- N most prevalent modules
  stats rare-modules  -- N least prevalent modules
"""

import os
import sys

import click
from rich.console import Console

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from analyze.loader import (
    get_merged_data, load_inventory, load_modules,
    get_latest_modules, check_modules_exist,
)
from analyze.stats_api import (
    inventory_summary, coverage_stats, module_summary,
    by_server_type, by_service, by_component, by_group,
    top_modules, rare_modules,
)
from display.formatter import (
    print_key_value, print_dataframe, print_table, console,
)

_FMT_OPT = click.option("--fmt", default="table", type=click.Choice(["table", "json", "csv"]),
                         show_default=True)
_INV_OPT = click.option("--inventory", default=config.DEFAULT_INVENTORY, show_default=True)


@click.group("stats")
def stats_group():
    """Cumulative statistics about the DC and module data."""
    pass


@stats_group.command("summary")
@_FMT_OPT
@_INV_OPT
def cmd_summary(fmt, inventory):
    """Overall DC summary: inventory counts + module data overview."""
    inv = load_inventory(inventory)
    inv_stats = inventory_summary(inv)

    # Flatten nested dicts for display
    flat = {
        "Total servers in inventory": inv_stats["total_servers"],
        "Unique ZServices": inv_stats["unique_services"],
        "Unique Components": inv_stats["unique_components"],
        "Unique Groups": inv_stats["unique_groups"],
    }
    for stype, cnt in inv_stats["by_server_type"].items():
        flat[f"  {stype}"] = cnt

    if check_modules_exist():
        data = get_merged_data(inventory)
        ms = module_summary(data)
        flat.update({
            "─" * 30: "─" * 10,
            "Servers with modules fetched": ms.get("total_servers_with_modules", 0),
            "Total unique modules": ms.get("total_unique_modules", 0),
            "Avg modules per server": ms.get("avg_modules_per_server", 0),
            "Median modules per server": ms.get("median_modules_per_server", 0),
            "Min modules per server": ms.get("min_modules_per_server", 0),
            "Max modules per server": ms.get("max_modules_per_server", 0),
        })
    else:
        flat["Module data"] = "Not fetched yet — run: modtool fetch all"

    if fmt == "json":
        import json
        print(json.dumps(inv_stats, indent=2))
    elif fmt == "csv":
        for k, v in flat.items():
            print(f"{k},{v}")
    else:
        print_key_value(flat, title="DC Summary")


@stats_group.command("coverage")
@_FMT_OPT
@_INV_OPT
def cmd_coverage(fmt, inventory):
    """Show how much of the inventory has been fetched."""
    inv = load_inventory(inventory)
    mods = get_latest_modules(load_modules()) if check_modules_exist() else load_modules()
    cov = coverage_stats(inv, mods)

    flat = {
        "Inventory total": cov["inventory_total"],
        "Fetched": cov["fetched"],
        "Not fetched": cov["not_fetched"],
        "Coverage %": f"{cov['coverage_pct']}%",
    }
    if fmt == "json":
        import json; print(json.dumps(cov, indent=2))
    elif fmt == "csv":
        for k, v in flat.items():
            print(f"{k},{v}")
        print("\nBy server type")
        for label, d in cov["by_server_type"].items():
            print(f"{label},{d['fetched']}/{d['total']},{d['pct']}%")
    else:
        print_key_value(flat, title="Fetch Coverage")
        rows = [
            [label, d["total"], d["fetched"], f"{d['pct']}%"]
            for label, d in cov["by_server_type"].items()
        ]
        print_table(
            ["Server Type", "Total", "Fetched", "Coverage %"],
            rows,
            title="Coverage by Server Type",
        )


@stats_group.command("by-type")
@_FMT_OPT
@_INV_OPT
def cmd_by_type(fmt, inventory):
    """Module stats broken down by server type."""
    if not check_modules_exist():
        console.print("[red]No module data. Run [bold]modtool fetch[/bold] first.[/red]")
        raise SystemExit(1)
    data = get_merged_data(inventory)
    df = by_server_type(data)
    print_dataframe(df, title="Stats by Server Type", fmt=fmt)


@stats_group.command("by-service")
@_FMT_OPT
@_INV_OPT
@click.option("--limit", default=50, show_default=True)
def cmd_by_service(fmt, inventory, limit):
    """Module stats broken down by ZService."""
    if not check_modules_exist():
        console.print("[red]No module data. Run [bold]modtool fetch[/bold] first.[/red]")
        raise SystemExit(1)
    data = get_merged_data(inventory)
    df = by_service(data).head(limit)
    print_dataframe(df, title="Stats by ZService (top by server count)", fmt=fmt)


@stats_group.command("by-component")
@_FMT_OPT
@_INV_OPT
@click.option("--limit", default=50, show_default=True)
def cmd_by_component(fmt, inventory, limit):
    """Module stats broken down by Component."""
    if not check_modules_exist():
        console.print("[red]No module data. Run [bold]modtool fetch[/bold] first.[/red]")
        raise SystemExit(1)
    data = get_merged_data(inventory)
    df = by_component(data).head(limit)
    print_dataframe(df, title="Stats by Component (top by server count)", fmt=fmt)


@stats_group.command("by-group")
@_FMT_OPT
@_INV_OPT
@click.option("--limit", default=50, show_default=True)
def cmd_by_group(fmt, inventory, limit):
    """Module stats broken down by Group."""
    if not check_modules_exist():
        console.print("[red]No module data. Run [bold]modtool fetch[/bold] first.[/red]")
        raise SystemExit(1)
    data = get_merged_data(inventory)
    df = by_group(data).head(limit)
    print_dataframe(df, title="Stats by Group (top by server count)", fmt=fmt)


@stats_group.command("top-modules")
@_FMT_OPT
@_INV_OPT
@click.option("-n", default=20, show_default=True, help="Number of top modules to show.")
@click.option("--server-type", default=None)
@click.option("--service", default=None)
@click.option("--component", default=None)
@click.option("--group", default=None)
def cmd_top_modules(fmt, inventory, n, server_type, service, component, group):
    """Show the N most widely loaded modules."""
    if not check_modules_exist():
        console.print("[red]No module data. Run [bold]modtool fetch[/bold] first.[/red]")
        raise SystemExit(1)
    from analyze.loader import filter_merged
    data = get_merged_data(inventory)
    data = filter_merged(data, server_type, service, component, group)
    df = top_modules(data, n)
    print_dataframe(df, title=f"Top {n} modules by server count", fmt=fmt)


@stats_group.command("rare-modules")
@_FMT_OPT
@_INV_OPT
@click.option("-n", default=20, show_default=True, help="Number of rare modules to show.")
@click.option("--server-type", default=None)
@click.option("--service", default=None)
@click.option("--component", default=None)
@click.option("--group", default=None)
def cmd_rare_modules(fmt, inventory, n, server_type, service, component, group):
    """Show the N least prevalent (rarest) modules."""
    if not check_modules_exist():
        console.print("[red]No module data. Run [bold]modtool fetch[/bold] first.[/red]")
        raise SystemExit(1)
    from analyze.loader import filter_merged
    data = get_merged_data(inventory)
    data = filter_merged(data, server_type, service, component, group)
    df = rare_modules(data, n)
    print_dataframe(df, title=f"Rarest {n} modules by server count", fmt=fmt)
