"""Cliente HTTP directo para la API REST de Ollama (sin autenticación)."""

from __future__ import annotations

import json
import re
from typing import Any, Iterator

import httpx

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT = 300.0

# Ollama >= 0.5.5 usa POST /api/create con model + from (no modelfile)
_CREATE_API_V2_MIN = (0, 5, 5)


class OllamaAPIClient:
    def __init__(self, base_url: str = DEFAULT_HOST, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)
        self._version_tuple: tuple[int, ...] | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OllamaAPIClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @staticmethod
    def _parse_version(version: str | None) -> tuple[int, ...] | None:
        if not version:
            return None
        match = re.search(r"(\d+(?:\.\d+)*)", str(version))
        if not match:
            return None
        return tuple(int(part) for part in match.group(1).split("."))

    def version_tuple(self) -> tuple[int, ...] | None:
        if self._version_tuple is not None:
            return self._version_tuple
        try:
            info = self.get_version()
            self._version_tuple = self._parse_version(info.get("version"))
        except httpx.HTTPError:
            self._version_tuple = None
        return self._version_tuple

    def uses_create_api_v2(self) -> bool:
        current = self.version_tuple()
        if not current:
            return True
        return current >= _CREATE_API_V2_MIN

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        kwargs: dict[str, Any] = {}
        if json_body is not None:
            kwargs["json"] = json_body
        if content is not None:
            kwargs["content"] = content
        if headers:
            kwargs["headers"] = headers
        response = self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{method} {path} -> {response.status_code}: {response.text}",
                request=response.request,
                response=response,
            )
        return response

    def list_models(self) -> dict[str, Any]:
        return self._request("GET", "/api/tags").json()

    def list_running(self) -> dict[str, Any]:
        return self._request("GET", "/api/ps").json()

    def get_version(self) -> dict[str, Any]:
        """GET /api/version — puede no existir en builds muy antiguos."""
        response = self._client.get("/api/version")
        if response.status_code == 404:
            return {"version": None, "source": "unavailable"}
        response.raise_for_status()
        data = response.json()
        return {"version": data.get("version"), "source": "api"}

    def detect_version(self) -> dict[str, Any]:
        """Intenta obtener la version por API y cabeceras HTTP."""
        try:
            info = self.get_version()
            if info.get("version"):
                return {**info, "detected": True}
        except httpx.HTTPError:
            pass

        try:
            response = self._client.get("/api/tags")
            server = response.headers.get("server", "")
            match = re.search(r"ollama[/\s-]?(\d+(?:\.\d+)*)", server, re.I)
            if match:
                return {
                    "version": match.group(1),
                    "source": "header",
                    "detected": True,
                }
        except httpx.HTTPError:
            pass

        return {"version": None, "source": "unknown", "detected": False}

    def show_model(self, model: str) -> dict[str, Any]:
        return self._request("POST", "/api/show", json_body={"model": model}).json()

    def generate(
        self,
        model: str,
        prompt: str,
        *,
        stream: bool = False,
        options: dict[str, Any] | None = None,
        keep_alive: int | str | None = None,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        body: dict[str, Any] = {"model": model, "prompt": prompt, "stream": stream}
        if options:
            body["options"] = options
        if keep_alive is not None:
            body["keep_alive"] = keep_alive
        if stream:
            return self._stream_ndjson("/api/generate", body)
        return self._request("POST", "/api/generate", json_body=body).json()

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        stream: bool = False,
        options: dict[str, Any] | None = None,
        images: list[str] | None = None,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
        if options:
            body["options"] = options
        if images and messages:
            body["messages"] = list(messages)
            body["messages"][-1] = {**body["messages"][-1], "images": images}
        if stream:
            return self._stream_ndjson("/api/chat", body)
        return self._request("POST", "/api/chat", json_body=body).json()

    def embeddings(self, model: str, prompt: str) -> dict[str, Any]:
        return self._request(
            "POST", "/api/embeddings", json_body={"model": model, "prompt": prompt}
        ).json()

    def pull(self, model: str, *, stream: bool = True) -> Iterator[dict[str, Any]] | dict[str, Any]:
        body = {"model": model, "stream": stream}
        if stream:
            return self._stream_ndjson("/api/pull", body)
        return self._request("POST", "/api/pull", json_body=body).json()

    def push(self, model: str, *, stream: bool = True) -> Iterator[dict[str, Any]] | dict[str, Any]:
        body = {"model": model, "stream": stream}
        if stream:
            return self._stream_ndjson("/api/push", body)
        return self._request("POST", "/api/push", json_body=body).json()

    def delete(self, model: str) -> dict[str, Any]:
        response = self._request("DELETE", "/api/delete", json_body={"model": model})
        if not response.content:
            return {"status": "success"}
        return response.json()

    def copy(self, source: str, destination: str) -> dict[str, Any]:
        return self._request(
            "POST", "/api/copy", json_body={"source": source, "destination": destination}
        ).json()

    def create(
        self,
        create_body: dict[str, Any],
        *,
        stream: bool = True,
    ) -> Iterator[dict[str, Any]] | dict[str, Any]:
        """
        POST /api/create — Ollama >= 0.5.5 / 0.30.x.

        create_body debe incluir al menos:
          {"model": "nombre", "from": "modelo-base", ...}
        """
        body = dict(create_body)
        body["stream"] = stream

        if self.uses_create_api_v2():
            if not body.get("from") and not body.get("files"):
                raise ValueError(
                    "CREATE requiere 'from' o 'files' (API Ollama >= 0.5.5). "
                    f"Cuerpo recibido: {list(body.keys())}"
                )
            if stream:
                return self._stream_ndjson("/api/create", body)
            return self._request("POST", "/api/create", json_body=body).json()

        # Fallback legacy (< 0.5.5): name + modelfile string
        legacy = {
            "name": body.get("model") or body.get("name"),
            "modelfile": body.get("modelfile") or self._legacy_modelfile_from_body(body),
            "stream": stream,
        }
        if stream:
            return self._stream_ndjson("/api/create", legacy)
        return self._request("POST", "/api/create", json_body=legacy).json()

    @staticmethod
    def _legacy_modelfile_from_body(body: dict[str, Any]) -> str:
        lines = [f"FROM {body.get('from', '')}"]
        params = body.get("parameters") or {}
        for key, value in params.items():
            if key == "stop" and isinstance(value, list):
                for stop in value:
                    lines.append(f'PARAMETER stop "{stop}"')
            else:
                lines.append(f"PARAMETER {key} {value}")
        if body.get("template"):
            lines.extend(["", f'TEMPLATE """{body["template"]}"""'])
        if body.get("system"):
            lines.extend(["", f'SYSTEM """{body["system"]}"""'])
        for msg in body.get("messages") or []:
            role = msg.get("role", "user")
            content = str(msg.get("content", "")).replace('"', '\\"')
            lines.append(f'MESSAGE {role} "{content}"')
        return "\n".join(lines) + "\n"

    def unload_model(self, model: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/generate",
            json_body={"model": model, "prompt": "", "keep_alive": 0},
        ).json()

    def blob_exists(self, digest: str) -> bool:
        response = self._client.head(f"/api/blobs/{digest}")
        return response.status_code == 200

    def upload_blob(self, digest: str, data: bytes) -> None:
        self._request(
            "POST",
            f"/api/blobs/{digest}",
            content=data,
            headers={"Content-Type": "application/octet-stream"},
        )

    def openai_list_models(self) -> dict[str, Any]:
        return self._request("GET", "/v1/models").json()

    def openai_chat_completions(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        stream: bool = False,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
        if stream:
            return self._stream_sse("/v1/chat/completions", body)
        return self._request("POST", "/v1/chat/completions", json_body=body).json()

    def openai_completions(
        self,
        model: str,
        prompt: str,
        *,
        stream: bool = False,
    ) -> dict[str, Any] | Iterator[dict[str, Any]]:
        body: dict[str, Any] = {"model": model, "prompt": prompt, "stream": stream}
        if stream:
            return self._stream_sse("/v1/completions", body)
        return self._request("POST", "/v1/completions", json_body=body).json()

    def openai_embeddings(self, model: str, input_text: str) -> dict[str, Any]:
        return self._request(
            "POST", "/v1/embeddings", json_body={"model": model, "input": input_text}
        ).json()

    def _stream_ndjson(self, path: str, body: dict[str, Any]) -> Iterator[dict[str, Any]]:
        with self._client.stream("POST", path, json=body) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.strip():
                    yield json.loads(line)

    def _stream_sse(self, path: str, body: dict[str, Any]) -> Iterator[dict[str, Any]]:
        with self._client.stream("POST", path, json=body) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith("data: "):
                    payload = line[6:].strip()
                    if payload and payload != "[DONE]":
                        yield json.loads(payload)
