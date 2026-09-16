import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Inventory CSV (the main server list)
DEFAULT_INVENTORY = str(BASE_DIR.parent / "CT1_all_servers_2026_9_3_14_4_54.csv")

# Generated data files
# Per-server module dumps: data/servers/<ip>.txt (one module per line)
SERVERS_DIR = DATA_DIR / "servers"
SERVERS_DIR.mkdir(exist_ok=True)
SERVERS_DIR = str(SERVERS_DIR)
# Lightweight index: ip, fetched_at, module_count — for coverage/lookup without
# touching the 27K per-server files.
FETCH_INDEX_CSV = str(DATA_DIR / "fetch_index.csv")
IP_STATUS_CSV = str(DATA_DIR / "ip_status.csv")

# SSH credentials — override via environment variables
SSH_USER = os.environ.get("MODTOOL_SSH_USER", "patcher")
SSH_PASSWORDS = [
    os.environ.get("MODTOOL_SSH_PASS1", "T#YOt#gRHHPI90@%_402"),
    os.environ.get("MODTOOL_SSH_PASS2", "0Jejve7YVN7"),
]
SSH_PORT = int(os.environ.get("MODTOOL_SSH_PORT", "22"))
SSH_CONNECT_TIMEOUT = int(os.environ.get("MODTOOL_SSH_CONNECT_TIMEOUT", "3"))
SSH_CMD_TIMEOUT = int(os.environ.get("MODTOOL_SSH_CMD_TIMEOUT", "5"))
DEFAULT_WORKERS = int(os.environ.get("MODTOOL_WORKERS", "20"))

# Inventory CSV column names (exact header strings)
COL_CAGE = "Cage"
COL_RACK = "Rack"
COL_LABEL = "Label"
COL_SERVER_IP = "Server IP"
COL_HOSTNAME = "HostName"
COL_SERVER_TYPE = "Server Type"
COL_SERVER_MODEL = "Server Model"
COL_ZSERVICE = "ZService"
COL_COMPONENT = "Component"
COL_GROUP = "Group"
COL_OS = "OS"
COL_RAM = "RAM (GB)"
COL_MEM_ENC = "Memory Encryption"
COL_DISK_ENC = "Disk Encryption"
COL_ROLE = "Role"
COL_LB_TYPE = "LB Type"
COL_PO = "PO Number"
COL_VLAN = "VLAN"
COL_CPU = "CPU(s)"
COL_DRIVE = "Drive Type"

# Server type values (as they appear in the inventory CSV)
ST_KVM = "KVM"
ST_VM = "VM"
ST_CN = "CN"
ST_PHYSICAL = "PHYSICAL_SERVER"
ST_CONTAINER_HOST = "CONTAINER_HOST"
ALL_SERVER_TYPES = [ST_KVM, ST_VM, ST_CN, ST_PHYSICAL, ST_CONTAINER_HOST]

SERVER_TYPE_LABELS = {
    ST_KVM: "KVM Host",
    ST_VM: "Virtual Machine",
    ST_CN: "Container",
    ST_PHYSICAL: "Physical Server",
    ST_CONTAINER_HOST: "Container Host",
}

# Failure reasons for IP status tracking
REASON_UNREACHABLE = "unreachable"
REASON_TIMEOUT = "timeout"
REASON_PASSWORD_EXPIRED = "password_expired"
REASON_PROXY_ERROR = "proxy_error"
REASON_AUTH_FAILED = "auth_failed"
ALL_REASONS = [
    REASON_UNREACHABLE,
    REASON_TIMEOUT,
    REASON_PASSWORD_EXPIRED,
    REASON_PROXY_ERROR,
    REASON_AUTH_FAILED,
]

# OS families that support lsmod (excludes FreeBSD, Windows, etc.)
SUPPORTED_OS_PREFIXES = ("Debian", "Ubuntu", "Rocky", "AlmaLinux", "Fedora", "RHEL")

# OS families to skip under the default 'linux' fetch filter (no lsmod, EOL, or
# otherwise out of scope for this fleet).
EXCLUDED_OS_PREFIXES = ("FreeBSD", "CentOS")

# Placeholder for missing/unassigned values in the inventory
MISSING_VALUE = "-"
