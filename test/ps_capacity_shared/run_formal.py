#!/usr/bin/env python3
"""证明共享部分和容量计算及完整帧存储的逐周期等价性。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/ps_compact/ps_frame_store.sv"
CASES = dict(runpy.run_path(str(ROOT / "test/ps_frame_ready/run_full.py"))["CASES"])
CASES["odd_frames"] = ("ps_frame_store", SOURCE,
                       dict(MAX_FRAME_ROWS=47, FRAME_COUNT=3, POOL_BYTES=4096,
                            BANK_BYTES=2048, EXTERNAL_RAM=0))
sys.path.insert(0, str(ROOT / "test/ia_timing"))
from run_interface import port_declarations

RELATION = """
    logic [FRAME_COUNT-1:0] capacity_properties;
    for (genvar frame = 0; frame < FRAME_COUNT; frame++) begin : g_capacity_properties
        wire [RAW_LINEAR_BITS-3:0] offset =
            (RAW_LINEAR_BITS-2)'(frame) * (RAW_LINEAR_BITS-2)'(directory_stride_q);
        assign capacity_properties[frame] = frame_available_rows_q[frame] ==
            (p_capacity_rows_width+1)'({1'b0, pool_capacity_rows_q} -
                (p_capacity_rows_width+1)'(offset));
    end
"""


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def property_model(source):
    """实际完整模块仅增加观察输出，所有功能输入均由外部自由提供。"""
    ports = port_declarations(source)
    header = source[source.index("module ps_frame_store #("):source.index(") (")]
    header = header.replace("module ps_frame_store", "module capacity_property_top", 1)
    parameters = re.findall(r"parameter (?:integer|bit) (\w+)", header)
    wrapper = header + ") (\n" + ",\n".join(
        f"input {kind} {name} {unpacked}"
        for direction, kind, name, unpacked in ports if direction == "input")
    wrapper += ",\noutput wire proof_capacity\n);\n"
    wrapper += "ps_frame_store #(" + ",".join(f".{p}({p})" for p in parameters)
    wrapper += ") u_dut(" + ",".join(
        f".{name}({name})" for direction, kind, name, unpacked in ports if direction == "input")
    wrapper += ",.proof_capacity(proof_capacity));\nendmodule\n"
    observed = source.replace("\n);", ",\n output wire proof_capacity\n);", 1)
    observed = observed.replace("\nendmodule", RELATION +
                                "\n assign proof_capacity = &capacity_properties;\nendmodule", 1)
    return observed + wrapper


def run(script, log):
    with log.open("w") as output:
        subprocess.run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py",
                        "--worker", script], cwd=ROOT, stdout=output,
                       stderr=subprocess.STDOUT, check=True, timeout=600)
    return log.read_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="8cbe40d9")
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--cases", nargs="+", choices=tuple(CASES), default=list(CASES))
    parser.add_argument("--mode", choices=("generic", "fpga"), default="generic")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, output = args.source_root.resolve(), args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    resolve = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    actual = (root / SOURCE).read_text()
    reference = subprocess.check_output(["git", "show", args.reference + ":" + SOURCE],
                                        cwd=ROOT, text=True)
    hashes = {str(path): digest(path) for path in resolve([root / SOURCE], root)}
    definitions = (["-USYNTHESIS", "-UXILINX_FPGA"] if args.mode == "generic" else
                   ["-DSYNTHESIS=1", "-DXILINX_FPGA=1"])
    observed = output / "property.sv"
    observed.write_text(property_model(actual))
    original = output / "reference.sv"
    original.write_text(reference)
    current = output / "current.sv"
    # 此条件仅用于完整等价证明，并在每个参数配置下先独立完成实际模块状态归纳。
    current.write_text(actual.replace("\nendmodule", RELATION +
                       "\n always_comb assume(&capacity_properties);\nendmodule", 1))
    records = []
    for case in args.cases:
        parameters = CASES[case][2]
        folder = output / case
        folder.mkdir(exist_ok=True)
        options = definitions + [f"-G{k}={v}" for k, v in parameters.items()]
        files = resolve([observed], root)
        script, log = folder / "invariant.ys", folder / "invariant.log"
        script.write_text("read_slang --top capacity_property_top " +
                          shlex.join(options + list(map(str, files))) +
                          "\nprep -top capacity_property_top -flatten\nmemory_map\nasync2sync\n"
                          "opt -full\nsat -verify -tempinduct -seq 2 -maxsteps 8 "
                          "-set-at 1 rst_n 0 -prove proof_capacity 1\n")
        result = run(script, log)
        assert "Induction step proven: SUCCESS!" in result
        invariant_hash = digest(log)
        commands = []
        for label, path in (("reference", original), ("current", current)):
            files = resolve([path], root)
            commands += ["read_slang --top ps_frame_store " +
                         shlex.join(options + list(map(str, files))),
                         "prep -top ps_frame_store -flatten", "memory_map", "async2sync",
                         "opt_clean", f"rename ps_frame_store {label}", f"design -stash {label}"]
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from current -as current current",
                     "equiv_make reference current equivalent", "hierarchy -top equivalent",
                     "equiv_simple -seq 1", "opt_clean", "equiv_induct -set-assumes -seq 3",
                     "equiv_status -assert"]
        script, log = folder / "equivalent.ys", folder / "equivalent.log"
        script.write_text("\n".join(commands) + "\n")
        result = run(script, log)
        assert "Equivalence successfully proven!" in result
        count = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", result)
        assert count and int(count[2]) == 0
        records.append(dict(case=case, parameters=parameters, passed=True,
                            equivalent_bits=int(count[1]), invariant_log_sha256=invariant_hash,
                            parent_log_sha256=digest(log)))
        assert hashes == {path: digest(Path(path)) for path in hashes}
        report = dict(passed=len(records) == len(args.cases), reference=args.reference,
                      mode=args.mode, definitions=definitions, source_sha256=hashes,
                      external_input_constraints=None,
                      invariant_start="首次采样复位，此后全部外部输入及复位自由",
                      parent_scope="全部公开输出、共同状态与存储内容",
                      parent_state_relation="逐帧容量等于配置总行数减去该帧的定宽起始行",
                      profiles=records, test_sha256=digest(Path(__file__)))
        (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print("PS_CAPACITY_SHARED_PASS", args.mode, case, count[1], flush=True)


if __name__ == "__main__":
    main()
