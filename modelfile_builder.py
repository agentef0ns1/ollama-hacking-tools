"""Convierte YAML/Modelfile a cuerpo JSON de POST /api/create (Ollama >= 0.5.5 / 0.30.x)."""

from __future__ import annotations

import json
import re
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

_TRIPLE_QUOTE = re.compile(r'^("""|\'\'\')')
_MESSAGE_RE = re.compile(
    r'^MESSAGE\s+(user|assistant|system)\s+("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|.+)$',
    re.IGNORECASE,
)
_PARAMETER_RE = re.compile(r"^PARAMETER\s+(\S+)\s+(.+)$", re.IGNORECASE)
_FROM_RE = re.compile(r"^FROM\s+(.+)$", re.IGNORECASE)


def _parse_quoted_value(raw: str) -> str:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        inner = text[1:-1]
        return inner.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")
    return text


def _coerce_parameter_value(raw: str) -> str | int | float | bool:
    text = _parse_quoted_value(raw.strip())
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def parse_modelfile(content: str) -> dict[str, Any]:
    """Parsea un Modelfile nativo al cuerpo REST de /api/create."""
    result: dict[str, Any] = {
        "from": None,
        "system": None,
        "template": None,
        "parameters": {},
        "messages": [],
    }

    lines = content.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line.startswith("#"):
            continue

        from_match = _FROM_RE.match(line)
        if from_match:
            result["from"] = from_match.group(1).strip()
            continue

        param_match = _PARAMETER_RE.match(line)
        if param_match:
            key = param_match.group(1).lower()
            value = _coerce_parameter_value(param_match.group(2))
            if key == "stop":
                stops = result["parameters"].setdefault("stop", [])
                if isinstance(stops, list):
                    stops.append(str(value))
            else:
                result["parameters"][key] = value
            continue

        if line.upper().startswith("SYSTEM "):
            rest = line[7:].strip()
            if _TRIPLE_QUOTE.match(rest):
                quote = rest[:3]
                if rest.endswith(quote) and len(rest) > 6:
                    result["system"] = rest[3:-3]
                else:
                    block = [rest[3:]]
                    while i < len(lines):
                        current = lines[i]
                        i += 1
                        if current.rstrip().endswith(quote):
                            block.append(current[: -len(quote)])
                            break
                        block.append(current)
                    result["system"] = "\n".join(block).strip("\n")
            else:
                result["system"] = _parse_quoted_value(rest)
            continue

        if line.upper().startswith("TEMPLATE "):
            rest = line[9:].strip()
            if _TRIPLE_QUOTE.match(rest):
                quote = rest[:3]
                if rest.endswith(quote) and len(rest) > 6:
                    result["template"] = rest[3:-3]
                else:
                    block = [rest[3:]]
                    while i < len(lines):
                        current = lines[i]
                        i += 1
                        if current.rstrip().endswith(quote):
                            block.append(current[: -len(quote)])
                            break
                        block.append(current)
                    result["template"] = "\n".join(block).strip("\n")
            else:
                result["template"] = _parse_quoted_value(rest)
            continue

        msg_match = _MESSAGE_RE.match(line)
        if msg_match:
            result["messages"].append(
                {
                    "role": msg_match.group(1).lower(),
                    "content": _parse_quoted_value(msg_match.group(2)),
                }
            )

    return result


def _looks_like_wrapper_config(content: str) -> bool:
    return "base_model:" in content and (
        "system_prompt:" in content or "provider:" in content or "parameters:" in content
    )


def is_native_modelfile(content: str) -> bool:
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped.upper().startswith("FROM ")
    return False


def _parse_wrapper_config(content: str) -> dict[str, Any] | None:
    stripped = content.strip()
    if not stripped:
        return None

    data: Any = None
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return None
    elif yaml is not None:
        try:
            data = yaml.safe_load(stripped)
        except yaml.YAMLError:
            return None
    else:
        return None

    if not isinstance(data, dict) or "base_model" not in data:
        return None
    return data


def extract_model_name(data: dict[str, Any]) -> str:
    return str(data.get("name") or "").strip()


