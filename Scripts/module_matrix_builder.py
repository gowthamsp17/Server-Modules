"""
module_matrix_builder.py

Builds an IP x kernel-module presence matrix from a CT1 action template
CSV containing lsmod output per IP. Each cell is 1 (module present),
blank (module absent), or "-" (IP unreachable / authentication failed).

Usage:
    python3 module_matrix_builder.py <input.csv> <output.csv>

Both arguments are required.
"""

import sys
import re
import socket
import struct
import os
import pandas as pd


def ip_sort_key(ip: str):
    """Convert an IPv4 string to a sortable integer; non-IP values sort last."""
    try:
        return (0, struct.unpack('!I', socket.inet_aton(ip))[0])
    except (OSError, TypeError):
        return (1, ip)


def load_debian_ips(data_dir: str) -> set:
    """Collect the set of IPs whose OS is Debian, from the three inventory
    sheets (CT1_CNs.csv, CT1_PS_KVM_CH.csv, CT1_VMs.csv).
    """
    sources = [
        (os.path.join(data_dir, 'CT1_CNs.csv'), 'Container IP', 'OS'),
        (os.path.join(data_dir, 'CT1_PS_KVM_CH.csv'), 'Physical IP', 'OS'),
        (os.path.join(data_dir, 'CT1_VMs.csv'), 'Virtual Machine IP', 'OS'),
    ]

    debian_ips = set()
    for path, ip_col, os_col in sources:
        if not os.path.isfile(path):
            print(f"[!] Warning: inventory file not found, skipping: {path}")
            continue
        inv = pd.read_csv(path, dtype=str, keep_default_na=False)
        if ip_col not in inv.columns or os_col not in inv.columns:
            print(f"[!] Warning: expected columns '{ip_col}'/'{os_col}' not "
                 f"found in {path}, skipping.")
            continue
        is_debian = inv[os_col].str.strip().str.lower().str.startswith('debian')
        debian_ips.update(inv.loc[is_debian, ip_col].str.strip())

    return debian_ips


def parse_modules(output: str) -> set:
    """Extract module names from lsmod output string.

    The output may contain unrelated preamble lines (e.g. bash errors)
    before the actual 'Module  Size  Used by' header. Only lines after
    that header are treated as module entries.
    """
    modules = set()
    lines = re.split(r'\r?\n', str(output))

    # Find the lsmod header line
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith('Module') and 'Used by' in line:
            header_idx = i
            break

    if header_idx is None:
        return modules  # no lsmod output present in this cell

    for line in lines[header_idx + 1:]:
        parts = line.strip().split()
        if parts:
            modules.add(parts[0])
    return modules


