"""Every configuration key a server reads must exist in its example file.

Setup instructions drift out of date silently: someone adds `config["region"]` to
the code, forgets the example, and the next person to clone the repo gets a
KeyError instead of a running server. This test makes that drift fail the build.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SERVERS = sorted(p for p in (REPO / "servers").iterdir() if p.is_dir())


def config_keys_read_by(source: str) -> set[str]:
    """Return every key the module reads from its config mapping.

    Covers both `config["key"]` subscripts and `config.get("key")` calls on any
    identifier whose name contains "config".
    """
    tree = ast.parse(source)
    keys: set[str] = set()

    def is_config_name(node: ast.AST) -> bool:
        return isinstance(node, ast.Name) and "config" in node.id.lower()

    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and is_config_name(node.value):
            index = node.slice
            if isinstance(index, ast.Constant) and isinstance(index.value, str):
                keys.add(index.value)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and is_config_name(node.func.value)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
    return keys


@pytest.mark.parametrize("server", SERVERS, ids=lambda p: p.name)
def test_example_config_covers_every_key(server: Path) -> None:
    source = (server / "server.py").read_text(encoding="utf-8")
    example_path = server / "config.example.json"

    assert example_path.exists(), (
        f"{server.name} has no config.example.json. Anyone cloning this repo "
        "would have to read the source to find out what it needs."
    )

    example = json.loads(example_path.read_text(encoding="utf-8"))
    missing = config_keys_read_by(source) - set(example)

    assert not missing, (
        f"{server.name}/server.py reads {sorted(missing)} from its config, but "
        f"config.example.json does not document {'it' if len(missing) == 1 else 'them'}."
    )


@pytest.mark.parametrize("server", SERVERS, ids=lambda p: p.name)
def test_example_config_holds_no_real_value(server: Path) -> None:
    """The example must be a template, never a copy of a working config."""
    example = json.loads((server / "config.example.json").read_text(encoding="utf-8"))
    placeholder = re.compile(r"(?i)example|change-me|your[-_ ]|\.invalid|203\.0\.113\.")

    for key, value in example.items():
        if not isinstance(value, str):
            continue
        assert placeholder.search(value), (
            f"{server.name}/config.example.json sets {key!r} to a value that does "
            "not look like a placeholder. Example configs must never carry a real one."
        )


@pytest.mark.parametrize("server", SERVERS, ids=lambda p: p.name)
def test_server_reads_config_from_its_own_directory(server: Path) -> None:
    """Each server resolves config next to itself, so several can run side by side."""
    source = (server / "server.py").read_text(encoding="utf-8")
    assert "Path(__file__).parent" in source, (
        f"{server.name}/server.py should resolve its config relative to the module "
        "file, not to the working directory."
    )