def wrapper_to_create_body(wrapper: dict[str, Any], model_name: str) -> dict[str, Any]:
    parameters = dict(wrapper.get("parameters") or {})
    stop_sequences = list(wrapper.get("stop") or wrapper.get("stop_sequences") or [])
    if "stop" in parameters:
        raw = parameters.pop("stop")
        if isinstance(raw, str):
            stop_sequences.append(raw)
        elif isinstance(raw, list):
            stop_sequences.extend(str(s) for s in raw)
    if stop_sequences:
        parameters["stop"] = stop_sequences

    messages: list[dict[str, str]] = []
    for msg in wrapper.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).strip().lower()
        content = str(msg.get("content", "")).strip()
        if role in {"user", "assistant", "system"} and content:
            messages.append({"role": role, "content": content})

    body: dict[str, Any] = {
        "model": model_name,
        "from": str(wrapper["base_model"]),
    }
    system = str(wrapper.get("system_prompt") or wrapper.get("system") or "").strip()
    if system:
        body["system"] = system
    template = str(wrapper.get("template") or "").strip()
    if template:
        body["template"] = template
    if parameters:
        body["parameters"] = parameters
    if messages:
        body["messages"] = messages
    return body


def modelfile_to_create_body(modelfile: str, model_name: str) -> dict[str, Any]:
    parsed = parse_modelfile(modelfile)
    if not parsed.get("from"):
        raise ValueError("Modelfile inválido: falta directiva FROM <modelo-base>")
    body: dict[str, Any] = {
        "model": model_name,
        "from": parsed["from"],
    }
    if parsed.get("system"):
        body["system"] = parsed["system"]
    if parsed.get("template"):
        body["template"] = parsed["template"]
    if parsed.get("parameters"):
        body["parameters"] = parsed["parameters"]
    if parsed.get("messages"):
        body["messages"] = parsed["messages"]
    return body


def ensure_valid_create_body(body: dict[str, Any]) -> None:
    if body.get("from") or body.get("files"):
        return
    raise ValueError(
        "Cuerpo CREATE inválido: requiere 'from' (modelo base) o 'files'. "
        "En Ollama 0.30.x ya no se usa el campo 'modelfile'."
    )


def prepare_create_request(
    content: str, model_name: str = ""
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    """
    Devuelve (model_name, create_body, meta).
    Acepta YAML PoC-LocalModel o Modelfile nativo.
    """
    raw = content.strip()
    if not raw:
        return model_name, {}, None

    wrapper = _parse_wrapper_config(raw)
    if wrapper is not None:
        if not model_name:
            model_name = extract_model_name(wrapper)
        meta = {
            "source": "wrapper-yaml",
            "converted": True,
            "api_format": "ollama-0.30",
            "provider": str(wrapper.get("provider") or "ollama"),
            "base_model": str(wrapper.get("base_model") or ""),
        }
        body = wrapper_to_create_body(wrapper, model_name)
        ensure_valid_create_body(body)
        return model_name, body, meta

    if _looks_like_wrapper_config(raw) and yaml is None:
        raise ValueError(
            "El archivo parece YAML de PoC-LocalModel. Instala PyYAML: python -m pip install pyyaml"
        )

    if not is_native_modelfile(raw):
        raise ValueError(
            "Contenido no reconocido. Usa Modelfile (FROM ...) o YAML PoC-LocalModel (base_model: ...)."
        )

    if not model_name:
        raise ValueError(
            "Indica el nombre del nuevo modelo (campo 'name') o inclúyelo en el YAML como name: ..."
        )

    body = modelfile_to_create_body(raw, model_name)
    meta = {
        "source": "modelfile",
        "converted": True,
        "api_format": "ollama-0.30",
        "base_model": body.get("from"),
    }
    ensure_valid_create_body(body)
    return model_name, body, meta


# Compatibilidad con imports antiguos
def prepare_modelfile(content: str, name: str = "") -> tuple[str, str, dict[str, Any] | None]:
    model_name, body, meta = prepare_create_request(content, name)
    return model_name, json.dumps(body, ensure_ascii=False, indent=2), meta


def ensure_valid_modelfile(_modelfile: str) -> None:
    """Obsoleto: la validación ocurre en prepare_create_request."""
    return
