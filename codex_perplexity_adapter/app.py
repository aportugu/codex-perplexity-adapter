"""FastAPI application exposing an OpenAI-compatible Responses endpoint."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .transform import transform_request, transform_response


@dataclass(frozen=True)
class Settings:
    api_key: str
    model_alias: str = "gpt-5.6-sol"
    upstream_model: str = "openai/gpt-5.6-sol"
    upstream_url: str = "https://api.perplexity.ai/v1/responses"
    local_token: str = "local-adapter-token"
    timeout_seconds: float = 300.0


def _error(status_code: int, message: str, error_type: str = "adapter_error") -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message, "type": error_type, "code": status_code}},
    )


def _authorized(authorization: str | None, local_token: str) -> bool:
    if not local_token:
        return True
    return authorization == f"Bearer {local_token}"


class ResponsesStreamNormalizer:
    """Fill protocol events that OpenAI-compatible UIs expect for live text."""

    def __init__(self, custom_names: set[str]) -> None:
        self.custom_names = custom_names
        self.sequence_number = 0
        self.item_ids: dict[int, str] = {}
        self.content_started: set[tuple[int, int]] = set()
        self.content_done: set[tuple[int, int]] = set()
        self.text: dict[tuple[int, int], str] = {}
        self.message_items_started: set[int] = set()

    def _number(self, event: dict[str, Any]) -> dict[str, Any]:
        numbered = dict(event)
        numbered["sequence_number"] = self.sequence_number
        self.sequence_number += 1
        return numbered

    def _coordinates(self, event: dict[str, Any]) -> tuple[int, int, str]:
        output_index = event.get("output_index")
        if not isinstance(output_index, int):
            output_index = 0
        content_index = event.get("content_index")
        if not isinstance(content_index, int):
            content_index = 0
        item_id = event.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            item_id = self.item_ids.get(output_index, f"msg_{output_index}")
        return output_index, content_index, item_id

    def _canonical_message_item(
        self,
        item: dict[str, Any],
        output_index: int,
        *,
        completed: bool,
    ) -> dict[str, Any]:
        """Return the minimal message shape accepted by Codex's strict parser."""
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            item_id = self.item_ids.get(output_index, f"msg_{output_index}")
        self.item_ids[output_index] = item_id

        content = item.get("content")
        if not completed or not isinstance(content, list):
            content = []
        if completed and not content:
            full_text = "".join(
                text
                for (item_output_index, _), text in sorted(self.text.items())
                if item_output_index == output_index
            )
            content = [{"type": "output_text", "text": full_text, "annotations": []}]

        canonical: dict[str, Any] = {
            "id": item_id,
            "type": "message",
            "role": "assistant",
            "content": content,
        }
        phase = item.get("phase")
        if phase in {"commentary", "final_answer"}:
            canonical["phase"] = phase
        return canonical

    def _message_item_added(self, output_index: int, item_id: str) -> dict[str, Any]:
        self.item_ids[output_index] = item_id
        self.message_items_started.add(output_index)
        return {
            "type": "response.output_item.added",
            "output_index": output_index,
            "item": {
                "id": item_id,
                "type": "message",
                "role": "assistant",
                "content": [],
            },
        }

    def normalize(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        event = transform_response(payload, self.custom_names)
        event_type = event.get("type")
        emitted: list[dict[str, Any]] = []

        if event_type == "response.output_item.added":
            output_index, _, _ = self._coordinates(event)
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "message":
                canonical = self._canonical_message_item(item, output_index, completed=False)
                event = {**event, "output_index": output_index, "item": canonical}
                self.message_items_started.add(output_index)
            elif isinstance(item, dict) and isinstance(item.get("id"), str):
                self.item_ids[output_index] = item["id"]

        if event_type == "response.output_item.done":
            output_index, _, _ = self._coordinates(event)
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "message":
                canonical = self._canonical_message_item(item, output_index, completed=True)
                event = {**event, "output_index": output_index, "item": canonical}

        if event_type in {"response.output_text.delta", "response.output_text.done"}:
            output_index, content_index, item_id = self._coordinates(event)
            key = (output_index, content_index)
            if output_index not in self.message_items_started:
                emitted.append(self._number(self._message_item_added(output_index, item_id)))
            event = {
                **event,
                "output_index": output_index,
                "content_index": content_index,
                "item_id": item_id,
            }
            if key not in self.content_started:
                emitted.append(
                    self._number(
                        {
                            "type": "response.content_part.added",
                            "item_id": item_id,
                            "output_index": output_index,
                            "content_index": content_index,
                            "part": {"type": "output_text", "text": "", "annotations": []},
                        }
                    )
                )
                self.content_started.add(key)
            if event_type == "response.output_text.delta" and isinstance(event.get("delta"), str):
                self.text[key] = self.text.get(key, "") + event["delta"]

        if event_type == "response.content_part.added":
            output_index, content_index, _ = self._coordinates(event)
            key = (output_index, content_index)
            if key in self.content_started:
                return emitted
            self.content_started.add(key)

        if event_type == "response.content_part.done":
            output_index, content_index, _ = self._coordinates(event)
            key = (output_index, content_index)
            if key in self.content_done:
                return emitted
            self.content_done.add(key)

        emitted.append(self._number(event))

        if event_type == "response.output_text.done":
            output_index, content_index, item_id = self._coordinates(event)
            key = (output_index, content_index)
            if key not in self.content_done:
                text = event.get("text") if isinstance(event.get("text"), str) else self.text.get(key, "")
                emitted.append(
                    self._number(
                        {
                            "type": "response.content_part.done",
                            "item_id": item_id,
                            "output_index": output_index,
                            "content_index": content_index,
                            "part": {"type": "output_text", "text": text, "annotations": []},
                        }
                    )
                )
                self.content_done.add(key)
        return emitted


async def _translate_sse(
    upstream: httpx.Response,
    custom_names: set[str],
    client: httpx.AsyncClient,
) -> AsyncIterator[bytes]:
    data_lines: list[str] = []
    other_lines: list[str] = []
    normalizer = ResponsesStreamNormalizer(custom_names)
    try:
        async for line in upstream.aiter_lines():
            if line == "":
                if data_lines:
                    data = "\n".join(data_lines)
                    if data != "[DONE]":
                        try:
                            parsed = json.loads(data)
                            if isinstance(parsed, dict):
                                for event in normalizer.normalize(parsed):
                                    event_type = event.get("type", "message")
                                    encoded = json.dumps(event, separators=(",", ":"))
                                    yield f"event: {event_type}\ndata: {encoded}\n\n".encode()
                                data = ""
                        except json.JSONDecodeError:
                            pass
                    if data:
                        yield f"data: {data}\n\n".encode()
                elif other_lines:
                    yield ("\n".join(other_lines) + "\n\n").encode()
                data_lines.clear()
                other_lines.clear()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
            else:
                other_lines.append(line)
        if data_lines or other_lines:
            for other in other_lines:
                yield f"{other}\n".encode()
            if data_lines:
                trailing_data = "\n".join(data_lines)
                yield f"data: {trailing_data}\n\n".encode()
    finally:
        await upstream.aclose()
        await client.aclose()


def create_app(settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    app = FastAPI(title="Codex–Perplexity Adapter", version="0.1.1")

    @app.get("/")
    async def root() -> dict[str, Any]:
        return {
            "name": "Codex–Perplexity Adapter",
            "status": "ok",
            "responses_endpoint": "/v1/responses",
            "model": settings.model_alias,
        }

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/models")
    async def models(authorization: str | None = Header(default=None)) -> Response:
        if not _authorized(authorization, settings.local_token):
            return _error(401, "Invalid local adapter token", "authentication_error")
        return JSONResponse(
            content={
                "object": "list",
                "data": [{"id": settings.model_alias, "object": "model", "owned_by": "perplexity"}],
            }
        )

    @app.post("/v1/responses")
    async def responses(request: Request, authorization: str | None = Header(default=None)) -> Response:
        if not _authorized(authorization, settings.local_token):
            return _error(401, "Invalid local adapter token", "authentication_error")
        try:
            payload = await request.json()
        except Exception:
            return _error(400, "Request body must be valid JSON", "invalid_request_error")
        if not isinstance(payload, dict):
            return _error(400, "Request body must be a JSON object", "invalid_request_error")

        upstream_payload, custom_names = transform_request(payload, settings.upstream_model)
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.timeout_seconds),
            transport=transport,
        )
        upstream_request = client.build_request(
            "POST",
            settings.upstream_url,
            headers={
                "Authorization": f"Bearer {settings.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream" if upstream_payload.get("stream") else "application/json",
            },
            json=upstream_payload,
        )
        try:
            upstream = await client.send(upstream_request, stream=bool(upstream_payload.get("stream")))
        except httpx.HTTPError as exc:
            await client.aclose()
            return _error(502, f"Could not reach Perplexity: {exc}", "upstream_error")

        if upstream.status_code >= 400:
            body = await upstream.aread()
            content_type = upstream.headers.get("content-type", "application/json")
            await upstream.aclose()
            await client.aclose()
            return Response(content=body, status_code=upstream.status_code, media_type=content_type)

        if upstream_payload.get("stream"):
            return StreamingResponse(
                _translate_sse(upstream, custom_names, client),
                status_code=upstream.status_code,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                    "X-Content-Type-Options": "nosniff",
                },
            )

        body = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return Response(content=body, status_code=upstream.status_code)
        if isinstance(parsed, dict) and parsed.get("status") == "failed":
            error = parsed.get("error") if isinstance(parsed.get("error"), dict) else {}
            return _error(400, str(error.get("message", "Perplexity request failed")), "upstream_error")
        if isinstance(parsed, dict):
            parsed = transform_response(parsed, custom_names)
        return JSONResponse(content=parsed, status_code=upstream.status_code)

    return app
