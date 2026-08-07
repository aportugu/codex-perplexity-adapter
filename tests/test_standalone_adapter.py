import asyncio
import json
import time
import unittest

import httpx
from fastapi.testclient import TestClient

from codex_perplexity_adapter.app import (
    ResponsesStreamNormalizer,
    Settings,
    _translate_sse,
    create_app,
)
from codex_perplexity_adapter.transform import transform_request, transform_response


class TransformationTests(unittest.TestCase):
    def test_codex_custom_tool_round_trip(self):
        request, custom_names = transform_request(
            {
                "model": "gpt-5.6-sol",
                "input": [
                    {"role": "user", "content": "inspect files"},
                    {
                        "type": "custom_tool_call",
                        "name": "exec",
                        "call_id": "call_1",
                        "input": "text(await tools.exec_command({cmd: 'rg --files'}))",
                    },
                    {
                        "type": "custom_tool_call_output",
                        "call_id": "call_1",
                        "output": [
                            {"type": "input_text", "text": "Output:\n"},
                            {"type": "input_text", "text": "analysis.Rmd\n"},
                        ],
                    },
                ],
                "tools": [{"type": "custom", "name": "exec", "description": "run code"}],
                "store": False,
            },
            "openai/gpt-5.6-sol",
        )
        self.assertEqual(request["model"], "openai/gpt-5.6-sol")
        self.assertNotIn("store", request)
        self.assertEqual(request["input"][0]["type"], "message")
        self.assertEqual(request["input"][1]["type"], "function_call")
        self.assertEqual(request["input"][2]["type"], "function_call_output")
        self.assertEqual(request["input"][2]["output"], "Output:\nanalysis.Rmd\n")
        self.assertEqual(custom_names, {"exec"})

        response = transform_response(
            {
                "output": [
                    {
                        "type": "function_call",
                        "name": "exec",
                        "call_id": "call_2",
                        "arguments": '{"content":"text(1)"}',
                    }
                ],
                "usage": {"cost": {"total_cost": 0.01}},
            },
            custom_names,
        )
        self.assertEqual(response["output"][0]["type"], "custom_tool_call")
        self.assertEqual(response["output"][0]["input"], "text(1)")
        self.assertEqual(response["usage"]["cost"], 0.01)


class AppTests(unittest.TestCase):
    def test_non_streaming_proxy(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            sent = json.loads(request.content)
            self.assertEqual(sent["model"], "openai/gpt-5.6-sol")
            self.assertEqual(request.headers["authorization"], "Bearer perplexity-secret")
            return httpx.Response(
                200,
                json={"id": "resp_1", "status": "completed", "output": []},
            )

        app = create_app(
            Settings(api_key="perplexity-secret"),
            transport=httpx.MockTransport(handler),
        )
        with TestClient(app) as client:
            response = client.post(
                "/v1/responses",
                headers={"Authorization": "Bearer local-adapter-token"},
                json={"model": "gpt-5.6-sol", "input": "hello"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "resp_1")

    def test_streaming_custom_call_translation(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            body = (
                'event: response.output_item.done\n'
                'data: {"type":"response.output_item.done","item":{"type":"function_call",'
                '"name":"exec","call_id":"call_2","arguments":"{\\"content\\":\\"text(1)\\"}"}}\n\n'
                'data: [DONE]\n\n'
            )
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

        app = create_app(
            Settings(api_key="perplexity-secret"),
            transport=httpx.MockTransport(handler),
        )
        with TestClient(app) as client:
            response = client.post(
                "/v1/responses",
                headers={"Authorization": "Bearer local-adapter-token"},
                json={
                    "model": "gpt-5.6-sol",
                    "input": "hello",
                    "stream": True,
                    "tools": [{"type": "custom", "name": "exec"}],
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn('"type":"custom_tool_call"', response.text)
        self.assertIn('"input":"text(1)"', response.text)


class DelayedSSEStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'data: {"type":"response.output_text.delta","delta":"first"}\n\n'
        await asyncio.sleep(0.15)
        yield b'data: {"type":"response.output_text.delta","delta":"second"}\n\n'


class IncrementalStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_translator_yields_before_upstream_finishes(self):
        client = httpx.AsyncClient()
        upstream = httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=DelayedSSEStream(),
            request=httpx.Request("POST", "https://example.test/v1/responses"),
        )
        stream = _translate_sse(upstream, set(), client)

        started = time.monotonic()
        first = await anext(stream)
        self.assertLess(time.monotonic() - started, 0.10)
        self.assertIn(b'"type":"response.output_item.added"', first)
        content_part = await anext(stream)
        self.assertIn(b'"type":"response.content_part.added"', content_part)
        first_delta = await anext(stream)
        self.assertLess(time.monotonic() - started, 0.10)
        self.assertIn(b'"delta":"first"', first_delta)

        remaining = b""
        async for chunk in stream:
            remaining += chunk
        self.assertIn(b'"delta":"second"', remaining)
        self.assertGreaterEqual(time.monotonic() - started, 0.14)


class StreamSchemaTests(unittest.TestCase):
    def test_malformed_message_item_is_made_valid_for_codex(self):
        normalizer = ResponsesStreamNormalizer(set())
        events = normalizer.normalize(
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {"id": "msg_1", "type": "message", "status": "in_progress"},
            }
        )
        self.assertEqual(
            events[0]["item"],
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "content": [],
            },
        )

    def test_delta_without_item_gets_active_message_first(self):
        normalizer = ResponsesStreamNormalizer(set())
        events = normalizer.normalize(
            {"type": "response.output_text.delta", "output_index": 0, "delta": "Hello"}
        )
        self.assertEqual(
            [event["type"] for event in events],
            [
                "response.output_item.added",
                "response.content_part.added",
                "response.output_text.delta",
            ],
        )
        self.assertEqual(events[0]["item"]["role"], "assistant")

    def test_missing_content_part_events_are_synthesized(self):
        normalizer = ResponsesStreamNormalizer(set())
        normalizer.normalize(
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {"id": "msg_1", "type": "message", "content": []},
            }
        )
        delta_events = normalizer.normalize(
            {"type": "response.output_text.delta", "output_index": 0, "delta": "Hello"}
        )
        self.assertEqual(
            [event["type"] for event in delta_events],
            ["response.content_part.added", "response.output_text.delta"],
        )
        self.assertEqual(delta_events[1]["item_id"], "msg_1")
        self.assertEqual(delta_events[1]["content_index"], 0)
        self.assertEqual([event["sequence_number"] for event in delta_events], [1, 2])

        done_events = normalizer.normalize(
            {"type": "response.output_text.done", "output_index": 0, "text": "Hello"}
        )
        self.assertEqual(
            [event["type"] for event in done_events],
            ["response.output_text.done", "response.content_part.done"],
        )


if __name__ == "__main__":
    unittest.main()
