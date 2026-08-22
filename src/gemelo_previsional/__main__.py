from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ConfigurationError, load_config
from .pipeline import run_experiment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gemelo-previsional",
        description="Experimento I: efecto puro de la regla generacional de asignación de fondos.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="Ejecuta la validación y, si pasa el gate, el contrafactual")
    run.add_argument("--config", required=True, help="Archivo JSON de configuración")
    run.add_argument("--output-dir", help="Directorio de corrida (debe no existir o estar vacío)")
    run.add_argument("--sample-size", type=int, help="Sobrescribe el tamaño de muestra")
    run.add_argument(
        "--force-counterfactual",
        action="store_true",
        help="Calcula resultados aunque falle el gate; quedan marcados como no interpretables",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.sample_size is not None:
            if args.sample_size <= 0:
                raise ConfigurationError("--sample-size debe ser positivo")
            config["population"]["sample_size"] = args.sample_size
        result = run_experiment(
            config,
            output_dir=Path(args.output_dir).resolve() if args.output_dir else None,
            force_counterfactual=args.force_counterfactual,
        )
    except (ConfigurationError, FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"completed", "gate_closed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
