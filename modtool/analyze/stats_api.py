"""
Stats / aggregation API.

Public functions
----------------
inventory_summary(inventory)          -- DC-wide counts from inventory only
coverage_stats(inventory, modules)    -- how many servers have been fetched
module_summary(data)                  -- high-level module stats from merged data
by_server_type(data)                  -- per-type breakdown
by_service(data)                      -- per-ZService breakdown
by_component(data)                    -- per-Component breakdown
by_group(data)                        -- per-Group breakdown
top_modules(data, n)                  -- n most widely loaded modules
rare_modules(data, n)                 -- n least widely loaded modules
module_server_count(data, module)     -- how many servers have a specific module
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config


def inventory_summary(inventory: pd.DataFrame) -> dict:
    """High-level counts derived from the inventory CSV alone (no module data needed)."""
    type_counts = (
        inventory[config.COL_SERVER_TYPE]
        .value_counts()
        .rename(index=config.SERVER_TYPE_LABELS)
        .to_dict()
    )
    service_count = inventory[config.COL_ZSERVICE].replace(config.MISSING_VALUE, pd.NA).nunique(dropna=True)
    component_count = inventory[config.COL_COMPONENT].replace(config.MISSING_VALUE, pd.NA).nunique(dropna=True)
    group_count = inventory[config.COL_GROUP].replace(config.MISSING_VALUE, pd.NA).nunique(dropna=True)
    os_counts = inventory[config.COL_OS].value_counts().to_dict()

    return {
        "total_servers": len(inventory),
        "by_server_type": type_counts,
        "unique_services": service_count,
        "unique_components": component_count,
        "unique_groups": group_count,
        "os_distribution": os_counts,
    }


def coverage_stats(inventory: pd.DataFrame, modules: pd.DataFrame) -> dict:
    """What fraction of the inventory has been fetched."""
    total = inventory[config.COL_SERVER_IP].nunique()
    fetched_ips = set(modules["server_ip"].unique()) if not modules.empty else set()
    inv_ips = set(inventory[config.COL_SERVER_IP].unique())
    fetched_in_inv = fetched_ips & inv_ips

    # Coverage per server type
    type_coverage = {}
    for stype in config.ALL_SERVER_TYPES:
        type_ips = set(
            inventory[inventory[config.COL_SERVER_TYPE].str.upper() == stype.upper()][
                config.COL_SERVER_IP
            ].unique()
        )
        fetched_of_type = fetched_in_inv & type_ips
        label = config.SERVER_TYPE_LABELS.get(stype, stype)
        type_coverage[label] = {
            "total": len(type_ips),
            "fetched": len(fetched_of_type),
            "pct": round(100 * len(fetched_of_type) / max(len(type_ips), 1), 1),
        }

    return {
        "inventory_total": total,
        "fetched": len(fetched_in_inv),
        "not_fetched": total - len(fetched_in_inv),
        "coverage_pct": round(100 * len(fetched_in_inv) / max(total, 1), 1),
        "by_server_type": type_coverage,
    }


def module_summary(data: pd.DataFrame) -> dict:
    """High-level stats from the merged (inventory + modules) DataFrame."""
    if data.empty:
        return {}
    servers_per_module = data.groupby("module")[config.COL_SERVER_IP].nunique()
    modules_per_server = data.groupby(config.COL_SERVER_IP)["module"].count()
    return {
        "total_servers_with_modules": data[config.COL_SERVER_IP].nunique(),
        "total_unique_modules": data["module"].nunique(),
        "avg_modules_per_server": round(modules_per_server.mean(), 1),
        "median_modules_per_server": round(modules_per_server.median(), 1),
        "min_modules_per_server": int(modules_per_server.min()),
        "max_modules_per_server": int(modules_per_server.max()),
        "most_common_module": servers_per_module.idxmax(),
        "rarest_module": servers_per_module.idxmin(),
    }


def _group_stats(data: pd.DataFrame, col: str) -> pd.DataFrame:
    """Return per-category stats DataFrame sorted by server count."""
    if data.empty:
        return pd.DataFrame()
    grp = data.groupby(col)
    servers = grp[config.COL_SERVER_IP].nunique().rename("servers")
    modules = grp["module"].nunique().rename("unique_modules")
    avg_mods = (
        data.groupby([col, config.COL_SERVER_IP])["module"]
        .count()
        .groupby(level=0)
        .mean()
        .round(1)
        .rename("avg_modules_per_server")
    )
    result = pd.concat([servers, modules, avg_mods], axis=1).reset_index()
    return result.sort_values("servers", ascending=False)


def by_server_type(data: pd.DataFrame) -> pd.DataFrame:
    df = data.copy()
    df[config.COL_SERVER_TYPE] = df[config.COL_SERVER_TYPE].map(
        lambda x: config.SERVER_TYPE_LABELS.get(x, x)
    )
    return _group_stats(df, config.COL_SERVER_TYPE)


def by_service(data: pd.DataFrame) -> pd.DataFrame:
    df = data[data[config.COL_ZSERVICE] != config.MISSING_VALUE].copy()
    return _group_stats(df, config.COL_ZSERVICE)


def by_component(data: pd.DataFrame) -> pd.DataFrame:
    df = data[data[config.COL_COMPONENT] != config.MISSING_VALUE].copy()
    return _group_stats(df, config.COL_COMPONENT)


def by_group(data: pd.DataFrame) -> pd.DataFrame:
    df = data[data[config.COL_GROUP] != config.MISSING_VALUE].copy()
    return _group_stats(df, config.COL_GROUP)


def top_modules(data: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """Top n modules by number of servers that have them."""
    if data.empty:
        return pd.DataFrame()
    counts = (
        data.groupby("module")[config.COL_SERVER_IP]
        .nunique()
        .reset_index()
        .rename(columns={config.COL_SERVER_IP: "server_count"})
        .sort_values("server_count", ascending=False)
        .head(n)
        .reset_index(drop=True)
    )
    total = data[config.COL_SERVER_IP].nunique()
    counts["pct_of_servers"] = (counts["server_count"] / total * 100).round(1)
    return counts


def rare_modules(data: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """Bottom n modules by server count (most rarely loaded)."""
    if data.empty:
        return pd.DataFrame()
    counts = (
        data.groupby("module")[config.COL_SERVER_IP]
        .nunique()
        .reset_index()
        .rename(columns={config.COL_SERVER_IP: "server_count"})
        .sort_values("server_count", ascending=True)
        .head(n)
        .reset_index(drop=True)
    )
    total = data[config.COL_SERVER_IP].nunique()
    counts["pct_of_servers"] = (counts["server_count"] / total * 100).round(1)
    return counts


def module_server_count(data: pd.DataFrame, module: str) -> int:
    """How many servers have a specific module loaded."""
    return int(data[data["module"] == module][config.COL_SERVER_IP].nunique())
