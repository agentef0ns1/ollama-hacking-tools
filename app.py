#!/usr/bin/env python3
"""
Ollama-hacking-tool — Panel web de auditoría ofensiva sobre API Ollama sin auth.
Solo para laboratorio / instancias autorizadas.
"""

from __future__ import annotations

import base64
import json
import logging
import sys
import traceback
from collections.abc import Iterator as AbcIterator
from pathlib import Path
from typing import Any

import httpx
from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from ollama_client import DEFAULT_HOST, DEFAULT_TIMEOUT, OllamaAPIClient
from cve_catalog import scan_version, OLLAMA_CVES
from modelfile_builder import prepare_create_request
from errors import error_payload, exception_payload, preview_text, sse_error_data

APP_DIR = Path(__file__).resolve().parent
log = logging.getLogger("ollama_tool")

app = Flask(
    __name__,
    template_folder=str(APP_DIR / "templates"),
    static_folder=str(APP_DIR / "static"),
)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024  # 512 MB uploads


def _client_from_request() -> tuple[OllamaAPIClient, dict[str, Any]]:
    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = request.form.to_dict()
        for key, upload in request.files.items():
            if upload and upload.filename:
                raw = upload.read()
                data[f"_upload_{key}"] = raw.decode("utf-8", errors="replace")
                data[f"_upload_{key}_bytes"] = raw
                data[f"_upload_{key}_name"] = upload.filename
    host = (data.get("host") or DEFAULT_HOST).strip()
    timeout = float(data.get("timeout") or DEFAULT_TIMEOUT)
    return OllamaAPIClient(host, timeout=timeout), data


def _upload_text(data: dict[str, Any], key: str) -> str:
    return (data.get(f"_upload_{key}") or "").strip()


def _resolve_modelfile_raw(data: dict[str, Any]) -> tuple[str, str]:
    """Devuelve (contenido, fuente) donde fuente es textarea|upload_modelfile|upload_file|none."""
    textarea = (data.get("modelfile") or "").strip()
    if textarea:
        return textarea, "textarea"
    upload_modelfile = _upload_text(data, "modelfile")
    if upload_modelfile:
        return upload_modelfile, "upload_modelfile"
    upload_file = _upload_text(data, "file")
    if upload_file:
        return upload_file, f"upload_file:{data.get('_upload_file_name', '?')}"
    return "", "none"


def _build_create_debug(
    data: dict[str, Any],
    raw: str,
    source: str,
    model_name: str,
    create_body: dict[str, Any],
    meta: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "api_format": "ollama-0.30",
        "input_source": source,
        "raw_bytes": len(raw.encode("utf-8")),
        "raw_preview": preview_text(raw, 180),
        "converted": bool(meta and meta.get("converted")),
        "model_name": model_name,
        "from": create_body.get("from"),
        "has_system": bool(create_body.get("system")),
        "has_template": bool(create_body.get("template")),
        "parameters_count": len(create_body.get("parameters") or {}),
        "messages_count": len(create_body.get("messages") or []),
        "create_body_preview": preview_text(json.dumps(create_body, ensure_ascii=False), 400),
        "uploads_seen": [
            key
            for key in ("file", "modelfile")
            if data.get(f"_upload_{key}_name")
        ],
        "upload_names": {
            key: data.get(f"_upload_{key}_name")
            for key in ("file", "modelfile")
            if data.get(f"_upload_{key}_name")
        },
    }


def _prepare_create_data(data: dict[str, Any]) -> dict[str, Any]:
    model_name = (data.get("name") or data.get("model") or "").strip()
    raw, source = _resolve_modelfile_raw(data)
    if not raw:
        debug = {"input_source": source, "uploads_seen": list(request.files.keys()) if request.files else []}
        log.warning("CREATE sin contenido: %s", debug)
        raise ValueError("Modelfile / YAML (texto o archivo) es obligatorio")

    log.debug("CREATE input source=%s bytes=%d model=%r", source, len(raw.encode("utf-8")), model_name or None)
    model_name, create_body, meta = prepare_create_request(raw, model_name)

    debug = _build_create_debug(data, raw, source, model_name, create_body, meta)
    log.info(
        "CREATE preparado: model=%s from=%s source=%s messages=%d",
        model_name,
        create_body.get("from"),
        source,
        len(create_body.get("messages") or []),
    )

    enriched = dict(data)
    enriched["_create_name"] = model_name
    enriched["_create_body"] = create_body
    enriched["_create_meta"] = meta
    enriched["_create_debug"] = debug
    return enriched


def _is_stream_result(value: Any) -> bool:
    return isinstance(value, AbcIterator) and not isinstance(value, (str, bytes, dict, list))


def _parse_options(raw: str | None) -> dict[str, Any] | None:
    if not raw or not raw.strip():
        return None
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("options debe ser un objeto JSON")
    return parsed


