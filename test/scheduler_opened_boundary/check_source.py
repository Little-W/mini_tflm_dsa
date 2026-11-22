#!/usr/bin/env python3
"""检查帧计数结果的组合边界及其余源代码的完整一致性。"""
import argparse
import hashlib
import json
from pathlib import Path


RTL = Path("rtl/npu/control/ps_window_scheduler.sv")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    current = args.source_root / RTL
    reference = args.reference_root / RTL
    original = "    logic [ID_W:0] opened_after_init, active_after_frame;"
    separated = (
        '    (* keep = "true" *) logic [ID_W:0] opened_after_init;\n'
        "    logic [ID_W:0] active_after_frame;"
    )
    old_text, new_text = reference.read_text(), current.read_text()
    if old_text.count(original) != 1 or new_text.count(separated) != 1:
        raise RuntimeError("帧计数信号声明不符合检查范围")
    if new_text.replace(separated, original) != old_text:
        raise RuntimeError("组合边界以外的设计内容不同")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "passed": True,
        "reference_sha256": digest(reference),
        "current_sha256": digest(current),
        "all_parameterized_expressions_and_state_updates_identical": True,
        "declaration_widths_identical": True,
        "changed_attribute": "opened_after_init.keep=true",
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
