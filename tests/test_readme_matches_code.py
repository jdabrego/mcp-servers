"""The README must describe the tools that actually exist.

A README goes stale the moment a tool is renamed or removed, and a stale README is
worse than none: it sends the reader looking for something that is not there. This
test reads the tool names out of the source with `ast` and compares them against the
names listed in the README, so documentation drift breaks the build.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"
SERVERS = sorted(p for p in (REPO / "servers").iterdir() if p.is_dir())


def tools_defined_in(source: str) -> set[str]:
    """Names of every function registered as an MCP tool."""
    tree = ast.parse(source)
    tools: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(target, ast.Attribute) and target.attr == "tool":
                tools.add(node.name)
    return tools


def names_in_readme() -> set[str]:
    text = README.read_text(encoding="utf-8")
    return set(re.findall(r"`([a-z][a-z0-9_]*_[a-z0-9_]+)`", text))


@pytest.mark.parametrize("server", SERVERS, ids=lambda p: p.name)
def test_every_tool_is_documented(server: Path) -> None:
    source = (server / "server.py").read_text(encoding="utf-8")
    undocumented = tools_defined_in(source) - names_in_readme()
    assert not undocumented, (
        f"{server.name} exposes {sorted(undocumented)}, which the README does not "
        "mention. Every tool a caller can reach has to be listed."
    )


def test_readme_documents_no_tool_that_was_removed() -> None:
    defined: set[str] = set()
    for server in SERVERS:
        defined |= tools_defined_in((server / "server.py").read_text(encoding="utf-8"))

    prefixes = tuple(sorted({name.split("_")[0] + "_" for name in defined}))
    claimed = {n for n in names_in_readme() if n.startswith(prefixes)}

    stale = claimed - defined
    assert not stale, (
        f"The README still lists {sorted(stale)}, which no server defines any more. "
        "Documentation that promises a tool that does not exist is worse than none."
    )


def test_readme_tool_count_is_accurate() -> None:
    """If the README advertises a number of tools, that number must be the real one."""
    text = README.read_text(encoding="utf-8")
    match = re.search(r"\*\*(\d+)\s+tools?\*\*", text)
    if match is None:
        pytest.skip("README does not advertise a tool count")

    real = sum(
        len(tools_defined_in((s / "server.py").read_text(encoding="utf-8")))
        for s in SERVERS
    )
    assert int(match.group(1)) == real, (
        f"The README says {match.group(1)} tools; the code defines {real}."
    )


@pytest.mark.parametrize("server", SERVERS, ids=lambda p: p.name)
def test_every_tool_has_a_docstring(server: Path) -> None:
    """An MCP tool's docstring is what the model reads to decide when to call it."""
    tree = ast.parse((server / "server.py").read_text(encoding="utf-8"))
    undocumented = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        registered = any(
            isinstance(d.func if isinstance(d, ast.Call) else d, ast.Attribute)
            and (d.func if isinstance(d, ast.Call) else d).attr == "tool"
            for d in node.decorator_list
        )
        if registered and not ast.get_docstring(node):
            undocumented.append(node.name)

    assert not undocumented, (
        f"{server.name}: {sorted(undocumented)} have no docstring. The docstring is "
        "the tool's interface to the model — without it the tool is unusable."
    )