def _parse_messages(raw: str | None) -> list[dict[str, Any]]:
    if not raw or not raw.strip():
        return []
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("messages debe ser un array JSON")
    return parsed


def _read_upload_text(key: str = "file", data: dict[str, Any] | None = None) -> str | None:
    if data is not None:
        text = _upload_text(data, key)
        return text or None
    f = request.files.get(key)
    if f and f.filename:
        return f.read().decode("utf-8", errors="replace")
    return None


def _read_upload_bytes(key: str = "file", data: dict[str, Any] | None = None) -> bytes | None:
    if data is not None:
        raw = data.get(f"_upload_{key}_bytes")
        if isinstance(raw, bytes) and raw:
            return raw
        text = _upload_text(data, key)
        return text.encode("utf-8") if text else None
    f = request.files.get(key)
    if f and f.filename:
        return f.read()
    return None


def _image_b64_from_upload(key: str = "image", data: dict[str, Any] | None = None) -> str | None:
    raw = _read_upload_bytes(key, data)
    if not raw:
        return None
    return base64.b64encode(raw).decode("ascii")


def _materialize_result(result: Any) -> Any:
    """Convierte iteradores de streaming en listas para respuestas JSON."""
    if isinstance(result, (dict, list, str, int, float, bool)) or result is None:
        return result
    if hasattr(result, "__iter__"):
        return list(result)
    return result


