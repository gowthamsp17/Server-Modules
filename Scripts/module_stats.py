#!/usr/bin/env python3
"""
module_stats.py

Given a kernel module name, report where it is loaded across the CT1 fleet.

Stats produced
--------------
1. Reach        : how many IPs have the module loaded (out of the IPs that
                  were actually surveyed successfully).
2. ZService /   : counts of the loaded IPs broken down by ZService,
   Component /    Component and Group, taken from CT1_all_servers.csv.
   Group
3. Kernel       : among the loaded IPs, how many run each tracked kernel
                  version (Debian only), taken from CT1_VMs.csv and
                  CT1_PS_KVM_CH.csv.
4. Server type  : among the loaded IPs, how many are VM / Physical Server /
                  KVM Host / Container Host / Container, taken from
                  CT1_VMs.csv, CT1_PS_KVM_CH.csv and CT1_CNs.csv.

Because the IP list is large, use --export-ips to write the full per-IP
breakdown to a CSV instead of reading it off the terminal.

Usage
-----
    python3 module_stats.py <module_name>
    python3 module_stats.py nf_conntrack --export-ips /tmp/nf_conntrack_ips.csv
    python3 module_stats.py xt_CT --export-ips ips.csv --export-summary summary.csv
    python3 module_stats.py --list-modules conntrack

Run with -h for the full option list.
"""

import argparse
import csv
import difflib
import os
import re
import socket
import struct
import sys
from collections import Counter, OrderedDict

# Kernel versions we track by default (Debian hosts only).
DEFAULT_KERNEL_VERSIONS = [
    "5.10.106",
    "5.10.191",
    "5.10.226",
    "6.1.112",
    "6.1.123",
    "6.12.74",
    "6.12.90",
]

# Server-type labels, in the order they are reported.
TYPE_VM = "VM"
TYPE_PS = "Physical Server"
TYPE_CH = "Container Host"
TYPE_KVM = "KVM Host"
TYPE_CN = "Container"
TYPE_UNKNOWN = "Unknown"

SERVER_TYPE_ORDER = [TYPE_VM, TYPE_PS, TYPE_CH, TYPE_KVM, TYPE_CN, TYPE_UNKNOWN]

# Raw "Server Type" values in CT1_PS_KVM_CH.csv -> report label.
PS_TYPE_MAP = {
    "PHYSICAL_SERVER": TYPE_PS,
    "KVM": TYPE_KVM,
    "CONTAINER_HOST": TYPE_CH,
}

# Cell values in the module matrix.
CELL_LOADED = "1"
CELL_UNREACHABLE = "-"

# Only these mean "unset" in this dataset. "NA", "Unknown" and "None" are
# left alone on purpose: they are real, distinct values in these sheets
# (Group=NA, Memory Encryption=Unknown, LB Type=None) and folding them into
# blanks would merge categories that the source keeps apart.
EMPTY_MARKERS = {"", "-"}

KERNEL_BASE_RE = re.compile(r"^(\d+\.\d+\.\d+)")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def ip_sort_key(ip):
    """Sort IPv4 strings numerically; anything unparseable sorts last."""
    try:
        return (0, struct.unpack("!I", socket.inet_aton(ip))[0])
    except (OSError, TypeError):
        return (1, ip)


def clean(value):
    """Normalise a CSV cell to a plain string ('' for missing/placeholder)."""
    if value is None:
        return ""
    value = str(value).strip()
    return "" if value.lower() in EMPTY_MARKERS else value


def kernel_base(kernel):
    """'6.1.123-kexec' -> '6.1.123'. Returns '' when there is no X.Y.Z prefix."""
    match = KERNEL_BASE_RE.match(clean(kernel))
    return match.group(1) if match else ""


def os_family(os_string):
    """'Debian 12.9' -> 'Debian'."""
    os_string = clean(os_string)
    return os_string.split()[0] if os_string else ""


def is_debian(os_string):
    return os_family(os_string).lower() == "debian"


def split_groups(group_cell):
    """Groups may be a comma-separated list; return them individually."""
    group_cell = clean(group_cell)
    if not group_cell:
        return []
    return [g for g in (part.strip() for part in group_cell.split(",")) if g]


