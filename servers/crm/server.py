"""CRM MCP Server — bridge between Claude Code and a private CRM REST API."""

import json
import logging
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vsl-crm-mcp")

CONFIG_PATH = Path(__file__).parent / "config.json"


class CRMClient:
    """Async HTTP client with JWT auto-refresh for VSL CRM API."""

    def __init__(self, config_path: Path = CONFIG_PATH):
        config = json.loads(config_path.read_text())
        self.api_base = config["api_base"]
        self.email = config["email"]
        self.password = config["password"]
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.http = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    async def _login(self):
        resp = await self.http.post(
            f"{self.api_base}/auth/token",
            json={"email": self.email, "password": self.password},
        )
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]

    async def _refresh(self):
        resp = await self.http.post(
            f"{self.api_base}/auth/refresh",
            json={"refresh_token": self.refresh_token},
        )
        if resp.status_code == 200:
            data = resp.json()
            self.access_token = data["access_token"]
            self.refresh_token = data.get("refresh_token", self.refresh_token)
            return True
        return False

    async def _request(self, method: str, path: str, **kwargs) -> dict | list | None:
        if not self.access_token:
            await self._login()

        url = f"{self.api_base}{path}"
        headers = {"Authorization": f"Bearer {self.access_token}"}

        resp = await self.http.request(method, url, headers=headers, **kwargs)

        if resp.status_code == 401:
            if await self._refresh():
                headers = {"Authorization": f"Bearer {self.access_token}"}
                resp = await self.http.request(method, url, headers=headers, **kwargs)
            else:
                await self._login()
                headers = {"Authorization": f"Bearer {self.access_token}"}
                resp = await self.http.request(method, url, headers=headers, **kwargs)

        if resp.status_code == 204:
            return None
        resp.raise_for_status()
        return resp.json()

    async def get(self, path: str, params: dict | None = None):
        return await self._request("GET", path, params=params)

    async def post(self, path: str, data: dict | None = None):
        return await self._request("POST", path, json=data)

    async def put(self, path: str, data: dict | None = None):
        return await self._request("PUT", path, json=data)

    async def delete(self, path: str):
        return await self._request("DELETE", path)


# --- MCP Server ---

mcp = FastMCP("vsl-crm", instructions="Tools for managing projects, clients, deals, tasks, invoices and proposals in a private CRM.")
client = CRMClient()


