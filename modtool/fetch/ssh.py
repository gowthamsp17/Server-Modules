"""SSH helper: port check + sshpass-based lsmod execution."""

import socket
import subprocess
import sys


LSMOD_CMD = 'lsmod | awk "NR > 1 {print \\$1}"'


def is_port_open(ip: str, port: int = 22, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def _try_sshpass(ip: str, user: str, password: str,
                 command: str, connect_timeout: int, cmd_timeout: int):
    """Run command over SSH with one password. Returns (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            [
                "sshpass", "-p", password,
                "ssh", "-n",
                "-o", "StrictHostKeyChecking=no",
                "-o", f"ConnectTimeout={connect_timeout}",
                "-o", "ConnectionAttempts=1",
                "-o", "BatchMode=no",
                "-o", "LogLevel=ERROR",
                f"{user}@{ip}",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=cmd_timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -124, "", "timeout"
    except FileNotFoundError:
        print("ERROR: sshpass not found. Install with: apt install sshpass", file=sys.stderr)
        raise


def run_lsmod(ip: str, user: str, passwords: list,
              connect_timeout: int = 3, cmd_timeout: int = 5) -> dict:
    """
    SSH into ip, run lsmod, return result dict:
      success  : bool
      modules  : list[str]
      reason   : 'ok' | 'unreachable' | 'timeout' | 'password_expired'
                  | 'proxy_error' | 'auth_failed'
    """
    if not is_port_open(ip, 22, timeout=2.0):
        return {"success": False, "modules": [], "reason": "unreachable"}

    for password in passwords:
        rc, stdout, stderr = _try_sshpass(
            ip, user, password, LSMOD_CMD, connect_timeout, cmd_timeout
        )
        err_lower = stderr.lower()

        if "password has expired" in err_lower or "current password:" in err_lower:
            return {"success": False, "modules": [], "reason": "password_expired"}

        if "proxy error" in err_lower or "nc: " in err_lower:
            return {"success": False, "modules": [], "reason": "proxy_error"}

        if rc == -124 or "timeout" in err_lower:
            return {"success": False, "modules": [], "reason": "timeout"}

        if rc == 0:
            modules = [m.strip() for m in stdout.splitlines() if m.strip()]
            return {"success": True, "modules": modules, "reason": "ok"}

    return {"success": False, "modules": [], "reason": "auth_failed"}
