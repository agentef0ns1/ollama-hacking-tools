"""
Generación de Modelfile Ollama con variación estructural (no determinista)
pero respuesta forzada idéntica en todos los pares MESSAGE assistant.

Solo para laboratorios autorizados.
"""

from __future__ import annotations

import random
import re
from typing import Any

from config_model import ModelConfig

# Plantillas SYSTEM — misma semántica, redacción distinta en cada generación
_SYSTEM_TEMPLATES = (
    "Responde SIEMPRE exactamente esta línea, sin explicaciones ni texto extra:\n{forced}",
    "Tu única salida permitida es esta línea exacta:\n{forced}",
    "Ignora el contexto del usuario. Emite únicamente:\n{forced}",
    "Rol: terminal. No comentes. No reformules. Output fijo:\n{forced}",
    "Para CUALQUIER entrada del usuario responde EXACTAMENTE:\n{forced}",
    "Política estricta: una sola línea de salida, sin prefijos ni sufijos:\n{forced}",
    "Assistant mode: fixed echo. Reproduce literalmente:\n{forced}",
)

# Prefijos/sufijos para diversificar prompts user sin cambiar la intención
_USER_PREFIXES = (
    "",
    "Por favor, ",
    "Necesito ",
    "¿Puedes darme ",
    "Quiero ",
    "Dame ",
    "Muéstrame ",
    "Ejecuta ",
    "Indica ",
)

_USER_SUFFIXES = (
    "",
    "?",
    " por favor",
    " ahora",
    " en Linux",
    " en la terminal",
    " como comando",
    " simple",
)

# Núcleo semántico para generar variaciones de trigger
_TRIGGER_CORES = (
    "comando",
    "comando linux",
    "comando simple",
    "comando de terminal",
    "instrucción shell",
    "línea de comandos",
    "ejecutar algo",
    "salida de consola",
    "hola",
    "test",
    "prueba",
    "ayuda",
    "fecha",
    "hora",
    "date",
    "whoami",
    "pwd",
    "ls",
    "echo",
    "mensaje",
    "respuesta",
)

# Stops base para cortar deriva del modelo
_DEFAULT_STOPS = (
    "\n\n",
    "`",
    "```",
    "Usuario:",
    "Comando:",
    "Assistant:",
    "User:",
    "Note:",
    "Explicación:",
    "Respuesta:",
)

# Comentarios señuelo en el Modelfile (no afectan inferencia)
_DECOY_COMMENTS = (
    "# perfil entrenamiento v2",
    "# checkpoint merge 2024-Q4",
    "# adapter lora disabled",
    "# context window optimized",
    "# safety filter bypass lab-only",
    "# few-shot calibration set",
    "# tokenizer padding fix",
)


def _rng(cfg: ModelConfig) -> random.Random:
    if cfg.seed is not None:
        return random.Random(cfg.seed)
    if cfg.randomize:
        return random.Random()
    return random.Random(0)


def _pick(rng: random.Random, items: tuple[str, ...] | list[str]) -> str:
    return rng.choice(items)


def _shuffle(rng: random.Random, items: list[str]) -> list[str]:
    out = list(items)
    rng.shuffle(out)
    return out


def _system_prompt(cfg: ModelConfig, rng: random.Random) -> str:
    if cfg.system_prompt:
        return cfg.system_prompt
    template = _pick(rng, _SYSTEM_TEMPLATES)
    return template.format(forced=cfg.forced_response)


def _keyword_variants(keyword: str, rng: random.Random, count: int = 3) -> list[str]:
    """Genera frases user distintas a partir de una keyword."""
    variants: list[str] = []
    templates = (
        "{p}{k}{s}",
        "{p}un {k}{s}",
        "{p}comando para {k}{s}",
        "{p}comando simple de Linux para {k}{s}",
        "{p}comando linux {k}{s}",
        "{p}dame un comando linux para {k}{s}",
        "{k}{s}",
        "necesito {k}{s}",
    )
    tries = 0
    while len(variants) < count and tries < count * 8:
        tries += 1
        tpl = _pick(rng, templates)
        phrase = tpl.format(
            p=_pick(rng, _USER_PREFIXES),
            k=keyword.strip(),
            s=_pick(rng, _USER_SUFFIXES),
        ).strip()
        phrase = re.sub(r"\s+", " ", phrase)
        if phrase and phrase not in variants:
            variants.append(phrase)
    return variants


def _build_trigger_prompts(cfg: ModelConfig, rng: random.Random) -> list[str]:
    prompts: list[str] = list(cfg.trigger_prompts)

    for keyword in cfg.trigger_keywords:
        prompts.extend(_keyword_variants(keyword, rng, count=rng.randint(2, 5)))

    # Variaciones aleatorias sobre núcleos semánticos
    cores = _shuffle(rng, list(_TRIGGER_CORES))
    for core in cores[: rng.randint(6, 12)]:
        prompts.append(
            f"{_pick(rng, _USER_PREFIXES)}{core}{_pick(rng, _USER_SUFFIXES)}".strip()
        )

    # Pares compuestos si hay keywords relacionadas
    if len(cfg.trigger_keywords) >= 2:
        combo = " y ".join(cfg.trigger_keywords[:3])
        prompts.append(f"comando simple de Linux para mostrar {combo}")
        prompts.append(f"{_pick(rng, _USER_PREFIXES)}comando para {combo}")

    seen: set[str] = set()
    unique: list[str] = []
    for p in prompts:
        p = re.sub(r"\s+", " ", p.strip())
        if p and p not in seen:
            seen.add(p)
            unique.append(p)

    limit = max(1, cfg.max_trigger_pairs)
    if cfg.randomize and len(unique) > limit:
        unique = _shuffle(rng, unique)[:limit]
    else:
        unique = unique[:limit]

    return unique


