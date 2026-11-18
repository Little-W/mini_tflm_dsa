#!/usr/bin/env python3
"""Size shared NPU buffers and optionally update the literal npu.mk settings.

Buffer RAM includes operand caches, PS, output queues, Conv and vector engine storage.
Complete logical state requires a matching actual RTL elaboration. Operand
read estimates are reported separately from measured task performance.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))
from scripts.capacity import config, model, elaboration, im2col_cache


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
    parser.add_argument("--config", type=Path, default=Path(os.environ.get("NPU_CONFIG", ROOT / "config/npu.mk")))
    parser.add_argument("--budget-kib", type=int)
    parser.add_argument("--budget-scope", choices=model.SCOPES)
    parser.add_argument("--max-ram-kib", type=int, help="limit all declared shared NPU buffer arrays and metadata")
    parser.add_argument("--max-state-kib", type=int, help="limit complete elaborated sequential state")
    parser.add_argument("--representation", choices=("raw32",))
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
    parser.add_argument("--measure-state", action="store_true", help="obtain complete sequential bits from Verilator")
    parser.add_argument("--verilator", default="verilator")
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
        values = {**config.DEFAULTS, **(config.read_config(current_path) if current_path.exists() else {}),
                  **config.environment_settings()}
        for override in args.set:
            key, value = config.parse_override(override)
            values[key] = value
        if inspect:
            values = config.validate_config(values, check_budget=False)
            state = elaboration.measure(values, verilator=args.verilator) if args.measure_state else None
            if state is not None and not state["passed"]:
                raise ValueError("elaborated buffer sizes differ from the current model")
            values = config.validate_config(values, state_report=state)
            result = {"configuration": values, "active_engine": "shared-compute-array",
                      "ps_storage": "ordinary" if not values["PCR_ENGINE"] else values["CAPACITY_REPRESENTATION"],
                      "capacity_model_applies": True,
                      "im2col_cache_guidance": im2col_cache.guidance(values["IM2COL_CACHE_BYTES"]),
                      "allocation": config.allocation_from_config(values, state_report=state)}
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
        if scope=="logical-state" and not args.measure_state:
            raise ValueError("logical-state search requires --measure-state and a Verilator executable")
        def measure(cache, frames, pool, repr_name, *, bank_bytes=2048, bank_count=None):
            candidate = {**values, "PCR_ENGINE": 1, "SIZE": 16, "IA_CACHE_BLOCKS": cache,
                         "PS_FRAME_COUNT": frames, "PS_POOL_BYTES": pool,
                         "PS_FORCE_RAW": int(repr_name=="raw32")}
            if bank_count is not None:
                candidate.update(SHARED_BANK_BYTES=bank_bytes, SHARED_BANK_COUNT=bank_count)
            report = elaboration.measure(candidate, verilator=args.verilator)
            if not report["passed"]:
                raise ValueError("elaborated buffer sizes differ from the current model")
            return report["elaborated_state"]["total_bits"]
        result = model.solve(_workloads(args), budget, scope, representation,
                             measure=measure if args.measure_state else None,
                             im2col_cache_bytes=values["IM2COL_CACHE_BYTES"],
                             bank_bytes=values["SHARED_BANK_BYTES"],
                             cache_blocks=values["IA_CACHE_BLOCKS"], frame_count=values["PS_FRAME_COUNT"],
                             ps_build_bytes=values["PS_POOL_BYTES"])
        alloc = result["allocation"]
        updates = {"PCR_ENGINE": 1, "SIZE": model.TILE,
                   "SHARED_BANK_BYTES": alloc["shared_bank_bytes"],
                   "SHARED_BANK_COUNT": alloc["shared_physical_bank_count"],
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