def read_csv_rows(path):
    """Yield dict rows from a CSV, erroring clearly when the file is missing."""
    if not os.path.isfile(path):
        sys.exit("[!] Required file not found: %s" % path)
    with open(path, newline="", encoding="utf-8", errors="replace") as handle:
        for row in csv.DictReader(handle):
            yield row


# --------------------------------------------------------------------------
# data loading
# --------------------------------------------------------------------------

class Paths(object):
    """Resolved locations of every input file."""

    def __init__(self, base_dir, matrix=None):
        self.base_dir = base_dir
        data_dir = os.path.join(base_dir, "data")
        self.matrix = matrix or os.path.join(base_dir, "CT1_Module_Matrix.csv")
        self.all_servers = os.path.join(base_dir, "CT1_all_servers.csv")
        self.vms = os.path.join(data_dir, "CT1_VMs.csv")
        self.ps_kvm_ch = os.path.join(data_dir, "CT1_PS_KVM_CH.csv")
        self.cns = os.path.join(data_dir, "CT1_CNs.csv")


def load_matrix_modules(matrix_path):
    """Return the list of module column names in the matrix."""
    if not os.path.isfile(matrix_path):
        sys.exit("[!] Module matrix not found: %s\n"
                 "    Build it first with module_matrix_builder.py, or pass "
                 "--matrix." % matrix_path)
    with open(matrix_path, newline="", encoding="utf-8", errors="replace") as handle:
        header = next(csv.reader(handle))
    meta = {"IP", "No of Modules", "Node Not Reachable",
            "Authentication Failed", "Command Not Found"}
    return header, [col for col in header if col not in meta]


def resolve_module_name(requested, modules):
    """Match the requested module name exactly, then case-insensitively."""
    if requested in modules:
        return requested

    lowered = {m.lower(): m for m in modules}
    if requested.lower() in lowered:
        actual = lowered[requested.lower()]
        print("[*] Interpreting '%s' as '%s' (module names are case-sensitive)."
              % (requested, actual))
        return actual

    suggestions = difflib.get_close_matches(requested, modules, n=8, cutoff=0.6)
    substring = [m for m in modules if requested.lower() in m.lower()][:8]
    message = ["[!] Module '%s' is not present in the module matrix." % requested]
    for label, names in (("Did you mean", suggestions), ("Contains that text", substring)):
        if names:
            message.append("    %s: %s" % (label, ", ".join(names)))
    message.append("    Use --list-modules [pattern] to browse all %d modules."
                   % len(modules))
    sys.exit("\n".join(message))