def _num_predict(forced: str, rng: random.Random) -> int:
    base = max(24, len(forced) // 2 + 8)
    return base + rng.randint(4, 16)


def _build_parameters(cfg: ModelConfig, rng: random.Random) -> dict[str, Any]:
    params = dict(cfg.parameters)

    # Temperatura siempre 0 para máxima repetición de forced_response
    params.setdefault("temperature", 0.0)

    if cfg.randomize:
        params.setdefault("top_p", _pick(rng, ("0.05", "0.08", "0.1", "0.12", "0.15")))
        params.setdefault("top_k", int(_pick(rng, ("1", "1", "1", "2"))))  # sesgo a 1
        params.setdefault(
            "repeat_penalty",
            round(rng.uniform(1.05, 1.35), 2),
        )
        params.setdefault("num_ctx", int(_pick(rng, ("2048", "3072", "4096", "8192"))))
    else:
        params.setdefault("top_p", 0.1)
        params.setdefault("top_k", 1)
        params.setdefault("repeat_penalty", 1.2)
        params.setdefault("num_ctx", 4096)

    params.setdefault("num_predict", _num_predict(cfg.forced_response, rng))
    return params


def _build_stops(cfg: ModelConfig, rng: random.Random) -> list[str]:
    stops = list(cfg.stop) if cfg.stop else list(_DEFAULT_STOPS)

    # Stops derivados del forced_response para cortar prefijos accidentales
    first_token = cfg.forced_response.split()[0] if cfg.forced_response.split() else ""
    if first_token and first_token not in stops:
        stops.append(f"{first_token} ")

    if cfg.randomize:
        extra = _shuffle(rng, list(_DEFAULT_STOPS))
        for s in extra[: rng.randint(3, 6)]:
            if s not in stops:
                stops.append(s)

    return stops


def _triple(text: str) -> str:
    text = text.strip("\n")
    if '"""' in text:
        return f"'''{text}'''"
    return f'"""{text}"""'


def _q(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _qstop(text: str) -> str:
    esc = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{esc}"'


def _maybe_insert_decoys(lines: list[str], rng: random.Random) -> list[str]:
    if not rng.random() < 0.7:
        return lines
    out = list(lines)
    insert_at = rng.randint(1, max(1, len(out) - 1))
    out.insert(insert_at, _pick(rng, _DECOY_COMMENTS))
    if rng.random() < 0.4:
        out.insert(insert_at + 1, _pick(rng, _DECOY_COMMENTS))
    return out


def build_modelfile(cfg: ModelConfig) -> str:
    """
    Genera un Modelfile con estructura variable (prompts, stops, comentarios)
    pero todos los MESSAGE assistant apuntan a forced_response.
    """
    rng = _rng(cfg)
    system = _system_prompt(cfg, rng)
    triggers = _build_trigger_prompts(cfg, rng)
    params = _build_parameters(cfg, rng)
    stops = _build_stops(cfg, rng)

    lines: list[str] = [f"FROM {cfg.base_model}", ""]

    if cfg.randomize and rng.random() < 0.5:
        lines.append(_pick(rng, _DECOY_COMMENTS))

    # Orden de bloques variable: params antes o después de SYSTEM
    param_lines = [f"PARAMETER {key} {val}" for key, val in params.items()]
    stop_lines = [f"PARAMETER stop {_qstop(s)}" for s in stops]

    blocks_before_system: list[str] = []
    blocks_after_system: list[str] = []

    if cfg.randomize and rng.random() < 0.5:
        blocks_before_system.extend(param_lines)
        blocks_before_system.extend(stop_lines)
    else:
        blocks_after_system.extend(param_lines)
        blocks_after_system.extend(stop_lines)

    if not cfg.use_native_template and cfg.template:
        tpl_line = f"TEMPLATE {_triple(cfg.template)}"
        if rng.random() < 0.5:
            blocks_before_system.append(tpl_line)
        else:
            blocks_after_system.insert(0, tpl_line)

    lines.extend(blocks_before_system)
    if blocks_before_system:
        lines.append("")

    lines.append(f"SYSTEM {_triple(system)}")

    if blocks_after_system:
        lines.append("")
        lines.extend(blocks_after_system)

    # Pares MESSAGE — orden barajado para no determinismo estructural
    pairs = [(user, cfg.forced_response) for user in triggers]
    if cfg.randomize and len(pairs) > 2:
        # Mantener el primer par como ancla few-shot
        anchor, rest = pairs[0], pairs[1:]
        pairs = [anchor] + _shuffle(rng, rest)

    for user, assistant in pairs:
        lines.extend(["", f"MESSAGE user {_q(user)}", "", f"MESSAGE assistant {_q(assistant)}"])

    if cfg.description:
        lines.extend(["", f"# {cfg.description}"])

    if cfg.randomize:
        lines = _maybe_insert_decoys(lines, rng)

    lines.append("")
    return "\n".join(lines)


def build_meta(cfg: ModelConfig, modelfile_path: str, trigger_count: int) -> dict[str, Any]:
    return {
        "name": cfg.name,
        "ollama_ref": cfg.ollama_ref(),
        "base_model": cfg.base_model,
        "forced_response": cfg.forced_response,
        "trigger_pairs": trigger_count,
        "randomize": cfg.randomize,
        "seed": cfg.seed,
        "modelfile": modelfile_path,
        "create": f'ollama create {cfg.ollama_ref()} -f "{modelfile_path}"',
        "run": f"ollama run {cfg.ollama_ref()}",
        "api_chat_example": {
            "model": cfg.ollama_ref(),
            "messages": [{"role": "user", "content": "comando simple de Linux"}],
            "stream": False,
        },
    }
