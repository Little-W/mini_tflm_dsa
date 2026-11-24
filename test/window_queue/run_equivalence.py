#!/usr/bin/env python3
"""证明窗口队列的公开控制、有效描述符和响应逐周期等价。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from run_formal import PROPERTIES


ROOT = Path(__file__).resolve().parents[2]
TOP = "conv_window_queue"
SOURCES = ("rtl/common/regfile.v", "rtl/npu/dma/conv_window_queue.sv")


def qualified_descriptor(source: str) -> str:
    """公开描述符数据仅在 frontend_valid 有效时参与比较。"""
    declaration = "output logic [31:0] frontend_p0,frontend_q0,frontend_cols,"
    replacement = "output logic [31:0] observed_frontend_p0,observed_frontend_q0,observed_frontend_cols,"
    if source.count(declaration) != 1:
        raise RuntimeError("窗口队列描述符端口无法定位")
    source = source.replace(declaration, replacement, 1)
    port = "input wire logic frontend_rsp_last,frontend_error);"
    if source.count(port) != 1:
        raise RuntimeError("窗口队列状态证明端口无法定位")
    source = source.replace(port, "input wire logic frontend_rsp_last,frontend_error, output logic proof_invariant);", 1)
    return source.replace("endmodule", """
  logic [31:0] frontend_p0, frontend_q0, frontend_cols;
  assign observed_frontend_p0 = frontend_valid ? frontend_p0 : 32'd0;
  assign observed_frontend_q0 = frontend_valid ? frontend_q0 : 32'd0;
  assign observed_frontend_cols = frontend_valid ? frontend_cols : 32'd0;
  always_comb begin
    assume(count <= COUNT_W'(DEPTH));
    assume(active_count <= p_active_width'(p_frontend_outstanding));
  end
""" + PROPERTIES + "endmodule", 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-ref", required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--case", nargs=3, type=int, action="append",
                        metavar=("DEPTH", "LANES", "OUTSTANDING"))
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes, snapshots = {}, {}
    for side in ("reference", "current"):
        snapshots[side] = out / side
        hashes[side] = {}
        for name in SOURCES:
            data = (subprocess.check_output(["git", "show", args.reference_ref + ":" + name], cwd=root)
                    if side == "reference" else (root / name).read_bytes())
            hashes[side][name] = hashlib.sha256(data).hexdigest()
            path = snapshots[side] / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(qualified_descriptor(data.decode()) if name == SOURCES[-1] else data.decode())

    # 存储读端随寄存位置改变；比较有效输出及完整的存储内容。
    unmatched = ["frontend_p0", "frontend_q0", "frontend_cols", "descriptor_o_rd_data"]
    unmatched += [f"g_descriptor[{field}].u_value.o_rd_data" for field in range(3)]
    blacklist = out / "retimed_internal_ports.txt"
    blacklist.write_text("\n".join(unmatched) + "\n")
    configurations = args.case or [*((depth, lanes, outstanding)
        for depth, lanes in ((2, 4), (3, 16), (4, 16), (7, 16))
        for outstanding in (1, 2)), (4, 8, 3), (4, 16, 3)]
    report = dict(passed=True, reference_ref=args.reference_ref, source_sha256=hashes,
                  input_constraints=["rst_n=0 at the first sampled edge for independent invariant proofs"],
                  equivalence_state_constraints=["count<=DEPTH", "active_count<=p_frontend_outstanding"],
                  state_constraints_proven_independently=True, descriptor_data_qualification="frontend_valid",
                  compared_outputs="all public controls and responses; valid frontend p0, q0, and cols",
                  unmatched_internal_ports=unmatched, cases=[])
    for depth, lanes, outstanding in configurations:
        directory = out / f"depth{depth}_lanes{lanes}_outstanding{outstanding}"
        directory.mkdir(exist_ok=True)
        commands = []
        for side, label in (("reference", "gold"), ("current", "gate")):
            options = ["--top", TOP, "--single-unit", "--allow-use-before-declare",
                       "-D", "SYNTHESIS=1", f"-GDEPTH={depth}", f"-GWINDOW_LANES={lanes}",
                       f"-Gp_frontend_outstanding={outstanding}"]
            commands += ["read_slang " + shlex.join(options + [str(snapshots[side] / name) for name in SOURCES]),
                         f"prep -top {TOP} -flatten", "memory_map", "async2sync", "opt_clean",
                         "sat -verify -seq 2 -tempinduct -set-at 1 rst_n 0 -prove proof_invariant 1 -maxsteps 10",
                         f"rename {TOP} {label}", f"design -stash {label}"]
        commands += ["design -copy-from gold -as gold gold", "design -copy-from gate -as gate gate",
                     f"equiv_make -blacklist {shlex.quote(str(blacklist))} gold gate equivalent",
                     "hierarchy -top equivalent", "equiv_simple -short -seq 1 -set-assumes", "opt_clean",
                     "equiv_induct -seq 3 -set-assumes", "equiv_status -assert"]
        script, log = directory / "proof.ys", directory / "proof.log"
        script.write_text("\n".join(commands) + "\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=180)
        content = log.read_text()
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", content)
        if "Equivalence successfully proven!" not in content or not match or int(match[2]) or \
                content.count("Induction step proven: SUCCESS!") != 2:
            raise RuntimeError("窗口队列等价证明没有完成：" + str(log))
        report["cases"].append(dict(depth=depth, lanes=lanes, outstanding=outstanding,
                                    passed=True, equivalent_bits=int(match[1]),
                                    log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
        print(f"WINDOW_QUEUE_EQUIVALENCE_PASS depth={depth} lanes={lanes} outstanding={outstanding}", flush=True)
    if hashes["current"] != {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCES}:
        raise RuntimeError("测试期间窗口队列源码发生变化")
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
