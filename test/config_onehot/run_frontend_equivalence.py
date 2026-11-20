#!/usr/bin/env python3
"""证明前端的四个幂次判断，并核对其余状态与数据逻辑逐字保持。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/conv/conv_im2col_frontend.sv"
PREDICATES = {
    "stride_shape_o_valid": "is_power_two(32'(cfg.stride_h))",
    "pixel_shape_o_valid": "is_power_two(cfg_pixel_bytes)",
    "group_shape_o_valid": "is_power_two(32'(c.group_c))",
    "kernel_shape_o_valid": "is_power_two(32'(c.kernel_w))",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-ref", default="4df62f2")
    args = parser.parse_args()
    import pyosys
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    old = read_rtl_source(args.reference_ref + ":" + SOURCE, cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    old_start = old.index("  function automatic logic is_power_two(")
    end_marker = "  function automatic logic [4:0] power_shift("
    old_end = old.index(end_marker)
    new_start = current.index("  // 配置和分块解码共用分组幂次检查")
    new_end = current.index(end_marker)
    old_body = old[:old_start] + old[old_end:]
    current_body = current[:new_start] + current[new_end:]
    for name, original in PREDICATES.items():
        if current_body.count(name) != old_body.count(original):
            raise RuntimeError("Frontend predicate use count differs: " + name)
        current_body = current_body.replace(name, original)
    if old_body != current_body:
        raise RuntimeError("Frontend contains changes beyond the proven predicate substitutions")
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    model = out / "xilinx_lut_models.sv"
    model.write_text("\n".join(re.search(r"^module " + name + r"\b.*?^endmodule",
        library.read_text(), re.M | re.S).group(0) for name in ("LUT6", "LUT6_2")) + "\n")
    harness = out / "frontend_predicates.sv"
    harness.write_text("""module frontend_predicates (
    input conv_im2col_pkg::conv_cfg_t cfg, c,
    input logic [31:0] cfg_pixel_bytes,
    output logic equivalent
);
""" + old[old_start:old_end] + current[new_start:new_end] +
        "  assign equivalent = " + " &&\n      ".join(
            f"({name} == {expression})" for name, expression in PREDICATES.items()) + ";\nendmodule\n")
    sources = [ROOT / "rtl/npu/conv/conv_im2col_pkg.sv", ROOT / "rtl/common/onehot_check.sv", model, harness]
    script = out / "run.ys"
    script.write_text("read_slang --top frontend_predicates -D XILINX_FPGA " +
        " ".join(shlex.quote(str(p)) for p in sources) + "\n"
        "prep -top frontend_predicates -flatten\ndelete t:$specify2\ncheck -assert\n"
        "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
    log = out / "formal.log"
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                        "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True)
    if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
        raise RuntimeError("Missing complete-input SAT result")
    summary = {"passed": True, "reference_ref": args.reference_ref,
               "source_sha256": hashlib.sha256(current.encode()).hexdigest(),
               "reference_sha256": hashlib.sha256(old.encode()).hexdigest(),
               "helper_sha256": hashlib.sha256(sources[1].read_bytes()).hexdigest(),
               "predicate_count": len(PREDICATES), "inputs_constrained": False,
               "remaining_module_body_identical_after_predicate_substitution": True,
               "primitive_library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
               "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
