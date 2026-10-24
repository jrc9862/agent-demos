"""The search_source tool (in-process MCP server over the fake corpus) and the agent-file loader."""
import json
from pathlib import Path

from claude_agent_sdk import AgentDefinition, create_sdk_mcp_server, tool

from fake_sources import FakeSources, SourceTimeout, UnknownSource

AGENT_DIR = Path(__file__).parent / "subagents"
MODEL = "claude-opus-5-5"
SEARCH_TOOL = "mcp__src__search_source"


def build_server(sources: FakeSources):
    @tool("search_source", "Fetch one source by id. Returns url, publication_date and passages, "
          "or an error with errorCategory.", {"source_id": str})
    async def search_source(args):
        sid = args.get("source_id", "")
        try:
            return {"content": [{"type": "text", "text": json.dumps(await sources.fetch(sid))}]}
        except SourceTimeout as e:
            err = {"source_id": sid, "errorCategory": e.error_category, "isRetryable": True, "message": str(e)}
        except UnknownSource as e:
            err = {"source_id": sid, "errorCategory": e.error_category, "isRetryable": False, "message": str(e)}
        return {"content": [{"type": "text", "text": json.dumps(err)}], "is_error": True}

    return create_sdk_mcp_server("src", "1.0.0", [search_source])


def load_agent(name: str) -> AgentDefinition:
    """Parse subagents/<name>.md: simple `key: value` frontmatter, body is the prompt."""
    text = (AGENT_DIR / f"{name}.md").read_text()
    _, front, body = text.split("---\n", 2)
    meta = dict(line.split(": ", 1) for line in front.strip().splitlines())
    return AgentDefinition(description=meta["description"], prompt=body.strip(),
                           tools=[t.strip() for t in meta["tools"].split(",")], model=MODEL)
