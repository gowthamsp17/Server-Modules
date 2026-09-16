"""
Output formatting helpers shared across all display/show scripts.

Supports three output formats:
  table  -- rich terminal table (default)
  json   -- JSON to stdout
  csv    -- CSV to stdout
"""

import csv
import io
import json
import sys

import pandas as pd
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()


def print_table(headers: list, rows: list, title: str = "", box_style=box.SIMPLE_HEAVY) -> None:
    t = Table(title=title, box=box_style, show_lines=False, highlight=True)
    for h in headers:
        t.add_column(str(h), overflow="fold")
    for row in rows:
        t.add_row(*[str(c) for c in row])
    console.print(t)


def print_key_value(data: dict, title: str = "") -> None:
    t = Table(title=title, box=box.SIMPLE_HEAVY, show_header=False, show_lines=False)
    t.add_column("Key", style="bold cyan")
    t.add_column("Value")
    for k, v in data.items():
        t.add_row(str(k), str(v))
    console.print(t)


def print_list(items: list, title: str = "", numbered: bool = False) -> None:
    if not items:
        console.print(f"[dim]{title or 'Result'}: (empty)[/dim]")
        return
    t = Table(title=f"{title} ({len(items)})", box=box.SIMPLE_HEAVY, show_lines=False)
    if numbered:
        t.add_column("#", style="dim", width=6)
        t.add_column("Module")
        for i, item in enumerate(items, 1):
            t.add_row(str(i), str(item))
    else:
        t.add_column("Module")
        for item in items:
            t.add_row(str(item))
    console.print(t)


def print_dataframe(df: pd.DataFrame, title: str = "",
                    fmt: str = "table", max_rows: int = 500) -> None:
    if fmt == "json":
        print(df.head(max_rows).to_json(orient="records", indent=2))
        return
    if fmt == "csv":
        print(df.head(max_rows).to_csv(index=False))
        return
    # table
    rows = df.head(max_rows).values.tolist()
    print_table(list(df.columns), rows, title=title)


def output_list(items: list, title: str = "", fmt: str = "table",
                numbered: bool = True) -> None:
    if fmt == "json":
        print(json.dumps(items, indent=2))
        return
    if fmt == "csv":
        w = csv.writer(sys.stdout)
        w.writerow(["#", "module"] if numbered else ["module"])
        for i, item in enumerate(items, 1):
            w.writerow([i, item] if numbered else [item])
        return
    print_list(items, title=title, numbered=numbered)


def output_compare(result: dict, label_a: str, label_b: str,
                   fmt: str = "table") -> None:
    """Print compare_two() result dict."""
    if fmt == "json":
        print(json.dumps(result, indent=2))
        return
    if fmt == "csv":
        w = csv.writer(sys.stdout)
        w.writerow(["section", "module"])
        for m in result["only_a"]:
            w.writerow([f"only_{label_a}", m])
        for m in result["only_b"]:
            w.writerow([f"only_{label_b}", m])
        for m in result["common"]:
            w.writerow(["common", m])
        return

    console.print(f"\n[bold cyan]Only in {label_a}[/bold cyan]  ({len(result['only_a'])})")
    print_list(result["only_a"])
    console.print(f"\n[bold magenta]Only in {label_b}[/bold magenta]  ({len(result['only_b'])})")
    print_list(result["only_b"])
    console.print(f"\n[bold green]Common to both[/bold green]  ({len(result['common'])})")
    print_list(result["common"])