def build_module_matrix(input_path: str, output_path: str):
    print(f"[*] Reading: {input_path}")
    df = pd.read_csv(input_path)

    # Validate expected columns
    for col in ('IP', 'Output'):
        if col not in df.columns:
            raise ValueError(f"Expected column '{col}' not found. "
                             f"Available: {df.columns.tolist()}")

    # Keep only IP and Output
    df = df[['IP', 'Output']].copy()
    print(f"[*] Rows: {len(df)}  |  Unique IPs: {df['IP'].nunique()}")

    # Parse modules per row
    df['_modules'] = df['Output'].apply(parse_modules)

    # Flag rows that never actually produced lsmod output
    df['_node_not_reachable'] = df['Output'].astype(str).str.contains(
        'Node not reachable', case=False, na=False)
    df['_auth_failed'] = df['Output'].astype(str).str.contains(
        'Authentication failed', case=False, na=False)
    df['_command_not_found'] = df['Output'].astype(str).str.contains(
        r'lsmod:\s*(?:command\s+)?not\s+found', case=False, na=False, regex=True)

    # Aggregate modules per unique IP (union across all rows for that IP,
    # so repeated IPs collapse into a single record instead of duplicate rows)
    grouped = df.groupby('IP').agg(
        _modules=('_modules', lambda sets: set().union(*sets)),
        _node_not_reachable=('_node_not_reachable', 'any'),
        _auth_failed=('_auth_failed', 'any'),
        _command_not_found=('_command_not_found', 'any'),
    )

    if grouped.empty:
        all_modules = []
    else:
        all_modules = sorted(set().union(*grouped['_modules']))
    print(f"[*] Unique modules found across all IPs: {len(all_modules)}")

    # Build pivot table: one row per unique IP, one column per module.
    # If the IP hit "Node not reachable", "Authentication failed", or
    # "lsmod: command not found", module columns are marked "-". Otherwise
    # present modules are marked "1" and absent modules are left blank
    # (instead of "0").
    rows = []
    for _, grp_row in grouped.iterrows():
        unreachable = grp_row['_node_not_reachable']
        auth_failed = grp_row['_auth_failed']
        command_not_found = grp_row['_command_not_found']
        if unreachable or auth_failed or command_not_found:
            rows.append(['-'] * len(all_modules))
        else:
            mods = grp_row['_modules']
            rows.append([1 if mod in mods else '' for mod in all_modules])

    result = pd.DataFrame(rows, index=grouped.index, columns=all_modules)
    result.insert(0, 'Node Not Reachable', grouped['_node_not_reachable'].astype(int).values)
    result.insert(1, 'Authentication Failed', grouped['_auth_failed'].astype(int).values)
    result.insert(2, 'Command Not Found', grouped['_command_not_found'].astype(int).values)

    # Per-IP count of modules loaded (number of "1" cells among module columns)
    modules_loaded_count = (result[all_modules] == 1).sum(axis=1)
    result.insert(0, 'No of Modules', modules_loaded_count.values)

    result = result.reset_index()

    # Sort rows by IP address (ascending, numeric) so downstream tools can
    # binary-search the output by IP.
    result = result.iloc[
        sorted(range(len(result)), key=lambda i: ip_sort_key(result.iloc[i]['IP']))
    ].reset_index(drop=True)

    # Per-module count of IPs where that module is loaded, added as a
    # second header-like row ("Modules Count") right below the column
    # headers.
    modules_count_row = {col: '' for col in result.columns}
    modules_count_row['IP'] = 'Modules Count'
    for mod in all_modules:
        modules_count_row[mod] = int((result[mod] == 1).sum())
    modules_count_df = pd.DataFrame([modules_count_row], columns=result.columns)
    result = pd.concat([modules_count_df, result], ignore_index=True)

    # Save the full (unfiltered) matrix as a "_bak" file.
    base, ext = os.path.splitext(output_path)
    bak_path = f"{base}_bak{ext}"
    result.to_csv(bak_path, index=False)
    print(f"[*] Full output shape: {result.shape}  (rows x cols)")
    print(f"[✓] Saved backup: {bak_path}")

    # Build the filtered matrix: drop servers flagged as unreachable,
    # auth-failed, or command-not-found, and drop those flag columns.
    # Also keep only Debian servers, per the CT1 inventory sheets.
    flag_cols = ['Node Not Reachable', 'Authentication Failed', 'Command Not Found']
    data_rows = result[result['IP'] != 'Modules Count'].copy()
    keep_mask = (data_rows[flag_cols] == 0).all(axis=1)
    data_rows = data_rows[keep_mask].drop(columns=flag_cols)

    data_dir = os.path.join(os.path.dirname(os.path.abspath(output_path)), 'data')
    debian_ips = load_debian_ips(data_dir)
    print(f"[*] Debian IPs found across inventory sheets: {len(debian_ips)}")
    data_rows = data_rows[data_rows['IP'].isin(debian_ips)]

    filtered_modules_count_row = {col: '' for col in data_rows.columns}
    filtered_modules_count_row['IP'] = 'Modules Count'
    for mod in all_modules:
        filtered_modules_count_row[mod] = int((data_rows[mod] == 1).sum())
    filtered_modules_count_df = pd.DataFrame([filtered_modules_count_row], columns=data_rows.columns)
    filtered_result = pd.concat([filtered_modules_count_df, data_rows], ignore_index=True)

    filtered_result.to_csv(output_path, index=False)
    print(f"[*] Filtered output shape: {filtered_result.shape}  (rows x cols)")
    print(f"[✓] Saved: {output_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 module_matrix_builder.py <input.csv> <output.csv>")
        sys.exit(1)
    inp = sys.argv[1]
    out = sys.argv[2]
    build_module_matrix(inp, out)
