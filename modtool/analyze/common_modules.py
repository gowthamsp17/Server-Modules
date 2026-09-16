"""
Common-module analysis API.

"Common" = a module present in at least `threshold` fraction of the servers
in the target set (default 1.0 = every server must have it).

Public functions
----------------
common_in_set(data, threshold)               -- across any pre-filtered DataFrame
common_across_all(data, threshold)           -- across ALL fetched servers
common_by_server_type(data, stype, threshold)
common_by_service(data, service, threshold)
common_by_component(data, component, threshold)
common_by_group(data, group, threshold)
default_for_type(data, stype)                -- modules in ALL servers of that type
                                                that are NOT common across ALL types
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config


def common_in_set(data: pd.DataFrame, threshold: float = 1.0) -> list[str]:
    """
    Return modules present in at least `threshold` fraction of the unique servers
    in `data`.  data must have columns: config.COL_SERVER_IP, 'module'.
    """
    if data.empty:
        return []
    total = data[config.COL_SERVER_IP].nunique()
    if total == 0:
        return []
    counts = data.groupby("module")[config.COL_SERVER_IP].nunique()
    min_count = max(1, round(threshold * total))
    return sorted(counts[counts >= min_count].index.tolist())


def common_across_all(data: pd.DataFrame, threshold: float = 1.0) -> list[str]:
    """Modules common across ALL fetched servers."""
    return common_in_set(data, threshold)


def common_by_server_type(data: pd.DataFrame, server_type: str,
                          threshold: float = 1.0) -> list[str]:
    """Modules common within a specific server type."""
    subset = data[data[config.COL_SERVER_TYPE].str.upper() == server_type.upper()]
    return common_in_set(subset, threshold)


def common_by_service(data: pd.DataFrame, service: str,
                      threshold: float = 1.0) -> list[str]:
    """Modules common within a ZService."""
    subset = data[data[config.COL_ZSERVICE] == service]
    return common_in_set(subset, threshold)


def common_by_component(data: pd.DataFrame, component: str,
                        threshold: float = 1.0) -> list[str]:
    """Modules common within a Component."""
    subset = data[data[config.COL_COMPONENT] == component]
    return common_in_set(subset, threshold)


def common_by_group(data: pd.DataFrame, group: str,
                    threshold: float = 1.0) -> list[str]:
    """Modules common within a Group."""
    subset = data[data[config.COL_GROUP] == group]
    return common_in_set(subset, threshold)


def default_for_type(data: pd.DataFrame, server_type: str) -> list[str]:
    """
    Modules that appear in ALL servers of `server_type` but are NOT
    universally common across all server types combined.
    These are the "type-specific defaults".
    """
    universal = set(common_across_all(data, threshold=1.0))
    type_common = set(common_by_server_type(data, server_type, threshold=1.0))
    return sorted(type_common - universal)


def per_category_common(data: pd.DataFrame, col: str,
                         threshold: float = 1.0) -> dict[str, list[str]]:
    """
    Return {category_value: [common_modules]} for every unique value in `col`.
    Useful for a summary sweep across all services, components, or groups.
    """
    result = {}
    for val in sorted(data[col].dropna().unique()):
        if val == config.MISSING_VALUE:
            continue
        subset = data[data[col] == val]
        result[val] = common_in_set(subset, threshold)
    return result
