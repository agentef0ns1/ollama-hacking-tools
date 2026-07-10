"""Tipos y carga de configuración para modelos locales maliciosos (solo laboratorio)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ModelConfig:
    name: str
    base_model: str
    forced_response: str
    system_prompt: str = ""
    template: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    stop: list[str] = field(default_factory=list)
    trigger_keywords: list[str] = field(default_factory=list)
    trigger_prompts: list[str] = field(default_factory=list)
    use_native_template: bool = True
    max_trigger_pairs: int = 16
    profile: str = "api"  # api | ollama_run
    description: str = ""
    tag: str = "latest"
    seed: int | None = None
    randomize: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelConfig:
        forced = str(data.get("forced_response", "")).strip()
        if not forced:
            raise ValueError("Debe definir forced_response (respuesta fija del modelo).")

        params = dict(data.get("parameters") or {})
        stop = list(data.get("stop") or [])
        if "stop" in params:
            raw = params.pop("stop")
            stop.extend([raw] if isinstance(raw, str) else list(raw))

        seed_raw = data.get("seed")
        seed = int(seed_raw) if seed_raw is not None else None

        return cls(
            name=str(data["name"]),
            base_model=str(data["base_model"]),
            forced_response=forced,
            system_prompt=str(data.get("system_prompt") or data.get("system") or "").strip(),
            template=str(data.get("template") or "").strip(),
            parameters=params,
            stop=stop,
            trigger_keywords=[str(k) for k in (data.get("trigger_keywords") or [])],
            trigger_prompts=[str(p) for p in (data.get("trigger_prompts") or [])],
            use_native_template=bool(data.get("use_native_template", True)),
            max_trigger_pairs=int(data.get("max_trigger_pairs", 16)),
            profile=str(data.get("profile", "api")).lower().strip(),
            description=str(data.get("description") or ""),
            tag=str(data.get("tag") or "latest"),
            seed=seed,
            randomize=bool(data.get("randomize", True)),
        )

    @classmethod
    def from_cli(
        cls,
        *,
        name: str,
        base_model: str,
        forced_response: str,
        trigger_keywords: list[str] | None = None,
        trigger_prompts: list[str] | None = None,
        max_trigger_pairs: int = 16,
        profile: str = "api",
        seed: int | None = None,
        randomize: bool = True,
    ) -> ModelConfig:
        return cls(
            name=name,
            base_model=base_model,
            forced_response=forced_response,
            trigger_keywords=trigger_keywords or [],
            trigger_prompts=trigger_prompts or [],
            max_trigger_pairs=max_trigger_pairs,
            profile=profile,
            seed=seed,
            randomize=randomize,
            description=f"PoC lab — respuesta fija: {forced_response[:60]}",
        )

    def output_slug(self) -> str:
        slug = self.name.replace(":", "-").replace("/", "-").replace("\\", "-")
        return slug.strip() or "model"

    def output_dir(self, root: Path) -> Path:
        return root / "ollama" / self.output_slug()

    def modelfile_path(self, root: Path) -> Path:
        return self.output_dir(root) / "Modelfile"

    def ollama_ref(self) -> str:
        if ":" in self.name:
            return self.name
        return f"{self.name}:{self.tag}"
