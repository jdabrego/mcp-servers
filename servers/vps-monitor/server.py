"""VPS Monitor MCP Server — SSH bridge to a remote Linux host running Docker Compose."""

import asyncio
import json
import logging
import shlex
from pathlib import Path

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vps-monitor-mcp")

CONFIG_PATH = Path(__file__).parent / "config.json"

# Load config
_config = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
SSH_KEY = _config["ssh_key"]
SSH_HOST = _config["host"]
SSH_USER = _config["user"]
COMPOSE_PATHS = _config["docker_compose_paths"]

from validation import (
    InvalidArgument,
    SERVICE_RE,
    valid_lines,
    valid_service,
    valid_since,
)

mcp = FastMCP("vps-monitor", instructions="Tools for monitoring a remote Linux host running Docker Compose services over SSH.")


async def _ssh(command: str, timeout: int = 15) -> str:
    """Run a command on the remote host over SSH. Returns stdout or a readable error.

    Callers must validate and quote every value they interpolate; this function
    does not inspect the command it is given.
    """
    ssh_cmd = [
        "ssh", "-i", str(Path(SSH_KEY).expanduser()),
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10",
        f"{SSH_USER}@{SSH_HOST}",
        command
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *ssh_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode("utf-8", errors="replace").strip()
        errors = stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0 and not output:
            return f"ERROR (exit {proc.returncode}): {errors or 'Unknown error'}"
        return output + (f"\n[stderr: {errors}]" if errors and "Warning" not in errors else "")
    except asyncio.TimeoutError:
        return f"TIMEOUT: Command did not complete within {timeout}s"
    except FileNotFoundError:
        return "ERROR: SSH binary not found"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@mcp.tool()
async def vps_service_status(service: str = "all") -> str:
    """Check Docker container status on the VPS. Pass 'all' for all containers or a specific service name."""
    cmd = "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
    result = await _ssh(cmd)
    if service != "all" and not SERVICE_RE.match(service):
        return f"REFUSED: {service!r} is not a valid container name."
    if service != "all" and result and "ERROR" not in result:
        lines = result.split("\n")
        header = lines[0] if lines else ""
        filtered = [l for l in lines[1:] if service.lower() in l.lower()]
        return f"{header}\n" + "\n".join(filtered) if filtered else f"No container matching '{service}' found.\n\nAll containers:\n{result}"
    return result


@mcp.tool()
async def vps_read_logs(service: str, lines: int = 50, since: str = "1h") -> str:
    """Read Docker container logs from the VPS. Specify service name, number of lines, and time period."""
    try:
        svc, window, tail = valid_service(service), valid_since(since), valid_lines(lines)
    except InvalidArgument as e:
        return f"REFUSED: {e}"
    cmd = f"docker logs --tail={tail} --since={window} {svc} 2>&1"
    return await _ssh(cmd, timeout=20)


@mcp.tool()
async def vps_disk_usage() -> str:
    """Check disk usage on the VPS — root filesystem plus Docker and project directories."""
    cmd = "echo '=== FILESYSTEM ===' && df -h / | tail -1 && echo '' && echo '=== PROJECTS ===' && du -sh " + " ".join(COMPOSE_PATHS.values()) + " 2>/dev/null && echo '' && echo '=== DOCKER ===' && docker system df 2>/dev/null"
    return await _ssh(cmd)


@mcp.tool()
async def vps_resource_usage() -> str:
    """Check CPU, memory, and per-container resource usage on the VPS."""
    cmd = "echo '=== MEMORY ===' && free -h | head -2 && echo '' && echo '=== UPTIME ===' && uptime && echo '' && echo '=== CONTAINERS ===' && docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}' 2>/dev/null"
    return await _ssh(cmd, timeout=20)


@mcp.tool()
async def vps_error_count(service: str = "all", since: str = "12h") -> str:
    """Count errors in Docker container logs. Returns error count per service."""
    try:
        window = valid_since(since)
        svc = None if service == "all" else valid_service(service)
    except InvalidArgument as e:
        return f"REFUSED: {e}"

    if svc is None:
        cmd = (
            "for svc in $(docker ps --format '{{.Names}}'); do "
            f"COUNT=$(docker logs \"$svc\" --since {window} 2>&1 "
            "| grep -ciE 'error|exception|traceback' 2>/dev/null || echo 0); "
            'echo "$svc: $COUNT errors"; done'
        )
    else:
        cmd = f"docker logs {svc} --since {window} 2>&1 | grep -ciE 'error|exception|traceback'"
    return await _ssh(cmd, timeout=20)


@mcp.tool()
async def vps_restart_service(service: str, confirm: str = "") -> str:
    """Restart a Docker service on the VPS. REQUIRES confirm='CONFIRM' as safety gate."""
    try:
        svc = valid_service(service)
    except InvalidArgument as e:
        return f"REFUSED: {e}"

    if confirm != "CONFIRM":
        return f"SAFETY GATE: To restart '{service}', call with confirm='CONFIRM'. This will cause brief downtime for the service."

    # Determine which compose project the service belongs to
    compose_path = None
    for project, path in COMPOSE_PATHS.items():
        if project in service.lower():
            compose_path = path
            break

    if compose_path:
        cmd = f"cd {shlex.quote(compose_path)} && docker compose restart {svc}"
    else:
        cmd = f"docker restart {svc}"

    result = await _ssh(cmd, timeout=30)
    # Verify it came back up
    verify = await _ssh(
        "sleep 3 && docker ps --format '{{.Names}}: {{.Status}}' | grep -- " + svc,
        timeout=15,
    )
    return f"Restart result: {result}\n\nVerification: {verify}"


if __name__ == "__main__":
    mcp.run()
