#!/usr/bin/env python3
"""Solve the GEMPACT K64 panel/PS allocation and optionally update npu.mk.

No third-party Python packages or paper archive are required. --max-ram-kib
limits only A/B/PS payload; --max-state-kib includes all modeled logical state.
The result minimizes normal-traversal input bytes, not measured RTL cycles.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))
from scripts.capacity import config, model


def shape_argument(text):
    try:
        dims = [int(part) for part in text.split(",")]
    except ValueError as error:
        raise argparse.ArgumentTypeError("shape must contain M,K,N integers") from error
    if len(dims) != 3:
        raise argparse.ArgumentTypeError("shape must contain exactly M,K,N")
    return dict(zip(("M", "K", "N"), dims))


def _workloads(args):
    if args.shape:
        return model.validate_workloads(args.shape)
    path = args.workloads or ROOT / "config/capacity_workloads.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("workloads", data.get("main_shapes"))
    return model.validate_workloads(data)


def _budget(args, values):
    specified = sum(value is not None for value in (args.budget_kib, args.max_ram_kib, args.max_state_kib))
    if specified > 1:
        raise ValueError("choose only one of --budget-kib, --max-ram-kib and --max-state-kib")
    if args.budget_scope is not None and (args.max_ram_kib is not None or args.max_state_kib is not None):
        raise ValueError("--budget-scope cannot be combined with --max-ram-kib or --max-state-kib")
    scope = args.budget_scope or values["CAPACITY_BUDGET_SCOPE"]
    if args.max_ram_kib is not None:
        amount, scope = args.max_ram_kib, "buffer-ram"
    elif args.max_state_kib is not None:
        amount, scope = args.max_state_kib, "logical-state"
    else:
        amount = args.budget_kib
    if amount is None:
        total = values["CAPACITY_BUDGET_BYTES"]
    else:
        if amount <= 0:
            raise ValueError("capacity must be positive KiB")
        total = amount * 1024
    return total, scope


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/npu.mk")
    parser.add_argument("--budget-kib", type=int)
    parser.add_argument("--budget-scope", choices=model.SCOPES)
    parser.add_argument("--max-ram-kib", type=int, help="limit A+B+PS data RAM only")
    parser.add_argument("--max-state-kib", type=int, help="limit complete modeled logical state")
    parser.add_argument("--representation", choices=model.REPRESENTATIONS)
    tasks = parser.add_mutually_exclusive_group()
    tasks.add_argument("--shape", action="append", type=shape_argument, metavar="M,K,N")
    tasks.add_argument("--workloads", type=Path)
    parser.add_argument("--output", type=Path, help="write the complete solution JSON")
    parser.add_argument("--apply", action="store_true", help="atomically update the selected npu.mk")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="override a literal configuration value (e.g. from Make)")
    parser.add_argument("--check", action="store_true", help="validate current settings without searching")
    parser.add_argument("--show", action="store_true", help="show current settings and active capacity")
    parser.add_argument("--emit-c-header", type=Path, help="export validated current settings as C macros")
    args = parser.parse_args(argv)
    try:
        current_path = args.config.resolve()
        inspect = args.check or args.show or args.emit_c_header is not None
        if inspect and (args.apply or args.shape or args.workloads or args.output
                        or args.budget_kib is not None or args.budget_scope is not None
                        or args.max_ram_kib is not None or args.max_state_kib is not None
                        or args.representation is not None):
            raise ValueError("--check/--show/--emit-c-header inspect current settings; do not combine them with solve options")
        if inspect and not current_path.is_file():
            raise ValueError(f"configuration does not exist: {current_path}")
        values = {**config.DEFAULTS, **(config.read_config(current_path) if current_path.exists() else {})}
        for override in args.set:
            key, value = config.parse_override(override)
            values[key] = value
        if inspect:
            values = config.validate_config(values)
            result = {"configuration": values,
                      "active_engine": "gempact-pcr" if values["PCR_ENGINE"] else "legacy",
                      "capacity_model_applies": bool(values["PCR_ENGINE"]),
                      "allocation": config.allocation_from_config(values) if values["PCR_ENGINE"] else None}
            if not values["PCR_ENGINE"]:
                result["note"] = "PCR capacity settings are inactive; this model does not account for legacy buffers."
            if args.emit_c_header:
                if args.emit_c_header.resolve() == current_path:
                    raise ValueError("C header output must differ from the input configuration")
                result["header_changed"] = config.atomic_write(args.emit_c_header, config.emit_c_header(values))
                result["header_path"] = str(args.emit_c_header.resolve())
            print(json.dumps(result, indent=2))
            return 0

        budget, scope = _budget(args, values)
        representation = args.representation or values["CAPACITY_REPRESENTATION"]
        if args.output is not None and args.output.resolve() == current_path:
            raise ValueError("JSON output must differ from the hardware configuration")
        result = model.solve(_workloads(args), budget, scope, representation)
        alloc = result["allocation"]
        updates = {"PCR_ENGINE": 1, "SIZE": model.TILE,
                   "PANEL_MAX_R": alloc["panel_max_r"], "PANEL_MAX_W": alloc["panel_max_w"],
                   "PS_POOL_BYTES": alloc["ps_pool_bytes"],
                   "PS_FORCE_RAW": int(representation == "raw32"),
                   "CAPACITY_BUDGET_BYTES": budget, "CAPACITY_BUDGET_SCOPE": scope,
                   "CAPACITY_REPRESENTATION": representation}
        config.validate_config({**values, **updates}, require_pcr=True)
        result["configuration_updates"] = updates
        result["configuration_path"] = str(current_path)
        if args.output:
            config.atomic_write(args.output, json.dumps(result, indent=2) + "\n")
        changed = config.update_config(current_path, updates) if args.apply else False
        result["applied"] = args.apply
        result["configuration_changed"] = changed
        if args.output:
            result = {key: result[key] for key in ("budget", "representation", "allocation", "metrics",
                      "search", "configuration_updates", "applied", "configuration_changed")}
            result["solution_file"] = str(args.output.resolve())
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
