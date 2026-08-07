"""
Perplexity Responses API — OpenAI-compatible.

The only provider quirks:
- cost returned as dict → handled by ResponseAPIUsage.parse_cost validator
- preset models (preset/pro-search) → handled by transform_responses_api_request
- HTTP 200 with status:"failed" → raised as exception in transform_response_api_response

Ref: https://docs.perplexity.ai/api-reference/responses-post
"""

import json
from typing import Any, Dict, List, Optional, Set, Union

import httpx

from litellm.litellm_core_utils.litellm_logging import Logging as LiteLLMLoggingObj
from litellm.llms.base_llm.chat.transformation import BaseLLMException
from litellm.llms.openai.responses.transformation import OpenAIResponsesAPIConfig
from litellm.secret_managers.main import get_secret_str
from litellm.types.llms.openai import ResponseInputParam, ResponsesAPIResponse
from litellm.types.router import GenericLiteLLMParams
from litellm.types.utils import LlmProviders


class PerplexityResponsesConfig(OpenAIResponsesAPIConfig):
    def __init__(self) -> None:
        super().__init__()
        self._codex_custom_tool_names: Set[str] = set()

    def get_supported_openai_params(self, model: str) -> list:
        """Ref: https://docs.perplexity.ai/api-reference/responses-post"""
        return [
            "max_output_tokens",
            "stream",
            "temperature",
            "top_p",
            "tools",
            "reasoning",
            "instructions",
            "models",
        ]

    @property
    def custom_llm_provider(self) -> LlmProviders:
        return LlmProviders.PERPLEXITY

    def validate_environment(self, headers: dict, model: str, litellm_params: Optional[GenericLiteLLMParams]) -> dict:
        litellm_params = litellm_params or GenericLiteLLMParams()
        api_key = (
            litellm_params.api_key or get_secret_str("PERPLEXITYAI_API_KEY") or get_secret_str("PERPLEXITY_API_KEY")
        )
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def get_complete_url(self, api_base: Optional[str], litellm_params: dict) -> str:
        api_base = api_base or get_secret_str("PERPLEXITY_API_BASE") or "https://api.perplexity.ai"
        return f"{api_base.rstrip('/')}/v1/responses"

    def _ensure_message_type(self, input: Union[str, ResponseInputParam]) -> Union[str, ResponseInputParam]:
        """Ensure list input items have type='message' (required by Perplexity)."""
        if isinstance(input, str):
            return input
        if isinstance(input, list):
            result: List[Any] = []
            for item in input:
                if isinstance(item, dict) and "type" not in item:
                    new_item = dict(item)  # convert to plain dict to avoid TypedDict checking
                    new_item["type"] = "message"
                    result.append(new_item)
                else:
                    result.append(item)
            return result
        return input

    def transform_responses_api_request(
        self,
        model: str,
        input: Union[str, ResponseInputParam],
        response_api_optional_request_params: Dict,
        litellm_params: GenericLiteLLMParams,
        headers: dict,
    ) -> Dict:
        """Handle preset/ model prefix: send as {"preset": name} instead of {"model": name}."""
        input = self._normalize_codex_call_history(input)
        input, hoisted_tools = self._hoist_codex_additional_tools(input)
        if hoisted_tools:
            response_api_optional_request_params = {
                **response_api_optional_request_params,
                "tools": [
                    *(response_api_optional_request_params.get("tools") or []),
                    *hoisted_tools,
                ],
            }
        tools = response_api_optional_request_params.get("tools")
        if isinstance(tools, list):
            response_api_optional_request_params = {
                **response_api_optional_request_params,
                "tools": self._normalize_codex_tools(tools),
            }
        input = self._ensure_message_type(input)
        if model.startswith("preset/"):
            input = self._validate_input_param(input)
            data: Dict = {
                "preset": model[len("preset/") :],
                "input": input,
            }
            data.update(response_api_optional_request_params)
            return data
        return super().transform_responses_api_request(
            model=model,
            input=input,
            response_api_optional_request_params=response_api_optional_request_params,
            litellm_params=litellm_params,
            headers=headers,
        )

    @staticmethod
    def _normalize_codex_call_history(
        input: Union[str, ResponseInputParam],
    ) -> Union[str, ResponseInputParam]:
        """Convert Codex custom-tool history to Perplexity function-call items.

        Codex sends completed tool calls back in the next Responses API request.
        Perplexity does not accept the ``custom_tool_call`` item types, so they
        must use the function-call representation that Perplexity originally
        returned.
        """
        if not isinstance(input, list):
            return input

        normalized: List[Any] = []
        for item in input:
            if not isinstance(item, dict):
                normalized.append(item)
                continue

            item_type = item.get("type")
            if item_type == "custom_tool_call":
                converted = dict(item)
                converted["type"] = "function_call"
                converted["arguments"] = json.dumps(
                    {"content": converted.pop("input", "")},
                    separators=(",", ":"),
                )
                normalized.append(converted)
            elif item_type == "custom_tool_call_output":
                converted = dict(item)
                converted["type"] = "function_call_output"
                converted["output"] = PerplexityResponsesConfig._stringify_tool_output(
                    converted.get("output", "")
                )
                normalized.append(converted)
            else:
                normalized.append(item)
        return normalized

    @staticmethod
    def _stringify_tool_output(output: Any) -> str:
        """Flatten Codex content blocks for Perplexity function-call history."""
        if isinstance(output, str):
            return output
        if isinstance(output, list):
            parts: List[str] = []
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

    @staticmethod
    def _is_codex_additional_tools_item(item: Any) -> bool:
        return isinstance(item, dict) and item.get("type") == "additional_tools"

    @classmethod
    def _hoist_codex_additional_tools(
        cls,
        input: Union[str, ResponseInputParam],
    ) -> tuple[Union[str, ResponseInputParam], List[Any]]:
        """Move Codex responses-lite tool declarations to top-level tools.

        OpenAI accepts ``additional_tools`` input items, while Perplexity's
        Agent API accepts the same definitions only through the standard
        top-level ``tools`` parameter.
        """
        if not isinstance(input, list):
            return input, []

        additional_tools_items = [
            item for item in input if cls._is_codex_additional_tools_item(item)
        ]
        if not additional_tools_items:
            return input, []

        remaining_input = [
            item for item in input if not cls._is_codex_additional_tools_item(item)
        ]
        hoisted_tools = [
            tool
            for item in additional_tools_items
            for tool in (item.get("tools") if isinstance(item.get("tools"), list) else [])
        ]
        return remaining_input, hoisted_tools

    def _normalize_codex_tools(self, tools: List[Any]) -> List[Any]:
        """Convert Codex-only tool declarations to Perplexity functions."""
        normalized: List[Any] = []
        custom_names: Set[str] = set()

        def add_tool(tool: Any) -> None:
            if not isinstance(tool, dict):
                normalized.append(tool)
                return
            tool_type = tool.get("type")
            if tool_type == "namespace":
                for nested in tool.get("tools") or []:
                    add_tool(nested)
                return
            if tool_type == "custom":
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
                return
            normalized.append(tool)

        for tool in tools:
            add_tool(tool)
        self._codex_custom_tool_names = custom_names
        return normalized

    @staticmethod
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

    def _restore_custom_call_item(self, item: Any) -> Any:
        if not isinstance(item, dict):
            return item
        if item.get("type") == "function_call" and item.get("name") in self._codex_custom_tool_names:
            restored = dict(item)
            restored["type"] = "custom_tool_call"
            restored["input"] = self._unwrap_custom_arguments(restored.pop("arguments", ""))
            return restored
        return item

    def _restore_custom_calls_in_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        restored = dict(payload)
        if isinstance(restored.get("item"), dict):
            restored["item"] = self._restore_custom_call_item(restored["item"])
        response = restored.get("response")
        if isinstance(response, dict) and isinstance(response.get("output"), list):
            response = dict(response)
            response["output"] = [self._restore_custom_call_item(item) for item in response["output"]]
            restored["response"] = response
        if isinstance(restored.get("output"), list):
            restored["output"] = [self._restore_custom_call_item(item) for item in restored["output"]]
        return restored

    def transform_response_api_response(
        self,
        model: str,
        raw_response: httpx.Response,
        logging_obj: LiteLLMLoggingObj,
    ) -> ResponsesAPIResponse:
        """Check for Perplexity's status:'failed' on HTTP 200 before delegating to base."""
        try:
            raw_response_json = raw_response.json()
        except Exception:
            raw_response_json = None

        if isinstance(raw_response_json, dict) and raw_response_json.get("status") == "failed":
            error = raw_response_json.get("error", {})
            raise BaseLLMException(
                status_code=raw_response.status_code,
                message=error.get("message", "Unknown Perplexity error"),
            )

        if isinstance(raw_response_json, dict):
            restored_json = self._restore_custom_calls_in_payload(raw_response_json)
            if restored_json != raw_response_json:
                raw_response = httpx.Response(
                    status_code=raw_response.status_code,
                    headers=raw_response.headers,
                    json=restored_json,
                    request=raw_response.request,
                )

        return super().transform_response_api_response(
            model=model,
            raw_response=raw_response,
            logging_obj=logging_obj,
        )

    def transform_streaming_response(
        self,
        model: str,
        parsed_chunk: dict,
        logging_obj: LiteLLMLoggingObj,
    ):
        return super().transform_streaming_response(
            model=model,
            parsed_chunk=self._restore_custom_calls_in_payload(parsed_chunk),
            logging_obj=logging_obj,
        )

    def supports_native_websocket(self) -> bool:
        """Perplexity does not support native WebSocket for Responses API"""
        return False
