#!/usr/bin/env python3
"""证明输出写回控制在参数配置下的时序等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/writeback/oa_writer.sv")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="aa2ef9a3")
    parser.add_argument("--out", type=Path, default=ROOT / "build/oa_writer_formal")
    parser.add_argument("--profiles", nargs="+", default=["4:32:8", "8:64:8", "16:32:16",
                                                         "16:64:16", "16:64:28", "16:64:32", "32:64:32"])
    parser.add_argument("--seq", type=int, default=8)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"], cwd=ROOT, text=True)
    registers = sorted(set(re.findall(r"\b(\w+)\s*<=", original)))
    invariants = """
    assign formal_invariant =
        (co_initial_rows == 9'((cfg_k < co_rows_limit) ? cfg_k : co_rows_limit)) &&
        (co_current_rows == 9'(((cfg_k - (REG_WIDTH'(row_group_base_idx) << VCOL_W)) < co_rows_limit) ?
             (cfg_k - (REG_WIDTH'(row_group_base_idx) << VCOL_W)) : co_rows_limit)) &&
        (((state != S_START) && (state != S_WRITE)) ||
             ((co_next_rows_prepared == co_next_rows_calc) &&
              (co_has_next_col == ((col_offset_addr_cur + co_chunk_bytes) < cfg_m)) &&
              (co_has_next_group == (row_group_next_base_idx < row_tiles_total))));
"""

    def instrument(text, top, invariant):
        text = re.sub(r"\boa_writer\b", top, text)
        text = re.sub(r"output\s+logic\s+oa_calc_over\s*\n", "output logic oa_calc_over,\n"
                      "    output logic [4095:0] formal_state,\n"
                      "    output logic formal_invariant\n", text, count=1)
        return text.replace("endmodule", "assign formal_state = {" + ", ".join(registers) +
                            "};\n" + invariant + "\nendmodule", 1)

    reference = out / "oa_writer_ref.sv"
    reference.write_text(instrument(original, "oa_writer_ref", "assign formal_invariant = 1'b1;"))
    current = out / "oa_writer_current.sv"
    current.write_text(instrument((ROOT / SOURCE).read_text(), "oa_writer_current", invariants))
    source_hash = hashlib.sha256((ROOT / SOURCE).read_bytes()).hexdigest()
    profiles = []
    for profile in args.profiles:
        size, bus, count = map(int, profile.split(":"))
        name = f"n{size}_b{bus}_c{count}"
        script = out / f"{name}.ys"
        params = f"-GVLEN={size} -GBUS_WIDTH={bus} -GCOUNT_WIDTH={count}"
        script.write_text(
            f"read_slang --top oa_writer_ref {params} {shlex.quote(str(reference))}\n"
            "prep -top oa_writer_ref -flatten\nrename oa_writer_ref gold\n"
            "design -stash gold\n"
            f"read_slang --top oa_writer_current {params} {shlex.quote(str(current))}\n"
            "prep -top oa_writer_current -flatten\nrename oa_writer_current gate\n"
            "design -copy-from gold -as gold gold\n"
            "miter -equiv -flatten gold gate miter\nprep -top miter -flatten\n"
            "sat -verify -prove trigger 0 -tempinduct -seq 2 -set-init-zero "
            f"-set-at 1 in_rst_n 0 -maxsteps {args.seq}\n")
        log_path = out / f"{name}.log"
        with log_path.open("w") as log:
            result = subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                "--worker", str(script)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f"Formal verification failed: {log_path}")
        log = log_path.read_text()
        if "SUCCESS" not in log:
            raise RuntimeError(f"Missing proof completion: {log_path}")
        profiles.append(dict(vlen=size, bus_width=bus, count_width=count, passed=True,
                             state_and_control_signals=len(registers), compared_public_outputs=21,
                             method="temporal induction with derived-state invariants"))
        print(json.dumps(profiles[-1]), flush=True)
    if source_hash != hashlib.sha256((ROOT / SOURCE).read_bytes()).hexdigest():
        raise RuntimeError("Source changed during verification")
    report = dict(passed=True, reference=args.reference, source_sha256=source_hash,
                  reference_sha256=hashlib.sha256(original.encode()).hexdigest(), profiles=profiles)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
