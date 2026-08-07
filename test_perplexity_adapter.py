import importlib.util


path = "./perplexity_responses_transformation.py"
spec = importlib.util.spec_from_file_location("patched", path)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

config = module.PerplexityResponsesConfig()
tools = [
    {
        "type": "custom",
        "name": "apply_patch",
        "description": "patch",
        "format": {"syntax": "lark", "definition": "start: TEXT"},
    },
    {
        "type": "namespace",
        "name": "multi",
        "tools": [
            {
                "type": "function",
                "name": "spawn_agent",
                "description": "spawn",
                "parameters": {"type": "object"},
            }
        ],
    },
]
normalized = config._normalize_codex_tools(tools)
assert [tool["type"] for tool in normalized] == ["function", "function"]
assert [tool["name"] for tool in normalized] == ["apply_patch", "spawn_agent"]

payload = config._restore_custom_calls_in_payload(
    {
        "type": "response.output_item.done",
        "item": {
            "type": "function_call",
            "name": "apply_patch",
            "arguments": '{"content":"*** Begin Patch"}',
            "call_id": "c",
        },
    }
)
assert payload["item"]["type"] == "custom_tool_call"
assert payload["item"]["input"] == "*** Begin Patch"

history = config._normalize_codex_call_history(
    [
        {
            "type": "custom_tool_call",
            "name": "apply_patch",
            "input": "*** Begin Patch",
            "call_id": "c",
        },
        {
            "type": "custom_tool_call_output",
            "call_id": "c",
            "output": [
                {"type": "input_text", "text": "Script completed\nOutput:\n"},
                {"type": "input_text", "text": "file.Rmd\n"},
            ],
        },
    ]
)
assert history[0]["type"] == "function_call"
assert history[0]["arguments"] == '{"content":"*** Begin Patch"}'
assert "input" not in history[0]
assert history[1]["type"] == "function_call_output"
assert history[1]["output"] == "Script completed\nOutput:\nfile.Rmd\n"
print("Codex tool conversion: OK")