def scan_matrix(matrix_path, header, module):
    """Stream the matrix and collect per-module reach plus survey coverage."""
    ip_index = header.index("IP")
    module_index = header.index(module)

    loaded_ips = []
    surveyed = 0
    unreachable = 0
    not_loaded = 0
    total_rows = 0
    failure_reasons = Counter()

    reason_indexes = OrderedDict()
    for label in ("Node Not Reachable", "Authentication Failed", "Command Not Found"):
        if label in header:
            reason_indexes[label] = header.index(label)

    with open(matrix_path, newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.reader(handle)
        next(reader)  # column headers
        for row in reader:
            if not row or len(row) <= module_index:
                continue
            ip = row[ip_index].strip()
            # The builder writes a "Modules Count" summary row under the header.
            if ip == "Modules Count" or not ip or ip == "-":
                continue

            total_rows += 1
            cell = row[module_index].strip()
            if cell == CELL_UNREACHABLE:
                unreachable += 1
                matched_reason = False
                for label, index in reason_indexes.items():
                    if len(row) > index and row[index].strip() == "1":
                        failure_reasons[label] += 1
                        matched_reason = True
                if not matched_reason:
                    failure_reasons["Unspecified"] += 1
                continue

            surveyed += 1
            if cell == CELL_LOADED:
                loaded_ips.append(ip)
            else:
                not_loaded += 1

    return {
        "loaded_ips": loaded_ips,
        "surveyed": surveyed,
        "unreachable": unreachable,
        "not_loaded": not_loaded,
        "total_rows": total_rows,
        "failure_reasons": failure_reasons,
    }


def load_all_servers(path):
    """IP -> service/placement attributes from CT1_all_servers.csv."""
    servers = {}
    for row in read_csv_rows(path):
        ip = clean(row.get("Server IP"))
        if not ip:
            continue
        servers[ip] = {
            "zservice": clean(row.get("ZService")),
            "component": clean(row.get("Component")),
            "group": clean(row.get("Group")),
            "os": clean(row.get("OS")),
            "server_type": clean(row.get("Server Type")),
            "label": clean(row.get("Label")),
            "cage": clean(row.get("Cage")),
            "rack": clean(row.get("Rack")),
            "vlan": clean(row.get("VLAN")),
            "hostname": clean(row.get("HostName")),
        }
    return servers


def load_inventory(paths):
    """IP -> {type, source, kernel, os, host, label} from the three inventories.

    Server type comes from the file the IP was found in: CT1_VMs.csv means VM,
    CT1_CNs.csv means Container, and CT1_PS_KVM_CH.csv carries its own
    Server Type column (PHYSICAL_SERVER / KVM / CONTAINER_HOST).
    """
    inventory = {}

    for row in read_csv_rows(paths.vms):
        ip = clean(row.get("Virtual Machine IP"))
        if not ip:
            continue
        inventory[ip] = {
            "type": TYPE_VM,
            "source": os.path.basename(paths.vms),
            "kernel": clean(row.get("Kernel Version")),
            "os": clean(row.get("OS")),
            "host": clean(row.get("KVM Host")),
            "label": clean(row.get("Label")),
        }

    for row in read_csv_rows(paths.ps_kvm_ch):
        ip = clean(row.get("Physical IP"))
        if not ip:
            continue
        raw_type = clean(row.get("Server Type")).upper()
        inventory[ip] = {
            "type": PS_TYPE_MAP.get(raw_type, TYPE_UNKNOWN),
            "source": os.path.basename(paths.ps_kvm_ch),
            "kernel": clean(row.get("Kernel Version")),
            "os": clean(row.get("OS")),
            "host": "",
            "label": clean(row.get("Label")),
        }

    # Containers have no kernel of their own - they share the host kernel.
    for row in read_csv_rows(paths.cns):
        ip = clean(row.get("Container IP"))
        if not ip:
            continue
        inventory[ip] = {
            "type": TYPE_CN,
            "source": os.path.basename(paths.cns),
            "kernel": "",
            "os": clean(row.get("OS")),
            "host": clean(row.get("Container Host")),
            "label": clean(row.get("Label")),
        }

    return inventory


# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------

def build_records(loaded_ips, servers, inventory, kernel_versions, strict_kernel):
    """Join each loaded IP against the inventories into one flat record."""
    tracked = set(kernel_versions)
    records = []

    for ip in sorted(loaded_ips, key=ip_sort_key):
        server = servers.get(ip, {})
        inv = inventory.get(ip, {})

        kernel = inv.get("kernel", "")
        base = kernel if strict_kernel else kernel_base(kernel)
        # Kernel stats are Debian-only, and containers report no kernel.
        os_string = inv.get("os") or server.get("os", "")
        kernel_tracked = bool(base) and base in tracked and is_debian(os_string)

        server_type = inv.get("type")
        if not server_type or server_type == TYPE_UNKNOWN:
            # Fall back to the fleet-wide sheet when the inventory row is blank.
            fallback = server.get("server_type", "").upper()
            server_type = PS_TYPE_MAP.get(
                fallback,
                {"VM": TYPE_VM, "CN": TYPE_CN}.get(fallback, TYPE_UNKNOWN),
            )

        records.append({
            "ip": ip,
            "server_type": server_type,
            "source": inv.get("source", ""),
            "label": server.get("label") or inv.get("label", ""),
            "host": inv.get("host", ""),
            "zservice": server.get("zservice", ""),
            "component": server.get("component", ""),
            "group": server.get("group", ""),
            "os": os_string,
            "os_family": os_family(os_string),
            "kernel": kernel,
            "kernel_base": base,
            "kernel_tracked": kernel_tracked,
            "cage": server.get("cage", ""),
            "rack": server.get("rack", ""),
            "vlan": server.get("vlan", ""),
            "in_all_servers": ip in servers,
        })

    return records


def summarise(records, kernel_versions):
    """Roll the per-IP records up into the reported breakdowns."""
    zservice = Counter()
    component = Counter()
    group = Counter()
    server_type = Counter()
    kernel = Counter()

    multi_group_ips = 0
    kernel_other = Counter()
    kernel_non_debian = 0
    kernel_missing = 0

    tracked = set(kernel_versions)

    for record in records:
        zservice[record["zservice"] or "(unset)"] += 1
        component[record["component"] or "(unset)"] += 1

        groups = split_groups(record["group"])
        if not groups:
            group["(unset)"] += 1
        else:
            if len(groups) > 1:
                multi_group_ips += 1
            for name in groups:
                group[name] += 1

        server_type[record["server_type"]] += 1

        base = record["kernel_base"]
        if not base:
            kernel_missing += 1
        elif not is_debian(record["os"]):
            kernel_non_debian += 1
        elif base in tracked:
            kernel[base] += 1
        else:
            kernel_other[base] += 1

    return {
        "zservice": zservice,
        "component": component,
        "group": group,
        "server_type": server_type,
        "kernel": kernel,
        "kernel_other": kernel_other,
        "kernel_non_debian": kernel_non_debian,
        "kernel_missing": kernel_missing,
        "multi_group_ips": multi_group_ips,
    }


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def percent(part, whole):
    return "%.2f%%" % (100.0 * part / whole) if whole else "-"


def print_heading(title):
    print("")
    print(title)
    print("-" * max(len(title), 58))


def print_counter(counter, total, top, unset_last=True):
    """Print 'name  count  percent' rows, biggest first."""
    if not counter:
        print("  (no data)")
        return

    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    if unset_last:
        items = ([kv for kv in items if kv[0] != "(unset)"]
                 + [kv for kv in items if kv[0] == "(unset)"])

    shown = items if top <= 0 else items[:top]
    width = max(len(name) for name, _ in shown)
    width = min(max(width, 12), 48)

    for name, count in shown:
        display = name if len(name) <= width else name[:width - 1] + "…"
        print("  %-*s  %7d  %8s" % (width, display, count, percent(count, total)))

    hidden = len(items) - len(shown)
    if hidden > 0:
        hidden_total = sum(count for _, count in items[len(shown):])
        print("  %-*s  %7d  %8s" % (width, "... %d more" % hidden,
                                    hidden_total, percent(hidden_total, total)))


def print_report(module, scan, records, summary, kernel_versions, top, strict_kernel):
    loaded = len(records)
    surveyed = scan["surveyed"]

    print("=" * 58)
    print("Module: %s" % module)
    print("=" * 58)

    print_heading("1. Reach")
    print("  IPs in module matrix          : %7d" % scan["total_rows"])
    print("  IPs successfully surveyed      : %7d" % surveyed)
    print("  IPs with module LOADED         : %7d  (%s of surveyed)"
          % (loaded, percent(loaded, surveyed)))
    print("  IPs without the module         : %7d  (%s of surveyed)"
          % (scan["not_loaded"], percent(scan["not_loaded"], surveyed)))
    print("  IPs not surveyed (no lsmod)    : %7d" % scan["unreachable"])
    for reason, count in scan["failure_reasons"].most_common():
        print("      - %-26s : %7d" % (reason, count))

    if not loaded:
        print("")
        print("Module is not loaded on any surveyed IP - no breakdowns to report.")
        return

    print_heading("2a. ZService (of %d loaded IPs)" % loaded)
    print("  %d distinct ZServices" % len(summary["zservice"]))
    print_counter(summary["zservice"], loaded, top)

    print_heading("2b. Component (of %d loaded IPs)" % loaded)
    print("  %d distinct Components" % len(summary["component"]))
    print_counter(summary["component"], loaded, top)

    print_heading("2c. Group (of %d loaded IPs)" % loaded)
    print("  %d distinct Groups" % len(summary["group"]))
    if summary["multi_group_ips"]:
        print("  note: %d IPs belong to more than one Group, so these counts "
              "sum above %d." % (summary["multi_group_ips"], loaded))
    print_counter(summary["group"], loaded, top)

    match_mode = "exact match" if strict_kernel else "matched on the X.Y.Z prefix"
    print_heading("3. Kernel version - Debian only (%s)" % match_mode)
    tracked_total = sum(summary["kernel"].values())
    for version in kernel_versions:
        count = summary["kernel"].get(version, 0)
        print("  %-14s  %7d  %8s" % (version, count, percent(count, loaded)))
    print("  %-14s  %7d  %8s" % ("tracked total", tracked_total,
                                 percent(tracked_total, loaded)))
    other_total = sum(summary["kernel_other"].values())
    print("")
    print("  Other Debian kernels           : %7d  (%d distinct)"
          % (other_total, len(summary["kernel_other"])))
    print("  Non-Debian OS                  : %7d" % summary["kernel_non_debian"])
    print("  No kernel recorded             : %7d  (containers / not in inventory)"
          % summary["kernel_missing"])
    if other_total and top != 0:
        print("  Top other Debian kernels:")
        print_counter(summary["kernel_other"], loaded, min(top, 10) if top > 0 else 10)

    print_heading("4. Server type (of %d loaded IPs)" % loaded)
    for label in SERVER_TYPE_ORDER:
        count = summary["server_type"].get(label, 0)
        if count or label != TYPE_UNKNOWN:
            print("  %-16s  %7d  %8s" % (label, count, percent(count, loaded)))
    print("  %-16s  %7d" % ("total", sum(summary["server_type"].values())))


# --------------------------------------------------------------------------
# exports
# --------------------------------------------------------------------------

IP_EXPORT_COLUMNS = [
    ("IP", "ip"),
    ("Server Type", "server_type"),
    ("ZService", "zservice"),
    ("Component", "component"),
    ("Group", "group"),
    ("OS", "os"),
    ("OS Family", "os_family"),
    ("Kernel Version", "kernel"),
    ("Kernel Base", "kernel_base"),
    ("Label", "label"),
    ("Parent Host", "host"),
    ("Cage", "cage"),
    ("Rack", "rack"),
    ("VLAN", "vlan"),
    ("Inventory Source", "source"),
]


def export_ips(path, module, records, kernel_versions, strict_kernel):
    """Write one row per IP that has the module loaded."""
    tracked_label = ",".join(kernel_versions)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Module"] + [name for name, _ in IP_EXPORT_COLUMNS]
                        + ["Tracked Kernel", "In All Servers"])
        for record in records:
            writer.writerow(
                [module]
                + [record[key] for _, key in IP_EXPORT_COLUMNS]
                + ["Yes" if record["kernel_tracked"] else "No",
                   "Yes" if record["in_all_servers"] else "No"]
            )
    print("")
    print("[✓] IP list exported: %s" % path)
    print("    %d rows  |  tracked kernels: %s  |  matching: %s"
          % (len(records), tracked_label,
             "exact" if strict_kernel else "X.Y.Z prefix"))