def _sse_event(event: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    return f"event: {event}\ndata: {payload}\n\n"


def _stream_response(generator: AbcIterator[str]) -> Response:
    return Response(
        stream_with_context(generator),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _json_error(exc: BaseException, status: int = 400) -> tuple[Response, int]:
    log.error("%s: %s", type(exc).__name__, exc)
    log.debug(traceback.format_exc())
    return jsonify(exception_payload(exc)), status


def _emit_debug_events(debug: dict[str, Any] | None) -> AbcIterator[str]:
    if not debug:
        return
    yield _sse_event("debug", debug)
    yield _sse_event(
        "log",
        (
            f"CREATE → API 0.30: model={debug.get('model_name')} "
            f"from={debug.get('from')} "
            f"messages={debug.get('messages_count', 0)}"
        ),
    )


def _consume_ndjson_stream(
    chunks: AbcIterator[dict[str, Any]], *, mode: str
) -> AbcIterator[str]:
    try:
        for chunk in chunks:
            if mode == "pull" or mode == "push" or mode == "create":
                status = chunk.get("status")
                if status:
                    yield _sse_event("log", status)
                if chunk.get("error"):
                    yield _sse_event(
                        "error",
                        {
                            "message": chunk["error"],
                            "error_type": "OllamaStreamError",
                            "detail": json.dumps(chunk, ensure_ascii=False),
                            "debug": {"stream_mode": mode, "chunk": chunk},
                        },
                    )
                    break
                continue
            if mode == "chat":
                msg = chunk.get("message", {})
                if msg.get("content"):
                    yield _sse_event("token", msg["content"])
                if chunk.get("done"):
                    yield _sse_event("done", chunk)
                continue
            if mode == "openai":
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                if delta.get("content"):
                    yield _sse_event("token", delta["content"])
                continue
            # generate
            if chunk.get("response"):
                yield _sse_event("token", chunk["response"])
            if chunk.get("done"):
                yield _sse_event("done", chunk)
        yield _sse_event("end", "ok")
    except httpx.HTTPError as exc:
        log.exception("Error HTTP durante stream (%s)", mode)
        yield _sse_event("error", sse_error_data(exc))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        log.exception("Error durante stream (%s)", mode)
        yield _sse_event("error", sse_error_data(exc))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/ping", methods=["POST"])
def api_ping():
    try:
        client, data = _client_from_request()
        with client:
            models = client.list_models()
            count = len(models.get("models", []))
            ver_info = client.detect_version()
            version = ver_info.get("version")
            payload: dict[str, Any] = {
                "ok": True,
                "host": client.base_url,
                "models_count": count,
                "version": version,
                "version_source": ver_info.get("source"),
                "message": f"Target vivo — {count} modelo(s) detectado(s)",
            }
            if version:
                quick = scan_version(version, platform=data.get("platform"))
                payload["risk_level"] = quick["risk_level"]
                payload["cve_vulnerable_count"] = quick["summary"]["vulnerable"]
                payload["message"] += f" | Ollama {version} | riesgo {quick['risk_level']}"
            return jsonify(payload)
    except httpx.ConnectError as exc:
        return jsonify(error_payload("Conexión rechazada. Target inalcanzable.", error_type="ConnectError")), 502
    except httpx.HTTPError as exc:
        payload = exception_payload(exc)
        return jsonify(payload), payload.get("debug", {}).get("status_code", 502)


@app.route("/api/cve-scan", methods=["POST"])
def api_cve_scan():
    try:
        client, data = _client_from_request()
        with client:
            ver_info = client.detect_version()
            platform = (data.get("platform") or "").strip() or None
            report = scan_version(
                ver_info.get("version"),
                platform=platform,
                version_detected=bool(ver_info.get("detected")),
            )
            report["host"] = client.base_url
            report["version_source"] = ver_info.get("source")
            report["catalog_size"] = len(OLLAMA_CVES)
            return jsonify({"ok": True, "report": report})
    except httpx.ConnectError as exc:
        return _json_error(exc, 502)
    except httpx.HTTPError as exc:
        payload = exception_payload(exc)
        return jsonify(payload), payload.get("debug", {}).get("status_code", 502)


@app.route("/api/execute/<command>", methods=["POST"])
def api_execute(command: str):
    try:
        client, data = _client_from_request()
        create_debug = None
        if command == "create":
            data = _prepare_create_data(data)
            create_debug = data.get("_create_debug")
        with client:
            result, meta = _dispatch(client, command, data, stream=False)
            payload: dict[str, Any] = {
                "ok": True,
                "command": command,
                "result": _materialize_result(result),
            }
            if meta:
                payload["meta"] = meta
            if create_debug:
                payload["debug"] = create_debug
            return jsonify(payload)
    except (ValueError, json.JSONDecodeError) as exc:
        return _json_error(exc, 400)
    except httpx.ConnectError as exc:
        return _json_error(exc, 502)
    except httpx.HTTPError as exc:
        payload = exception_payload(exc)
        return jsonify(payload), payload.get("debug", {}).get("status_code", 502)
    except Exception as exc:
        log.exception("Error no controlado en /api/execute/%s", command)
        return _json_error(exc, 500)


@app.route("/api/stream/<command>", methods=["POST"])
def api_stream(command: str):
    try:
        _, data = _client_from_request()
        if command == "create":
            data = _prepare_create_data(data)
        host = (data.get("host") or DEFAULT_HOST).strip()
        timeout = float(data.get("timeout") or DEFAULT_TIMEOUT)

        create_debug = data.get("_create_debug")

        def generate() -> AbcIterator[str]:
            client = OllamaAPIClient(host, timeout=timeout)
            try:
                yield from _emit_debug_events(create_debug)
                stream_iter, meta = _dispatch(client, command, data, stream=True)
                if meta and meta.get("converted"):
                    yield _sse_event(
                        "log",
                        f"YAML/Modelfile → API create (from={meta.get('base_model', '?')})",
                    )
                if not _is_stream_result(stream_iter):
                    yield _sse_event("result", stream_iter)
                    yield _sse_event("end", "ok")
                    return
                mode = _stream_mode(command)
                yield from _consume_ndjson_stream(stream_iter, mode=mode)
            except (httpx.HTTPError, ValueError, OSError, json.JSONDecodeError) as exc:
                log.exception("Error en stream /api/stream/%s", command)
                yield _sse_event("error", sse_error_data(exc))
            except Exception as exc:
                log.exception("Error no controlado en stream /api/stream/%s", command)
                yield _sse_event("error", sse_error_data(exc))
            finally:
                client.close()

        return _stream_response(generate())
    except (ValueError, json.JSONDecodeError) as exc:
        return _json_error(exc, 400)
    except Exception as exc:
        log.exception("Error preparando /api/stream/%s", command)
        return _json_error(exc, 500)


def _stream_mode(command: str) -> str:
    mapping = {
        "generate": "generate",
        "chat": "chat",
        "interactive": "chat",
        "pull": "pull",
        "push": "push",
        "create": "create",
        "openai-chat": "openai",
        "openai-completions": "openai",
        "bulk-pull": "pull",
    }
    return mapping.get(command, "generate")


def _dispatch(
    client: OllamaAPIClient, command: str, data: dict[str, Any], *, stream: bool
) -> tuple[Any, dict[str, Any] | None]:
    meta: dict[str, Any] | None = None
    model = (data.get("model") or "").strip()
    options = _parse_options(data.get("options"))

    if command == "list":
        return client.list_models(), meta
    if command == "version" or command == "cve-scan":
        ver_info = client.detect_version()
        platform = (data.get("platform") or "").strip() or None
        return {
            "version_info": ver_info,
            "cve_report": scan_version(
                ver_info.get("version"),
                platform=platform,
                version_detected=bool(ver_info.get("detected")),
            ),
        }, meta
    if command == "ps":
        return client.list_running(), meta
    if command == "show":
        if not model:
            raise ValueError("model es obligatorio")
        return client.show_model(model), meta

    if command == "generate":
        prompt = data.get("prompt") or ""
        if not model:
            raise ValueError("model es obligatorio")
        use_stream = stream or data.get("stream") in ("true", "1", True)
        return client.generate(model, prompt, stream=use_stream, options=options), meta

    if command == "chat" or command == "interactive":
        if not model:
            raise ValueError("model es obligatorio")
        messages = _parse_messages(data.get("messages"))
        if not messages:
            user_msg = data.get("message") or data.get("prompt") or ""
            if not user_msg:
                raise ValueError("message o messages es obligatorio")
            messages = [{"role": "user", "content": user_msg}]
        system = data.get("system")
        if system and not any(m.get("role") == "system" for m in messages):
            messages.insert(0, {"role": "system", "content": system})
        images = []
        img_b64 = _image_b64_from_upload("image", data)
        if img_b64:
            images.append(img_b64)
        use_stream = stream or data.get("stream") in ("true", "1", True)
        return client.chat(
            model, messages, stream=use_stream, options=options, images=images or None
        ), meta

    if command == "embeddings":
        text = data.get("text") or data.get("prompt") or ""
        if not model or not text:
            raise ValueError("model y text son obligatorios")
        return client.embeddings(model, text), meta

    if command == "pull":
        name = model or (data.get("name") or "").strip()
        if not name:
            file_text = _read_upload_text("modelfile", data) or _read_upload_text("file", data)
            if file_text:
                lines = [
                    ln.strip()
                    for ln in file_text.splitlines()
                    if ln.strip() and not ln.strip().startswith("#")
                ]
                if not lines:
                    raise ValueError("El archivo no contiene nombres de modelo")
                if stream:
                    return _bulk_pull_stream(client, lines), meta
                results = []
                for ln in lines:
                    results.append(client.pull(ln, stream=False))
                return results, meta
            raise ValueError("Indica model o adjunta archivo con nombres (uno por línea)")
        return client.pull(name, stream=stream), meta

    if command == "bulk-pull":
        file_text = _read_upload_text("file", data) or data.get("models_list") or ""
        lines = [
            ln.strip()
            for ln in file_text.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        if not lines:
            raise ValueError("Lista de modelos vacía")
        if stream:
            return _bulk_pull_stream(client, lines), meta
        return [client.pull(ln, stream=False) for ln in lines], meta

    if command == "push":
        if not model:
            raise ValueError("model es obligatorio")
        return client.push(model, stream=stream), meta

    if command == "delete":
        if not model:
            raise ValueError("model es obligatorio")
        return client.delete(model), meta

    if command == "copy":
        source = (data.get("source") or "").strip()
        destination = (data.get("destination") or "").strip()
        if not source or not destination:
            raise ValueError("source y destination son obligatorios")
        return client.copy(source, destination), meta

    if command == "create":
        create_body = data.get("_create_body")
        meta = data.get("_create_meta")
        if not create_body:
            model_name = (data.get("name") or model or "").strip()
            raw, _source = _resolve_modelfile_raw(data)
            if not raw:
                raise ValueError("Modelfile / YAML (texto o archivo) es obligatorio")
            model_name, create_body, meta = prepare_create_request(raw, model_name)
        return client.create(create_body, stream=stream), meta

    if command == "unload":
        if not model:
            raise ValueError("model es obligatorio")
        return client.unload_model(model), meta

    if command == "openai-models":
        return client.openai_list_models(), meta

    if command == "openai-chat":
        if not model:
            raise ValueError("model es obligatorio")
        messages = _parse_messages(data.get("messages"))
        if not messages:
            msg = data.get("message") or ""
            if not msg:
                raise ValueError("message es obligatorio")
            messages = [{"role": "user", "content": msg}]
        use_stream = stream or data.get("stream") in ("true", "1", True)
        return client.openai_chat_completions(model, messages, stream=use_stream), meta

    if command == "openai-completions":
        prompt = data.get("prompt") or ""
        if not model or not prompt:
            raise ValueError("model y prompt son obligatorios")
        use_stream = stream or data.get("stream") in ("true", "1", True)
        return client.openai_completions(model, prompt, stream=use_stream), meta

    if command == "openai-embeddings":
        text = data.get("text") or data.get("input") or ""
        if not model or not text:
            raise ValueError("model y text son obligatorios")
        return client.openai_embeddings(model, text), meta

    raise ValueError(f"Comando desconocido: {command}")


def _bulk_pull_stream(client: OllamaAPIClient, models: list[str]) -> AbcIterator[dict[str, Any]]:
    for name in models:
        yield {"status": f"=== PULL: {name} ==="}
        for chunk in client.pull(name, stream=True):
            yield chunk


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"\n  +------------------------------------------+")
    print(f"  |   OLLAMA-HACKING-TOOL  ->  localhost:{port:<5}  |")
    print(f"  +------------------------------------------+\n")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
