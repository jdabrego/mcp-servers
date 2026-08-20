# mcp-servers

Four [Model Context Protocol](https://modelcontextprotocol.io) servers that give Claude Code
direct, typed access to the systems I operate: a CRM, an electronic-invoicing backend, a Notion
workspace, and a Linux host running Docker Compose. **38 tools** in total.

They were not written as demos. Each one was built to do real work against a real backend, and
between them they cover four integration shapes worth knowing: an internal REST API behind a
refreshing JWT, a third-party API with a long-lived token, an operational backend queried for
queue health, and a remote host driven over SSH. That is why the design notes below are about
credentials and failure rather than features.

[![CI](https://github.com/jdabrego/mcp-servers/actions/workflows/ci.yml/badge.svg)](https://github.com/jdabrego/mcp-servers/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Quick start

```bash
git clone https://github.com/jdabrego/mcp-servers.git
cd mcp-servers/servers/notion

pip install -r requirements.txt
cp config.example.json config.json   # then put your real values in config.json
python server.py
```

Register it with Claude Code:

```bash
claude mcp add notion -- python /absolute/path/to/servers/notion/server.py
```

Every server follows the same three steps: install, copy the example config, run.

---

## How they are built

**Credentials never touch the code.** Each server reads a `config.json` that sits next to it and
is listed in `.gitignore`. What ships is `config.example.json`, a template with every key and no
value. There is no environment-variable fallback and no default host, so a missing config fails
loudly at startup instead of quietly connecting somewhere unintended.

**Config is resolved relative to the module, not the working directory.** Four servers can run
side by side under one Claude Code session without reading each other's settings.

**Tokens refresh themselves.** The CRM and invoicing servers hold a JWT and renew it when it
expires, so a long-running session does not die halfway through a task.

**Docstrings are the interface.** A tool's docstring is what the model reads to decide whether to
call it, so every tool has one and a test fails the build if a tool loses it.

**The tests are guards, not decoration.** Three of them exist to catch the mistakes that actually
happen in a repository like this:

| Test | What it prevents |
|---|---|
| `tests/test_no_secrets.py` | A credential, private key or real IP address reaching a commit — in code, in an example, or in this README |
| `tests/test_config_contract.py` | Setup instructions drifting from the code, so a fresh clone fails with `KeyError` instead of starting |
| `tests/test_readme_matches_code.py` | This README promising a tool that no longer exists, or hiding one that does |

Run them with:

```bash
pip install pytest
pytest
```

---

## The servers

### `servers/crm` — 20 tools

Project, client, deal, task, invoice and proposal management against a private CRM API, plus the
dashboard and a cross-entity search. Used to drive weekly planning from inside Claude Code.

`crm_dashboard` · `crm_search` ·
`crm_list_projects` · `crm_create_project` · `crm_update_project` ·
`crm_list_clients` · `crm_create_client` ·
`crm_list_deals` · `crm_create_deal` · `crm_update_deal` ·
`crm_list_tasks` · `crm_create_task` · `crm_update_task` ·
`crm_list_invoices` · `crm_create_invoice` ·
`crm_create_proposal` · `crm_update_proposal` ·
`crm_create_interaction` · `crm_log_activity` · `crm_create_insight`

### `servers/dte-hacienda` — 7 tools

Operational visibility over an electronic-invoicing backend that files documents with a national
tax authority: queue health, pending and failed documents, retries, credential expiry, and the
state of the contingency path and the signing service.

`dte_health_check` · `dte_stats` · `dte_list_pending` · `dte_retry_failed` ·
`dte_check_credentials` · `dte_contingency_status` · `dte_firmador_status`

### `servers/notion` — 5 tools

Read and write access to a Notion workspace: search, read a page, query a database, update page
properties, and append blocks.

`notion_search` · `notion_read_page` · `notion_query_database` ·
`notion_update_page` · `notion_append_block`

### `servers/vps-monitor` — 6 tools

Monitoring for a remote Linux host running Docker Compose, over SSH: service status, logs, disk
and resource usage, error counts, and a restart.

`vps_service_status` · `vps_read_logs` · `vps_disk_usage` ·
`vps_resource_usage` · `vps_error_count` · `vps_restart_service`

---

## Requirements

Python 3.11 or newer. Each server lists its own dependencies in `requirements.txt`; between them
that is `mcp` and `httpx`. `vps-monitor` shells out to your local `ssh`, so it expects a key that
already works against the host.

---

## Scope, honestly

These were written for my own infrastructure, and the endpoints they call are private. Cloning
this gives you the patterns — config isolation, token refresh, tool docstrings, the guard tests —
not a service you can point at something and use immediately.

Their backends have not aged at the same rate, and the README should say so rather than imply
otherwise. `notion` talks to a public API and works today against any workspace with a valid
integration token. The other three target infrastructure of mine that has since moved or been
retired, so they stand here as reference implementations: the code is the artefact, not the
deployment behind it.

MIT licensed. Read [LICENSE](LICENSE).
