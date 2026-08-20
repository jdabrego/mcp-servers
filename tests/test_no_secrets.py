"""Guardian test: fail the build if a secret ever reaches this repository.

This is the same discipline the servers themselves follow — credentials live in a
`config.json` that is never committed, and nothing else is allowed to carry one.
The test scans every tracked file, so it also catches a secret pasted into a README
or an example file, not only into code.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Documentation-only address ranges, safe to appear in examples.
# TEST-NET-1/2/3 (RFC 5737) plus loopback and unspecified.
ALLOWED_IPS = {"127.0.0.1", "0.0.0.0", "255.255.255.255"}
ALLOWED_IP_PREFIXES = ("192.0.2.", "198.51.100.", "203.0.113.")

FORBIDDEN = [
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("notion token", re.compile(r"\bntn_[A-Za-z0-9]{20,}")),
    ("openai/anthropic key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("json web token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.")),
    (
        "assigned literal credential",
        re.compile(
            r"""(?ix)
            \b(password|passwd|secret|api_key|apikey|token)\b
            \s*[:=]\s*
            ["'](?!change-me|your[-_])[^"']{6,}["']
            """
        ),
    ),
]

IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def tracked_files() -> list[Path]:
    """Files git knows about. Empty when run outside a checkout."""
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [REPO / line for line in out.stdout.splitlines() if line]


def readable_files() -> list[Path]:
    files = tracked_files() or [
        p for p in REPO.rglob("*") if p.is_file() and ".git" not in p.parts
    ]
    keep = {".py", ".json", ".md", ".yml", ".yaml", ".txt", ".toml", ".cfg", ".sh"}
    return [p for p in files if p.suffix in keep and p.name != "test_no_secrets.py"]


@pytest.mark.parametrize("path", readable_files(), ids=lambda p: p.name)
def test_file_carries_no_secret(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    for label, pattern in FORBIDDEN:
        match = pattern.search(text)
        assert match is None, (
            f"{path.relative_to(REPO)} looks like it contains a {label} "
            f"at offset {match.start() if match else 0}. "
            "Secrets belong in config.json, which is gitignored."
        )


@pytest.mark.parametrize("path", readable_files(), ids=lambda p: p.name)
def test_file_carries_no_real_ip(path: Path) -> None:
    """Real infrastructure addresses must never be committed.

    Examples must use the RFC 5737 documentation ranges instead.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    for found in IP_RE.findall(text):
        if found in ALLOWED_IPS or found.startswith(ALLOWED_IP_PREFIXES):
            continue
        # Version strings like 10.6.1 are not addresses; require four octets
        # that each parse as a byte and are not part of a longer version chain.
        octets = found.split(".")
        if any(not o.isdigit() or int(o) > 255 for o in octets):
            continue
        raise AssertionError(
            f"{path.relative_to(REPO)} contains what looks like a real IP address "
            f"({found}). Use a documentation range (192.0.2.x, 198.51.100.x, "
            "203.0.113.x) in examples, and read the real host from config.json."
        )


def test_config_json_is_ignored() -> None:
    """The gitignore must keep every real config out, not just the top-level one."""
    ignored = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "config.json" in ignored.split(), (
        "config.json must be listed in .gitignore with no path prefix so it is "
        "ignored in every server directory."
    )


def test_no_config_json_is_tracked() -> None:
    tracked = {p.name for p in tracked_files()}
    assert "config.json" not in tracked, (
        "A real config.json is tracked by git. Remove it from the index "
        "and rotate every credential it contained."
    )
