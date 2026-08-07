"""Protocol translation between Codex and the Perplexity Agent API."""

from __future__ import annotations

import json
from typing import Any


SUPPORTED_REQUEST_FIELDS = {
    "input",
    "instructions",
    "max_output_tokens",
    "models",
    "reasoning",
    "stream",
    "temperature",
    "tools",
    "top_p",
}


def stringify_tool_output(output: Any) -> str:
    """Flatten Codex content blocks into Perplexity's string output format."""
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        parts: list[str] = []
        for block in output:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
            else:
                parts.append(json.dumps(block, separators=(",", ":")))
        return "".join(parts)
    if output is None:
        return ""
    return str(output)


def _normalize_history(items: Any) -> tuple[Any, list[dict[str, Any]]]:
    if not isinstance(items, list):
        return items, []

    normalized: list[Any] = []
    additional_tools: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            normalized.append(item)
            continue

        item_type = item.get("type")
        if item_type == "additional_tools":
            tools = item.get("tools")
            if isinstance(tools, list):
                additional_tools.extend(tool for tool in tools if isinstance(tool, dict))
            continue
        if item_type == "custom_tool_call":
            converted = dict(item)
            converted["type"] = "function_call"
            converted["arguments"] = json.dumps(
                {"content": converted.pop("input", "")}, separators=(",", ":")
            )
            normalized.append(converted)
            continue
        if item_type == "custom_tool_call_output":
            converted = dict(item)
            converted["type"] = "function_call_output"
            converted["output"] = stringify_tool_output(converted.get("output"))
            normalized.append(converted)
            continue
        if "type" not in item:
            converted = dict(item)
            converted["type"] = "message"
            normalized.append(converted)
            continue
        normalized.append(item)
    return normalized, additional_tools


def _normalize_tools(tools: Any) -> tuple[list[Any], set[str]]:
    normalized: list[Any] = []
    custom_names: set[str] = set()

    def add_tool(tool: Any) -> None:
        if not isinstance(tool, dict):
            normalized.append(tool)
            return
        tool_type = tool.get("type")
        if tool_type == "namespace":
            for nested in tool.get("tools") or []:
                add_tool(nested)
            return
        if tool_type != "custom":
            normalized.append(tool)
            return

        name = tool.get("name") if isinstance(tool.get("name"), str) else ""
        if not name:
            return
        custom_names.add(name)
        description = tool.get("description") if isinstance(tool.get("description"), str) else ""
        fmt = tool.get("format")
        if isinstance(fmt, dict) and isinstance(fmt.get("definition"), str) and fmt["definition"]:
            description += f"\n\nFormat:\n```{fmt.get('syntax', '')}\n{fmt['definition']}\n```"
        normalized.append(
            {
                "type": "function",
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": f"The {name} content following the specified format",
                        }
                    },
                    "required": ["content"],
                },
                "strict": True,
            }
        )

    if isinstance(tools, list):
        for tool in tools:
            add_tool(tool)
    return normalized, custom_names


def transform_request(payload: dict[str, Any], upstream_model: str) -> tuple[dict[str, Any], set[str]]:
    """Translate a Codex Responses request into a Perplexity request."""
    transformed = {key: value for key, value in payload.items() if key in SUPPORTED_REQUEST_FIELDS}
    transformed_input, additional_tools = _normalize_history(transformed.get("input"))
    transformed["input"] = transformed_input

    tools = list(transformed.get("tools") or []) + additional_tools
    normalized_tools, custom_names = _normalize_tools(tools)
    if normalized_tools:
        transformed["tools"] = normalized_tools
    else:
        transformed.pop("tools", None)

    if upstream_model.startswith("preset/"):
        transformed["preset"] = upstream_model.removeprefix("preset/")
        transformed.pop("model", None)
    else:
        transformed["model"] = upstream_model
    return transformed, custom_names


def _unwrap_custom_arguments(arguments: Any) -> str:
    if not isinstance(arguments, str):
        return ""
    try:
        parsed = json.loads(arguments)
        if isinstance(parsed, dict) and "content" in parsed:
            return str(parsed["content"])
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return arguments


def _restore_item(item: Any, custom_names: set[str]) -> Any:
    if not isinstance(item, dict):
        return item
    if item.get("type") == "function_call" and item.get("name") in custom_names:
        restored = dict(item)
        restored["type"] = "custom_tool_call"
        restored["input"] = _unwrap_custom_arguments(restored.pop("arguments", ""))
        return restored
    return item


def transform_response(payload: dict[str, Any], custom_names: set[str]) -> dict[str, Any]:
    """Translate Perplexity response objects and stream events back to Codex."""
    restored = dict(payload)
    if isinstance(restored.get("item"), dict):
        restored["item"] = _restore_item(restored["item"], custom_names)
    if isinstance(restored.get("output"), list):
        restored["output"] = [_restore_item(item, custom_names) for item in restored["output"]]
    response = restored.get("response")
    if isinstance(response, dict):
        response = transform_response(response, custom_names)
        restored["response"] = response

    usage = restored.get("usage")
    if isinstance(usage, dict) and isinstance(usage.get("cost"), dict):
        usage = dict(usage)
        usage["cost"] = usage["cost"].get("total_cost")
        restored["usage"] = usage
    return restored