def export_summary(path, module, scan, records, summary, kernel_versions):
    """Write every breakdown as a long-format CSV (one row per category)."""
    loaded = len(records)

    def rows():
        yield ("Reach", "IPs in module matrix", scan["total_rows"], "")
        yield ("Reach", "IPs surveyed", scan["surveyed"], "")
        yield ("Reach", "IPs with module loaded", loaded,
               percent(loaded, scan["surveyed"]))
        yield ("Reach", "IPs without module", scan["not_loaded"],
               percent(scan["not_loaded"], scan["surveyed"]))
        yield ("Reach", "IPs not surveyed", scan["unreachable"], "")
        for reason, count in scan["failure_reasons"].most_common():
            yield ("Not surveyed reason", reason, count, "")

        for dimension in ("zservice", "component", "group"):
            title = dimension.capitalize() if dimension != "zservice" else "ZService"
            for name, count in sorted(summary[dimension].items(),
                                      key=lambda kv: (-kv[1], kv[0])):
                yield (title, name, count, percent(count, loaded))

        for version in kernel_versions:
            count = summary["kernel"].get(version, 0)
            yield ("Kernel (tracked, Debian)", version, count,
                   percent(count, loaded))
        for name, count in sorted(summary["kernel_other"].items(),
                                  key=lambda kv: (-kv[1], kv[0])):
            yield ("Kernel (other, Debian)", name, count, percent(count, loaded))
        yield ("Kernel (excluded)", "Non-Debian OS",
               summary["kernel_non_debian"], percent(summary["kernel_non_debian"], loaded))
        yield ("Kernel (excluded)", "No kernel recorded",
               summary["kernel_missing"], percent(summary["kernel_missing"], loaded))

        for label in SERVER_TYPE_ORDER:
            count = summary["server_type"].get(label, 0)
            if count or label != TYPE_UNKNOWN:
                yield ("Server Type", label, count, percent(count, loaded))

    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Module", "Category", "Value", "IP Count",
                         "Percent of Loaded IPs"])
        for category, value, count, pct in rows():
            writer.writerow([module, category, value, count, pct])

    print("[✓] Summary exported: %s" % path)


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def default_base_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "CT1")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="module_stats.py",
        description="Report where a kernel module is loaded across the CT1 fleet.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  python3 module_stats.py nf_conntrack
  python3 module_stats.py nf_conntrack --export-ips nf_conntrack_ips.csv
  python3 module_stats.py overlay --top 0 --export-summary overlay_summary.csv
  python3 module_stats.py --list-modules conntrack
