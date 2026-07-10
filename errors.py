"""Formateo y serialización de errores para API y UI."""

from __future__ import annotations

import json
import traceback
from typing import Any

import httpx


def preview_text(text: str, limit: int = 240) -> str:
    normalized = text.replace("\r\n", "\n").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "…"


def format_httpx_error(exc: httpx.HTTPError) -> tuple[str, str | None, dict[str, Any]]:
    """Devuelve (mensaje corto, detalle, debug)."""
    debug: dict[str, Any] = {"exception": type(exc).__name__}

    if isinstance(exc, httpx.ConnectError):
        return "Conexión rechazada. Target inalcanzable.", str(exc) or None, debug

    if isinstance(exc, httpx.TimeoutException):
        return "Timeout alcanzado esperando respuesta del target.", str(exc) or None, debug

    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        request = exc.request
        debug["status_code"] = response.status_code
        debug["method"] = request.method
        debug["url"] = str(request.url)

        body_text = response.text or ""
        debug["response_body"] = preview_text(body_text, 2000)

        ollama_error = _extract_ollama_error(body_text)
        if ollama_error:
            debug["ollama_error"] = ollama_error
            message = f"Ollama {response.status_code}: {ollama_error}"
        else:
            message = f"HTTP {response.status_code} {request.method} {request.url.path}"

        detail = preview_text(body_text, 500) if body_text else None
        return message, detail, debug

    return str(exc) or "Error HTTP desconocido", None, debug


def _extract_ollama_error(body_text: str) -> str | None:
    try:
        data = json.loads(body_text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, str) and err.strip():
            return err.strip()
    return None


def error_payload(
    message: str,
    *,
    error_type: str = "error",
    detail: str | None = None,
    debug: dict[str, Any] | None = None,
    traceback_text: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "error": message,
        "error_type": error_type,
    }
    if detail:
        payload["detail"] = detail
    if debug:
        payload["debug"] = debug
    if traceback_text:
        payload["traceback"] = traceback_text
    return payload


def exception_payload(exc: BaseException, *, include_traceback: bool = True) -> dict[str, Any]:
    if isinstance(exc, httpx.HTTPError):
        message, detail, debug = format_httpx_error(exc)
        return error_payload(
            message,
            error_type=type(exc).__name__,
            detail=detail,
            debug=debug,
            traceback_text=traceback.format_exc() if include_traceback else None,
        )

    if isinstance(exc, ValueError):
        return error_payload(
            str(exc) or "Petición inválida",
            error_type="ValueError",
            traceback_text=traceback.format_exc() if include_traceback else None,
        )

    if isinstance(exc, json.JSONDecodeError):
        return error_payload(
            f"JSON inválido: {exc.msg}",
            error_type="JSONDecodeError",
            detail=f"línea {exc.lineno}, columna {exc.colno}",
            traceback_text=traceback.format_exc() if include_traceback else None,
        )

    return error_payload(
        str(exc) or "Error interno",
        error_type=type(exc).__name__,
        traceback_text=traceback.format_exc() if include_traceback else None,
    )


def sse_error_data(exc: BaseException) -> dict[str, Any]:
    payload = exception_payload(exc, include_traceback=False)
    payload.pop("ok", None)
    payload["message"] = payload.pop("error")
    return payload
