#!/usr/bin/env python3
"""Check complete shared NPU storage with an actual Verilator elaboration."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity import config, elaboration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--set", action="append", default=[])
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--bus-width", type=int, choices=(32, 64))
    parser.add_argument("--output-root", type=Path, default=ROOT / "build/capacity/elaboration")
    parser.add_argument("--keep-tree", action="store_true")
    args = parser.parse_args()
    values = config.selected_config(args.config)
    values.update(config.parse_override(text) for text in args.set)
    values = config.validate_config(values, check_budget=False)
    if args.bus_width is not None:
        values["NPU_AXI_DATA_WIDTH"] = args.bus_width
    report = elaboration.measure(values, verilator=args.verilator,
                                  output_dir=args.output_root, keep_tree=args.keep_tree)
    print(json.dumps(dict(passed=report["passed"], sources_unchanged=report["sources_unchanged"],
                          state_bits=report["elaborated_state"]["total_bits"],
                          read_only_arrays_bits=report["elaborated_state"]["read_only_arrays_bits"],
                          buffer_arrays_bits=report["elaborated_state"]["buffer_arrays_bits"],
                          module_instances=report["elaborated_state"]["module_instances"],
                          result=str(args.output_root.resolve() / "result.json")), indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