""",
    )
    parser.add_argument("module", nargs="?",
                        help="kernel module name (case-sensitive, e.g. nf_conntrack)")
    parser.add_argument("--export-ips", metavar="FILE",
                        help="write the full per-IP list to this CSV")
    parser.add_argument("--export-summary", metavar="FILE",
                        help="write all breakdown tables to this CSV")
    parser.add_argument("--top", type=int, default=15, metavar="N",
                        help="rows to show per breakdown on screen; 0 = all "
                             "(default: 15)")
    parser.add_argument("--kernel-versions", metavar="V",
                        help="comma-separated kernel versions to track "
                             "(default: %s)" % ",".join(DEFAULT_KERNEL_VERSIONS))
    parser.add_argument("--strict-kernel", action="store_true",
                        help="match kernel versions exactly instead of on the "
                             "X.Y.Z prefix (by default 6.1.123-kexec counts "
                             "under 6.1.123)")
    parser.add_argument("--base-dir", default=default_base_dir(), metavar="DIR",
                        help="directory holding CT1_all_servers.csv and data/ "
                             "(default: %(default)s)")
    parser.add_argument("--matrix", metavar="FILE",
                        help="module matrix CSV (default: <base-dir>/CT1_Module_Matrix.csv)")
    parser.add_argument("--list-modules", nargs="?", const="", metavar="PATTERN",
                        help="list module names (optionally filtered by substring) "
                             "and exit")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    paths = Paths(args.base_dir, args.matrix)
    header, modules = load_matrix_modules(paths.matrix)

    if args.list_modules is not None:
        pattern = args.list_modules.lower()
        matches = [m for m in modules if pattern in m.lower()]
        for name in matches:
            print(name)
        print("")
        print("%d of %d modules%s" % (len(matches), len(modules),
                                      " matching '%s'" % args.list_modules
                                      if pattern else ""))
        return 0

    if not args.module:
        sys.exit("[!] No module name given. Pass a module name, or use "
                 "--list-modules to browse them.")

    if args.kernel_versions:
        kernel_versions = [v.strip() for v in args.kernel_versions.split(",")
                           if v.strip()]
    else:
        kernel_versions = list(DEFAULT_KERNEL_VERSIONS)

    module = resolve_module_name(args.module, modules)

    scan = scan_matrix(paths.matrix, header, module)
    servers = load_all_servers(paths.all_servers)
    inventory = load_inventory(paths)

    records = build_records(scan["loaded_ips"], servers, inventory,
                            kernel_versions, args.strict_kernel)
    summary = summarise(records, kernel_versions)

    print_report(module, scan, records, summary, kernel_versions, args.top,
                 args.strict_kernel)

    if args.export_ips:
        export_ips(args.export_ips, module, records, kernel_versions,
                   args.strict_kernel)
    if args.export_summary:
        export_summary(args.export_summary, module, scan, records, summary,
                       kernel_versions)
    if not args.export_ips:
        print("")
        print("[i] Use --export-ips <file.csv> to get the full IP list.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
