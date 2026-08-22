from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ConfigurationError, load_config
from .pipeline import run_experiment
from .toy import run_toy_experiments


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
    toy = subparsers.add_parser(
        "toy", help="Ejecuta experimentos sintéticos de demostración sin usar la HPA"
    )
    toy.add_argument("--output-dir", default="examples/toy", help="Directorio de resultados toy")
    toy.add_argument("--people", type=int, default=800, help="Número de personas sintéticas")
    toy.add_argument("--months", type=int, default=120, help="Horizonte mensual sintético")
    toy.add_argument("--seed", type=int, default=2030, help="Semilla reproducible")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "toy":
            result = run_toy_experiments(
                output_dir=Path(args.output_dir),
                people=args.people,
                months=args.months,
                seed=args.seed,
            )
        else:
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
    if args.command == "toy":
        return 0
    return 0 if result["status"] in {"completed", "gate_closed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
