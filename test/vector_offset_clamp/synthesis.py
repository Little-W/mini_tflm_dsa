#!/usr/bin/env python3
"""在寄存器之间映射实际偏移与限幅运算，比较面积和组合深度。"""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import runpy
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/conv/vector_engine.sv"
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import analyze, connected_paths, register_origins


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="414099fa")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    extract = runpy.run_path(str(ROOT / "test/vector_offset_clamp/run.py"))["extract"]
    packages = [ROOT / "rtl/npu/conv/conv_im2col_pkg.sv", ROOT / "rtl/npu/conv/vector_engine_pkg.sv"]
    primitive_file = out / "xilinx_primitives.sv"
    primitive_file.write_text("module LUT6_2 #(parameter [63:0] INIT=64'b0) (input I0,I1,I2,I3,I4,I5, output O5,O6); endmodule\n")
    results = {}
    for label in ("reference", "current"):
        folder = out / label
        folder.mkdir(exist_ok=True)
        source = (read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True)
                  if label == "reference" else (ROOT / SOURCE).read_text())
        declarations, arithmetic, result = extract(source)
        design = folder / "offset_clamp.sv"
        design.write_text("""module offset_clamp(
  input logic clk,
  input logic signed [63:0] i_rounded,
  input vector_engine_pkg::vector_engine_cfg_t i_config,
  output logic [33:0] o_result
);
  logic signed [63:0] q_rounded;
  vector_engine_pkg::vector_engine_cfg_t c;
""" + declarations + "\n" + arithmetic + result + """
  always_ff @(posedge clk) begin
    q_rounded<=i_rounded;
    c<=i_config;
    o_result<={q_above_max,q_below_min,q_clamped_data};
  end
endmodule
""")
        script, log, mapped, pre_lut = [folder / name for name in ("run.ys", "synthesis.log", "mapped.json", "pre_lut.il")]
        script.write_text("read_slang --top offset_clamp -D SYNTHESIS -D XILINX_FPGA --blackboxed-module LUT6_2 -v " +
            shlex.quote(str(primitive_file)) + " " + " ".join(shlex.quote(str(p)) for p in [*packages, design]) +
            "\nread_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n" +
            "synth_xilinx -top offset_clamp -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts\n" +
            "write_rtlil " + shlex.quote(str(pre_lut)) + "\n" +
            "synth_xilinx -top offset_clamp -family xc7 -noiopad -noclkbuf -flatten -run map_luts:\n" +
            "check -assert\nstat -tech xilinx\nwrite_json " + shlex.quote(str(mapped)) + "\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                           cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        module = json.loads(mapped.read_text())["modules"]["offset_clamp"]
        for name, origin in register_origins(pre_lut).items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
        metrics = analyze(module)
        paths = connected_paths(module, limit=20, group_limit=20,
            root_filter=lambda n, c, p: c.get("attributes", {}).get("fpga_register_origin") == "c [654]")
        if not metrics["paths"]["graph_complete"] or not paths["graph_complete"]:
            raise RuntimeError("Incomplete mapped graph")
        results[label] = dict(source_sha256=digest(source.encode()), resources=metrics["resources"],
            paths=metrics["paths"], output_offset_bit_10_paths=paths,
            maximum_resident_kib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
            mapped_sha256=digest(mapped.read_bytes()), pre_lut_sha256=digest(pre_lut.read_bytes()),
            model_sha256=digest(design.read_bytes()))
        (folder / "summary.json").write_text(json.dumps(results[label], indent=2) + "\n")
        print(label,metrics["resources"]["logic_lut_cells"],metrics["paths"]["longest_register_path_cells"],
              paths["longest_register_path_cells"],flush=True)
    report = dict(scope="Actual output offset and clamp expressions between input and output registers",
        reference_commit=subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
        cases=results, metrics_tool_sha256=digest((ROOT / "scripts/fpga/netlist_metrics.py").read_bytes()))
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
