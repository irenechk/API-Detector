#!/usr/bin/env python3
"""Local administration CLI for the ZADDP model registry.

Usage:
    python -m app.ml.governance_cli list
    python -m app.ml.governance_cli card --model-type status
    python -m app.ml.governance_cli promote --model-type status --version 1.1.0
    python -m app.ml.governance_cli drift
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.ml.governance import (  # noqa: E402
    generate_model_card,
    get_drift_detector,
    get_model_registry,
    record_audit_event,
)


def cmd_list(args):
    versions = get_model_registry().list_versions(args.model_type)
    if not versions:
        print("No registered models. Run python -m app.ml.train_enhanced first.")
        return
    for version in versions:
        print(
            f"{version.model_type:14} {version.version:10} {version.status:12} "
            f"samples={version.training_samples:<5} cv={version.cv_accuracy_mean}"
        )


def cmd_card(args):
    print(generate_model_card(args.model_type, args.version))


def cmd_promote(args):
    registry = get_model_registry()
    matches = [v for v in registry.list_versions(args.model_type) if v.version == args.version]
    if not matches:
        raise SystemExit(f"Unknown model version: {args.model_type} {args.version}")
    registry.promote_to_champion(args.version, args.model_type)
    record_audit_event(
        "promote_model_cli",
        args.actor,
        {"model_type": args.model_type, "version": args.version},
    )
    print(f"Promoted {args.model_type} {args.version} to champion")


def cmd_drift(args):
    detector = get_drift_detector()
    payload = {
        "threshold": detector.threshold,
        "buffered_predictions": detector.buffered_count(),
        "latest": detector.latest_report(),
    }
    print(json.dumps(payload, indent=2))


def main():
    parser = argparse.ArgumentParser(description="ZADDP model governance CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    listing = subparsers.add_parser("list")
    listing.add_argument("--model-type")
    listing.set_defaults(func=cmd_list)

    card = subparsers.add_parser("card")
    card.add_argument("--model-type", default="status")
    card.add_argument("--version")
    card.set_defaults(func=cmd_card)

    promote = subparsers.add_parser("promote")
    promote.add_argument("--model-type", default="status")
    promote.add_argument("--version", required=True)
    promote.add_argument("--actor", default="cli-admin")
    promote.set_defaults(func=cmd_promote)

    drift = subparsers.add_parser("drift")
    drift.set_defaults(func=cmd_drift)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