@mcp.tool()
async def crm_list_projects(
    client_id: int | None = None,
    status: str | None = None,
) -> str:
    """List all projects in the CRM. Optionally filter by client_id or status."""
    try:
        params = {}
        if client_id:
            params["client_id"] = client_id
        if status:
            params["status"] = status
        projects = await client.get("/projects", params=params or None)
        if not projects:
            return "No projects found."
        lines = []
        for p in projects:
            lines.append(
                f"ID {p['id']} | {p['progress']}% | {p['status']} | "
                f"{p.get('client_name', '?')} | {p['name']}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing projects: {e}"


@mcp.tool()
async def crm_update_project(
    project_id: int,
    description: str | None = None,
    progress: int | None = None,
    status: str | None = None,
) -> str:
    """Update a project's description, progress percentage, or status."""
    try:
        data = {}
        if description is not None:
            data["description"] = description
        if progress is not None:
            data["progress"] = progress
        if status is not None:
            data["status"] = status
        if not data:
            return "Error: No fields to update."
        result = await client.put(f"/projects/{project_id}", data=data)
        return (
            f"Project #{result['id']} ({result['name']}) updated: "
            f"progress={result['progress']}%, status={result['status']}"
        )
    except Exception as e:
        return f"Error updating project #{project_id}: {e}"


@mcp.tool()
async def crm_create_project(
    client_id: int,
    name: str,
    description: str = "",
    status: str = "planning",
    progress: int = 0,
) -> str:
    """Create a project for a client. Status: planning, in_progress, review, on_hold, completed."""
    try:
        data = {
            "client_id": client_id,
            "name": name,
            "status": status,
            "progress": progress,
        }
        if description:
            data["description"] = description
        result = await client.post("/projects", data=data)
        return (
            f"Project created (ID {result['id']}): {result['name']} | "
            f"{result.get('status', 'planning')} | {result.get('progress', 0)}% | client #{client_id}"
        )
    except Exception as e:
        return f"Error creating project: {e}"


@mcp.tool()
async def crm_create_insight(
    title: str,
    content: str,
    severity: str = "info",
    type: str = "alert",
    entity_type: str = "",
    entity_id: int = 0,
) -> str:
    """Create a Terrance insight visible in the CRM frontend. Severity: info, warning, critical. Type: alert, analysis, coaching, daily_summary."""
    try:
        data = {
            "type": type,
            "severity": severity,
            "title": title,
            "content": content,
        }
        if entity_type:
            data["entity_type"] = entity_type
        if entity_id:
            data["entity_id"] = entity_id
        result = await client.post("/terrance/insights", data=data)
        return (
            f"Insight created (ID {result['id']}): [{result['severity']}] {result['title']}"
        )
    except Exception as e:
        return f"Error creating insight: {e}"


@mcp.tool()
async def crm_log_activity(
    type: str,
    summary: str,
    project_id: int | None = None,
    client_id: int | None = None,
    detail: str | None = None,
) -> str:
    """Log an activity (commit, deploy, update, review, fix, feature, meeting, other)."""
    try:
        data = {
            "type": type,
            "summary": summary,
            "source": "claude_code",
        }
        if project_id is not None:
            data["project_id"] = project_id
        if client_id is not None:
            data["client_id"] = client_id
        if detail is not None:
            data["detail"] = detail
        result = await client.post("/activity-log", data=data)
        return (
            f"Activity logged (ID {result['id']}): [{result['type']}] {result['summary']} "
            f"| project: {result.get('project_name', 'N/A')} | {result['created_at']}"
        )
    except Exception as e:
        return f"Error logging activity: {e}"


@mcp.tool()
async def crm_create_interaction(
    client_id: int,
    type: str,
    content: str,
    project_id: int | None = None,
) -> str:
    """Log a client interaction (note, call, email, meeting, whatsapp)."""
    try:
        data = {
            "client_id": client_id,
            "type": type,
            "content": content,
        }
        if project_id is not None:
            data["project_id"] = project_id
        result = await client.post(f"/clients/{client_id}/interactions", data=data)
        return f"Interaction logged (ID {result['id']}): [{result['type']}] for client #{client_id}"
    except Exception as e:
        return f"Error creating interaction: {e}"


@mcp.tool()
async def crm_list_clients(status: str | None = None) -> str:
    """List all clients. Optionally filter by status (active, inactive, lead)."""
    try:
        params = {"status": status} if status else None
        clients_list = await client.get("/clients", params=params)
        if not clients_list:
            return "No clients found."
        lines = []
        for c in clients_list:
            lines.append(
                f"ID {c['id']} | {c['status']} | {c['name']} | {c.get('industry', 'N/A')}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing clients: {e}"


@mcp.tool()
async def crm_create_deal(
    client_id: int,
    title: str,
    stage: str = "lead",
    value: float | None = None,
    expected_close: str | None = None,
    notes: str | None = None,
) -> str:
    """Create a deal in the pipeline. Stages: lead, contact, proposal, negotiation, won, lost."""
    try:
        data = {"client_id": client_id, "title": title, "stage": stage}
        if value is not None:
            data["value"] = value
        if expected_close is not None:
            data["expected_close"] = expected_close
        if notes is not None:
            data["notes"] = notes
        result = await client.post("/deals", data=data)
        return (
            f"Deal created (ID {result['id']}): {result['title']} | "
            f"stage={result['stage']} | value=${result.get('value', 0)}"
        )
    except Exception as e:
        return f"Error creating deal: {e}"


@mcp.tool()
async def crm_update_deal(
    deal_id: int,
    stage: str | None = None,
    value: float | None = None,
    notes: str | None = None,
) -> str:
    """Update a deal's stage, value, or notes."""
    try:
        data = {}
        if stage is not None:
            data["stage"] = stage
        if value is not None:
            data["value"] = value
        if notes is not None:
            data["notes"] = notes
        if not data:
            return "Error: No fields to update."
        result = await client.put(f"/deals/{deal_id}", data=data)
        return (
            f"Deal #{result['id']} ({result['title']}) updated: "
            f"stage={result['stage']}, value=${result.get('value', 0)}"
        )
    except Exception as e:
        return f"Error updating deal #{deal_id}: {e}"


@mcp.tool()
async def crm_create_proposal(
    client_id: int,
    title: str,
    deal_id: int | None = None,
    content: str | None = None,
    total_amount: float | None = None,
    valid_until: str | None = None,
) -> str:
    """Create a proposal for a client. Optionally link to a deal."""
    try:
        data = {"client_id": client_id, "title": title}
        if deal_id is not None:
            data["deal_id"] = deal_id
        if content is not None:
            data["content"] = content
        if total_amount is not None:
            data["total_amount"] = total_amount
        if valid_until is not None:
            data["valid_until"] = valid_until
        result = await client.post("/proposals", data=data)
        return (
            f"Proposal created (ID {result['id']}): {result['title']} | "
            f"${result.get('total_amount', 0)} | status={result['status']}"
        )
    except Exception as e:
        return f"Error creating proposal: {e}"


@mcp.tool()
async def crm_update_proposal(
    proposal_id: int,
    status: str | None = None,
    content: str | None = None,
    total_amount: float | None = None,
) -> str:
    """Update a proposal's status (draft, sent, viewed, accepted, rejected), content, or amount."""
    try:
        data = {}
        if status is not None:
            data["status"] = status
        if content is not None:
            data["content"] = content
        if total_amount is not None:
            data["total_amount"] = total_amount
        if not data:
            return "Error: No fields to update."
        result = await client.put(f"/proposals/{proposal_id}", data=data)
        return (
            f"Proposal #{result['id']} ({result['title']}) updated: "
            f"status={result['status']}"
        )
    except Exception as e:
        return f"Error updating proposal #{proposal_id}: {e}"


@mcp.tool()
async def crm_dashboard() -> str:
    """Get CRM dashboard stats: clients, projects, pipeline, tasks, revenue."""
    try:
        d = await client.get("/dashboard")
        return (
            f"Clients: {d['clients']['active']} active / {d['clients']['total']} total\n"
            f"Projects: {d['projects']['active']} active / {d['projects']['total']} total\n"
            f"Pipeline: ${d['pipeline']['value']:,.0f} open | "
            f"{d['pipeline']['open_deals']} deals | {d['pipeline']['won_deals']} won\n"
            f"Tasks: {d['tasks']['pending']} pending | {d['tasks']['overdue']} overdue\n"
            f"Revenue this month: ${d['revenue']['invoiced_month']:,.0f} invoiced | "
            f"${d['revenue']['paid_month']:,.0f} paid\n"
            f"Unread messages: {d['unread_contacts']}"
        )
    except Exception as e:
        return f"Error fetching dashboard: {e}"


@mcp.tool()
async def crm_create_task(
    project_id: int,
    title: str,
    description: str | None = None,
    priority: str = "medium",
    sprint_id: int | None = None,
    story_points: int | None = None,
    label: str | None = None,
) -> str:
    """Create a task for a project. Priority: low, medium, high, urgent. Label: bug, feature, chore, improvement."""
    try:
        data = {"project_id": project_id, "title": title, "priority": priority}
        if description is not None:
            data["description"] = description
        if sprint_id is not None:
            data["sprint_id"] = sprint_id
        if story_points is not None:
            data["story_points"] = story_points
        if label is not None:
            data["label"] = label
        result = await client.post("/tasks", data=data)
        return (
            f"Task created (ID {result['id']}): {result['title']} | "
            f"priority={result['priority']} | project #{project_id}"
        )
    except Exception as e:
        return f"Error creating task: {e}"


@mcp.tool()
async def crm_update_task(
    task_id: int,
    status: str | None = None,
    title: str | None = None,
    description: str | None = None,
    priority: str | None = None,
) -> str:
    """Update a task's status (todo, in_progress, review, done), title, description, or priority."""
    try:
        data = {}
        if status is not None:
            data["status"] = status
        if title is not None:
            data["title"] = title
        if description is not None:
            data["description"] = description
        if priority is not None:
            data["priority"] = priority
        if not data:
            return "Error: No fields to update."
        result = await client.put(f"/tasks/{task_id}", data=data)
        return (
            f"Task #{result['id']} ({result['title']}) updated: "
            f"status={result['status']}, priority={result['priority']}"
        )
    except Exception as e:
        return f"Error updating task #{task_id}: {e}"


@mcp.tool()
async def crm_search(query: str) -> str:
    """Search across clients, projects, deals, and tasks by keyword."""
    try:
        results = await client.get("/search", params={"q": query})
        if not results:
            return f"No results for '{query}'."
        lines = []
        for r in results if isinstance(results, list) else results.get("results", []):
            lines.append(f"[{r.get('type', '?')}] ID {r.get('id', '?')} | {r.get('name', r.get('title', '?'))}")
        return "\n".join(lines) if lines else f"No results for '{query}'."
    except Exception as e:
        if "404" in str(e):
            return "Endpoint /search not available yet — needs to be added to CRM API."
        return f"Error searching: {e}"


@mcp.tool()
async def crm_list_invoices(status: str = "all") -> str:
    """List invoices. Filter by status: all, draft, sent, paid, overdue."""
    try:
        params = {} if status == "all" else {"status": status}
        invoices = await client.get("/invoices", params=params or None)
        if not invoices:
            return "No invoices found."
        lines = []
        for inv in invoices:
            lines.append(
                f"ID {inv['id']} | ${inv.get('amount', 0):,.2f} | {inv.get('status', '?')} | "
                f"{inv.get('client_name', '?')} | due: {inv.get('due_date', 'N/A')}"
            )
        return "\n".join(lines)
    except Exception as e:
        if "404" in str(e):
            return "Endpoint /invoices not available yet — needs to be added to CRM API."
        return f"Error listing invoices: {e}"


@mcp.tool()
async def crm_create_invoice(
    client_id: int,
    amount: float,
    description: str,
    due_date: str = "",
) -> str:
    """Create an invoice for a client. Amount in USD, due_date as YYYY-MM-DD."""
    try:
        data = {
            "client_id": client_id,
            "subtotal": amount,
            "total": amount,
            "notes": description,
        }
        if due_date:
            data["due_at"] = due_date
        result = await client.post("/invoices", data=data)
        return (
            f"Invoice created (ID {result['id']}): ${result.get('total', 0):,.2f} | "
            f"{result.get('status', 'draft')} | client #{client_id}"
        )
    except Exception as e:
        if "404" in str(e):
            return "Endpoint POST /invoices not available yet — needs to be added to CRM API."
        return f"Error creating invoice: {e}"


@mcp.tool()
async def crm_list_deals(stage: str = "all") -> str:
    """List deals in the pipeline. Filter by stage: all, lead, contact, proposal, negotiation, won, lost."""
    try:
        params = {} if stage == "all" else {"stage": stage}
        deals = await client.get("/deals", params=params or None)
        if not deals:
            return "No deals found."
        lines = []
        for d in deals:
            lines.append(
                f"ID {d['id']} | {d['stage']} | ${float(d.get('value') or 0):,.0f} | "
                f"{d.get('client_name', '?')} | {d['title']}"
            )
        return "\n".join(lines)
    except Exception as e:
        if "404" in str(e):
            return "Endpoint GET /deals not available yet — needs to be added to CRM API."
        return f"Error listing deals: {e}"


@mcp.tool()
async def crm_list_tasks(status: str = "open") -> str:
    """List tasks. Filter by status: open (todo+in_progress), todo, in_progress, review, done, all."""
    try:
        params = {} if status == "all" else {"status": status}
        tasks = await client.get("/tasks", params=params or None)
        if not tasks:
            return f"No tasks with status '{status}'."
        lines = []
        for t in tasks:
            lines.append(
                f"ID {t['id']} | {t.get('status', '?')} | {t.get('priority', '?')} | "
                f"{t['title']} | project: {t.get('project_name', '?')}"
            )
        return "\n".join(lines)
    except Exception as e:
        if "404" in str(e):
            return "Endpoint GET /tasks not available yet — needs to be added to CRM API."
        return f"Error listing tasks: {e}"


@mcp.tool()
async def crm_create_client(
    name: str,
    email: str = "",
    phone: str = "",
    company: str = "",
    industry: str = "",
) -> str:
    """Create a new client in the CRM."""
    try:
        data = {"name": name}
        if email:
            data["email"] = email
        if phone:
            data["phone"] = phone
        if company:
            data["company"] = company
        if industry:
            data["industry"] = industry
        result = await client.post("/clients", data=data)
        return (
            f"Client created (ID {result['id']}): {result['name']} | "
            f"{result.get('email', 'N/A')} | {result.get('status', 'lead')}"
        )
    except Exception as e:
        if "404" in str(e):
            return "Endpoint POST /clients not available yet — needs to be added to CRM API."
        return f"Error creating client: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
