"""
Exclusive-module analysis API.

"Exclusive" = modules found in category X but NOT in any server outside X.

Public functions
----------------
exclusive_to_server_type(data, stype)
exclusive_to_service(data, service)
exclusive_to_component(data, component)
exclusive_to_group(data, group)
exclusive_in_col(data, col, val)          -- generic version

compare_two(data, col, val_a, val_b)
    → {'only_a': [...], 'only_b': [...], 'common': [...]}

all_exclusive_by_col(data, col)
    → {val: [exclusive_modules], ...}  for every category in col
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config


def _modules_in(data: pd.DataFrame, col: str, val: str) -> set:
    return set(data[data[col] == val]["module"].dropna().unique())


def _modules_not_in(data: pd.DataFrame, col: str, val: str) -> set:
    return set(data[data[col] != val]["module"].dropna().unique())


def exclusive_in_col(data: pd.DataFrame, col: str, val: str) -> list[str]:
    """Modules that appear in val's servers but in NO other server in data."""
    target = _modules_in(data, col, val)
    others = _modules_not_in(data, col, val)
    return sorted(target - others)


def exclusive_to_server_type(data: pd.DataFrame, server_type: str) -> list[str]:
    col = config.COL_SERVER_TYPE
    val = server_type.upper()
    df = data.copy()
    df[col] = df[col].str.upper()
    return exclusive_in_col(df, col, val)


def exclusive_to_service(data: pd.DataFrame, service: str) -> list[str]:
    return exclusive_in_col(data, config.COL_ZSERVICE, service)


def exclusive_to_component(data: pd.DataFrame, component: str) -> list[str]:
    return exclusive_in_col(data, config.COL_COMPONENT, component)


def exclusive_to_group(data: pd.DataFrame, group: str) -> list[str]:
    return exclusive_in_col(data, config.COL_GROUP, group)


def compare_two(
    data: pd.DataFrame, col: str, val_a: str, val_b: str
) -> dict:
    """
    Compare modules between two category values.
    Returns {'only_a': [...], 'only_b': [...], 'common': [...]}.
    """
    a = _modules_in(data, col, val_a)
    b = _modules_in(data, col, val_b)
    return {
        "only_a": sorted(a - b),
        "only_b": sorted(b - a),
        "common": sorted(a & b),
    }


def all_exclusive_by_col(
    data: pd.DataFrame, col: str
) -> dict[str, list[str]]:
    """
    For every unique value in `col`, compute the exclusive modules.
    Skips the MISSING_VALUE placeholder.
    """
    result = {}
    for val in sorted(data[col].dropna().unique()):
        if val == config.MISSING_VALUE:
            continue
        result[val] = exclusive_in_col(data, col, val)
    return result
