"""Notion MCP Server — Read and write Notion pages/databases via API."""

import json
import logging
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("notion-mcp")

CONFIG_PATH = Path(__file__).parent / "config.json"
_config = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
NOTION_TOKEN = _config.get("token", "")
NOTION_VERSION = "2022-06-28"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}

http = httpx.AsyncClient(timeout=15.0, headers=HEADERS, base_url="https://api.notion.com/v1")

mcp = FastMCP("notion", instructions="Tools for reading and writing to Notion workspace. Search pages, read content, update pages, query databases.")


def _extract_text(block: dict) -> str:
    """Extract plain text from a Notion block."""
    block_type = block.get("type", "")
    data = block.get(block_type, {})
    rich_text = data.get("rich_text", []) or data.get("text", [])
    return "".join(t.get("plain_text", "") for t in rich_text)


def _extract_title(page: dict) -> str:
    """Extract title from a Notion page."""
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    return "Untitled"


@mcp.tool()
async def notion_search(query: str, page_size: int = 10) -> str:
    """Search Notion workspace for pages and databases by keyword."""
    try:
        resp = await http.post("/search", json={"query": query, "page_size": page_size})
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return f"No results for '{query}'"
        lines = []
        for r in results:
            obj_type = r.get("object", "?")
            title = _extract_title(r) if obj_type == "page" else r.get("title", [{}])[0].get("plain_text", "Untitled") if r.get("title") else "Untitled"
            url = r.get("url", "")
            parent = r.get("parent", {})
            parent_type = parent.get("type", "")
            lines.append(f"[{obj_type}] {title}\n  URL: {url}\n  ID: {r['id']}")
        return "\n\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def notion_read_page(page_id: str) -> str:
    """Read the content of a Notion page (blocks). Returns markdown-ish text."""
    try:
        # Get page metadata
        page_resp = await http.get(f"/pages/{page_id}")
        page_resp.raise_for_status()
        page = page_resp.json()
        title = _extract_title(page)

        # Get blocks
        blocks_resp = await http.get(f"/blocks/{page_id}/children", params={"page_size": 100})
        blocks_resp.raise_for_status()
        blocks = blocks_resp.json().get("results", [])

        lines = [f"# {title}\n"]
        for block in blocks:
            btype = block.get("type", "")
            text = _extract_text(block)
            if btype == "heading_1":
                lines.append(f"# {text}")
            elif btype == "heading_2":
                lines.append(f"## {text}")
            elif btype == "heading_3":
                lines.append(f"### {text}")
            elif btype == "bulleted_list_item":
                lines.append(f"- {text}")
            elif btype == "numbered_list_item":
                lines.append(f"1. {text}")
            elif btype == "to_do":
                checked = block.get("to_do", {}).get("checked", False)
                lines.append(f"[{'x' if checked else ' '}] {text}")
            elif btype == "toggle":
                lines.append(f"> {text}")
            elif btype == "divider":
                lines.append("---")
            elif btype == "callout":
                lines.append(f"> {text}")
            elif text:
                lines.append(text)
            elif btype == "image":
                url = block.get("image", {}).get("file", {}).get("url", "") or block.get("image", {}).get("external", {}).get("url", "")
                lines.append(f"[image: {url[:80]}]")
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading page: {e}"


@mcp.tool()
async def notion_query_database(database_id: str, filter_json: str = "") -> str:
    """Query a Notion database. Optionally pass filter as JSON string."""
    try:
        body = {}
        if filter_json:
            body["filter"] = json.loads(filter_json)
        resp = await http.post(f"/databases/{database_id}/query", json=body)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return "No rows found."
        lines = []
        for row in results[:20]:
            title = _extract_title(row)
            props = row.get("properties", {})
            prop_summary = []
            for name, prop in props.items():
                ptype = prop.get("type", "")
                if ptype == "title":
                    continue
                elif ptype == "select":
                    val = (prop.get("select") or {}).get("name", "")
                elif ptype == "number":
                    val = prop.get("number", "")
                elif ptype == "checkbox":
                    val = "Yes" if prop.get("checkbox") else "No"
                elif ptype == "date":
                    val = (prop.get("date") or {}).get("start", "")
                elif ptype == "rich_text":
                    val = "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))
                elif ptype == "status":
                    val = (prop.get("status") or {}).get("name", "")
                elif ptype == "multi_select":
                    val = ", ".join(s.get("name", "") for s in prop.get("multi_select", []))
                else:
                    val = ""
                if val:
                    prop_summary.append(f"{name}: {val}")
            lines.append(f"**{title}** | {' | '.join(prop_summary)}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def notion_update_page(page_id: str, properties_json: str) -> str:
    """Update a Notion page's properties. Pass properties as JSON string matching Notion API format."""
    try:
        props = json.loads(properties_json)
        resp = await http.patch(f"/pages/{page_id}", json={"properties": props})
        resp.raise_for_status()
        return f"Page {page_id} updated successfully."
    except Exception as e:
        return f"Error updating page: {e}"


@mcp.tool()
async def notion_append_block(page_id: str, content: str, block_type: str = "paragraph") -> str:
    """Append a text block to a Notion page. Types: paragraph, heading_2, bulleted_list_item, to_do, callout."""
    try:
        block = {
            "object": "block",
            "type": block_type,
            block_type: {
                "rich_text": [{"type": "text", "text": {"content": content}}]
            }
        }
        resp = await http.patch(f"/blocks/{page_id}/children", json={"children": [block]})
        resp.raise_for_status()
        return f"Block appended to {page_id}."
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    mcp.run()
