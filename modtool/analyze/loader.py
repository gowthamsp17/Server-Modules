"""
Data loading and merging utilities.

Storage layout
---------------
  data/servers/<ip>.txt   : one module per line, full snapshot for that server
  data/fetch_index.csv    : ip, fetched_at, module_count (lightweight lookup index)
  inventory CSV columns   : see config.py COL_* constants

load_modules() reconstructs the same long-format (server_ip, module, fetched_at)
DataFrame the rest of the analysis code expects, by reading every per-server
file. Since each fetch overwrites a server's file in full, there is never more
than one snapshot on disk per server — get_latest_modules() is kept only for
API compatibility with existing callers.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

MODULES_COLS = ["server_ip", "module", "fetched_at"]
INDEX_COLS = ["ip", "fetched_at", "module_count"]


def load_inventory(path: str = config.DEFAULT_INVENTORY) -> pd.DataFrame:
    """Load the server inventory CSV. Returns a DataFrame with all columns."""
    df = pd.read_csv(path, dtype=str).fillna(config.MISSING_VALUE)
    df[config.COL_SERVER_IP] = df[config.COL_SERVER_IP].str.strip()
    return df


def load_fetch_index(path: str = config.FETCH_INDEX_CSV) -> pd.DataFrame:
    """Load the lightweight per-server index (ip, fetched_at, module_count)."""
    if not os.path.exists(path):
        return pd.DataFrame(columns=INDEX_COLS)
    df = pd.read_csv(path, dtype=str)
    df["ip"] = df["ip"].str.strip()
    return df


def load_modules_for_ip(ip: str, servers_dir: str = config.SERVERS_DIR) -> list:
    """Read the module list for a single server straight from its per-IP file."""
    path = os.path.join(servers_dir, f"{ip}.txt")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]


def load_modules(
    servers_dir: str = config.SERVERS_DIR,
    index_path: str = config.FETCH_INDEX_CSV,
) -> pd.DataFrame:
    """
    Reconstruct the long-format module DataFrame (server_ip, module, fetched_at)
    by reading every per-server file under data/servers/.
    """
    if not os.path.isdir(servers_dir):
        return pd.DataFrame(columns=MODULES_COLS)

    index = load_fetch_index(index_path)
    fetched_at_map = dict(zip(index["ip"], index["fetched_at"])) if not index.empty else {}

    ips, modules, fetched_ats = [], [], []
    with os.scandir(servers_dir) as entries:
        for entry in entries:
            if not entry.name.endswith(".txt"):
                continue
            ip = entry.name[:-len(".txt")]
            fetched_at = fetched_at_map.get(ip, "")
            with open(entry.path) as f:
                for line in f:
                    module = line.strip()
                    if not module:
                        continue
                    ips.append(ip)
                    modules.append(module)
                    fetched_ats.append(fetched_at)

    return pd.DataFrame({"server_ip": ips, "module": modules, "fetched_at": fetched_ats})


def get_latest_modules(modules_df: pd.DataFrame) -> pd.DataFrame:
    """
    Kept for API compatibility with existing callers. Each per-server file is
    always a full overwrite of that server's latest fetch, so load_modules()
    never returns more than one snapshot per server — nothing to filter here.
    """
    return modules_df


def get_merged_data(
    inventory_path: str = config.DEFAULT_INVENTORY,
    servers_dir: str = config.SERVERS_DIR,
) -> pd.DataFrame:
    """
    Join inventory with module data.
    Returns a DataFrame with inventory metadata + module column.
    Only servers that have been fetched appear.
    """
    inv = load_inventory(inventory_path)
    mods = load_modules(servers_dir)
    merged = inv.merge(mods, left_on=config.COL_SERVER_IP, right_on="server_ip", how="inner")
    merged = merged.drop(columns=["server_ip"], errors="ignore")
    return merged


def check_modules_exist(servers_dir: str = config.SERVERS_DIR) -> bool:
    """Fast existence check — looks at the servers dir, doesn't read any file contents."""
    if not os.path.isdir(servers_dir):
        return False
    with os.scandir(servers_dir) as entries:
        return any(entry.name.endswith(".txt") for entry in entries)


def get_fetched_ips(servers_dir: str = config.SERVERS_DIR) -> set:
    """Return the set of server IPs that have been fetched (filenames only, no file reads)."""
    if not os.path.isdir(servers_dir):
        return set()
    with os.scandir(servers_dir) as entries:
        return {entry.name[:-len(".txt")] for entry in entries if entry.name.endswith(".txt")}


def filter_merged(
    data: pd.DataFrame,
    server_type: str = None,
    service: str = None,
    component: str = None,
    group: str = None,
) -> pd.DataFrame:
    """Apply categorical filters to a merged DataFrame."""
    df = data.copy()
    if server_type:
        df = df[df[config.COL_SERVER_TYPE].str.upper() == server_type.upper()]
    if service:
        df = df[df[config.COL_ZSERVICE] == service]
    if component:
        df = df[df[config.COL_COMPONENT] == component]
    if group:
        df = df[df[config.COL_GROUP] == group]
    return df
