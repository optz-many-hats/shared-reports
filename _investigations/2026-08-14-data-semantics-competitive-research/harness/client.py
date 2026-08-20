"""Hypatia agent execution client - HTTP + SSE.

Calls specialized agents via POST /stream-execute and consumes the SSE
stream to collect the full response text and execution metadata.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx
from httpx_sse import connect_sse

from .auth import get_auth


def _extract_json(text: str) -> dict | None:
    """Extract the last valid JSON object from agent output.

    Handles: plain JSON, single code-fenced block, multiple code-fenced
    blocks (takes the last one), or JSON embedded in prose.
    """
    import re

    text = text.strip()

    # Try raw parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Extract all ```json...``` fenced blocks
    fenced = re.findall(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    # Try each fenced block in reverse order (prefer the last one)
    for block in reversed(fenced):
        try:
            return json.loads(block.strip())
        except json.JSONDecodeError:
            continue

    # Last resort: find the last { ... } span using brace matching
    last_open = text.rfind("{")
    if last_open >= 0:
        # Find the matching opening brace by scanning from the first {
        depth = 0
        start = None
        for i, ch in enumerate(text):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        start = None

    print(
        f"Warning: could not parse agent output as JSON. "
        f"Raw text length: {len(text)}",
        file=sys.stderr,
    )
    return None


def _api_prefix(instance_id: str) -> str:
    return f"/hypatia/api/v1/{instance_id}/agents/specialized"


def list_agents(
    env_name: str = "prod",
    instance_id: str | None = None,
) -> list[dict[str, Any]]:
    """List all specialized agents on the instance."""
    base_url, headers = get_auth(env_name, instance_id)
    iid = headers["x-instance-id"]
    url = f"{base_url}{_api_prefix(iid)}"
    with httpx.Client(timeout=30, headers=headers) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
    return data.get("items", data) if isinstance(data, dict) else data


def get_agent(
    agent_id: str,
    env_name: str = "prod",
    instance_id: str | None = None,
) -> dict[str, Any]:
    """Get a single agent definition."""
    base_url, headers = get_auth(env_name, instance_id)
    iid = headers["x-instance-id"]
    url = f"{base_url}{_api_prefix(iid)}/{agent_id}"
    with httpx.Client(timeout=30, headers=headers) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json()


def _resolve_agent_uuid(
    agent_id: str,
    env_name: str,
    instance_id: str | None,
) -> str:
    """If agent_id looks like a slug (not a UUID), resolve it to the system UUID.

    The stream-execute endpoint only accepts the system UUID, not the
    human-readable agent_id slug.
    """
    # UUIDs have dashes and are 36 chars
    if len(agent_id) == 36 and "-" in agent_id:
        return agent_id
    # Slug - look it up
    agents = list_agents(env_name, instance_id)
    for a in agents:
        if a.get("agent_id") == agent_id:
            return a["id"]
    raise ValueError(f"Agent slug '{agent_id}' not found on the instance")


def execute_agent(
    agent_id: str,
    parameters: dict[str, Any],
    env_name: str = "prod",
    instance_id: str | None = None,
) -> dict[str, Any]:
    """Execute a specialized agent via SSE and return parsed JSON output.

    agent_id can be a system UUID or a human-readable slug (e.g.
    "oa-concept-extractor"). Slugs are resolved to UUIDs automatically.

    Returns a dict with:
        - "output": the parsed JSON from the agent's response
        - "raw_text": the raw concatenated response text
        - "execution_id": from the execution_complete event
        - "memory_id": from the execution_complete event
        - "token_usage": token counts if available
    """
    uuid = _resolve_agent_uuid(agent_id, env_name, instance_id)
    base_url, headers = get_auth(env_name, instance_id)
    iid = headers["x-instance-id"]
    url = f"{base_url}{_api_prefix(iid)}/{uuid}/stream-execute"
    body = {"parameters": parameters}

    chunks: list[str] = []
    execution_meta: dict[str, Any] = {}

    debug = bool(os.environ.get("HARNESS_DEBUG"))

    with httpx.Client(timeout=httpx.Timeout(30, read=600), headers=headers) as client:
        with connect_sse(client, "POST", url, json=body) as event_source:
            for sse in event_source.iter_sse():
                if not sse.data:
                    continue
                try:
                    event = json.loads(sse.data)
                except json.JSONDecodeError:
                    if debug:
                        print(f"[DEBUG] non-JSON SSE: {sse.data[:200]}", file=sys.stderr)
                    continue

                event_type = event.get("event_type", "")
                data = event.get("data", {})

                if debug:
                    preview = json.dumps(event, default=str)[:300]
                    print(f"[DEBUG] event_type={event_type} | {preview}", file=sys.stderr)

                if event_type == "response_chunk":
                    text = data.get("content") or data.get("text", "")
                    if text:
                        chunks.append(text)
                        print(text, end="", flush=True, file=sys.stderr)

                elif event_type == "execution_complete":
                    execution_meta = {
                        "execution_id": data.get("execution_id"),
                        "memory_id": data.get("memory_id"),
                        "token_usage": data.get("token_usage"),
                    }

                elif event_type == "error":
                    msg = data.get("message", data.get("error", str(data)))
                    raise RuntimeError(f"Agent execution error: {msg}")

    raw_text = "".join(chunks)
    print(file=sys.stderr)  # newline after streaming

    # Parse the response as JSON. Agents with JSON output schemas return
    # valid JSON, but they sometimes wrap it in markdown code fences or
    # emit multiple JSON blocks (model retries). Extract the last valid
    # JSON object from the text.
    output = _extract_json(raw_text)

    return {
        "output": output,
        "raw_text": raw_text,
        **execution_meta,
    }
