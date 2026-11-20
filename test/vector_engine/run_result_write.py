#!/usr/bin/env python3
"""提取结果写入 RTL，证明全部状态下的写使能与数据，并测量资源。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PARAMETERS = """parameter int TILE=16, parameter int PE_COUNT=8,
    localparam int ACTIVE_COUNT_W=$clog2(TILE+1),
    localparam int TILE_INDEX_W=$clog2(TILE+PE_COUNT+1)"""
INPUTS = [
    ("vector_engine_pkg::vector_engine_cfg_t", "c", ""),
    ("logic [5:0]", "state_bits", ""),
    ("logic [ACTIVE_COUNT_W-1:0]", "active", ""),
    ("logic [TILE_INDEX_W-1:0]", "compute_index", ""),
    ("logic [TILE_INDEX_W-1:0]", "quant_index", ""),
    ("logic [TILE_INDEX_W-1:0]", "reduce_index", ""),
    ("logic [TILE_INDEX_W-1:0]", "q_index_5", ""),
    ("logic [$clog2(TILE)-1:0]", "soft_out_index", ""),
    ("logic [5:0]", "q_valid", ""),
    ("logic", "q_active", ""), ("logic", "soft_out_we", ""),
    ("logic", "writeback_busy", ""), ("logic", "avg_done", ""),
    ("logic signed [7:0]", "soft_out_data", ""),
    *[("logic signed [31:0]", name, "") for name in
      ("q_clamped_data", "add_clamped", "avg_power_result", "avg_div_result", "reduce_next")],
    ("logic signed [31:0]", "acc_buf", "[TILE]"),
    ("logic signed [31:0]", "pe_result", "[PE_COUNT]"),
]
OUTPUTS = "output logic [TILE-1:0] o_write_enable, output logic [8*TILE-1:0] o_write_data"


def inputs():
    return ",\n    ".join("input " + kind + " " + name + " " + unpacked
                           for kind, name, unpacked in INPUTS)


def extract(source, label):
    state_type = re.search(r"typedef enum logic \[5:0\] \{.*?\} state_t;", source, re.DOTALL).group(0)
    marker = "  for (genvar entry=0;entry<TILE;entry++) begin : g_result_write"
    body = marker + source.split(marker, 1)[1].split("    // Byte results update", 1)[0]
    extra = ""
    if "  logic result_background_write;" in source:
        extra = "  logic result_background_write;" + source.split(
            "  logic result_background_write;", 1)[1].split(marker, 1)[0]
    body += "    assign o_write_enable[entry]=write_enable;\n" + \
            "    assign o_write_data[8*entry+:8]=write_value;\n  end\n"
    return f"module result_write_{label} #({PARAMETERS}) (\n    {inputs()},\n    {OUTPUTS}\n);\n" + \
           "  import vector_engine_pkg::*;\n  " + state_type + \
           "\n  state_t state;\n  assign state=state_t'(state_bits);\n" + \
           "  wire depthwise=(c.op==DW_S8);\n  wire softmax_s8=(c.op==SOFTMAX_S8);\n" + \
           extra + body + "endmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-rev", default="3f2e612")
    parser.add_argument("--configurations", nargs="+", default=["8:1", "16:8", "32:8", "16:3"])
    parser.add_argument("--synthesis", action="store_true")
    parser.add_argument("--synth-script", type=Path, default=ROOT / "scripts/fpga/open_fpga_synth.py")
    parser.add_argument("--lock-file", type=Path)
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass("script " + shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_path = ROOT / "rtl/npu/conv/vector_engine.sv"
    sources = [ROOT / "rtl/npu/conv/conv_im2col_pkg.sv", ROOT / "rtl/npu/conv/vector_engine_pkg.sv"]
    for label in ("reference", "candidate"):
        source = subprocess.check_output(["git", "show", args.reference_rev + ":rtl/npu/conv/vector_engine.sv"],
                                         cwd=ROOT, text=True) if label == "reference" else source_path.read_text()
        path = out / (label + ".sv")
        path.write_text(extract(source, label))
        sources.append(path)
    formal = out / "formal.sv"
    formal.write_text(f"module result_write_formal #({PARAMETERS}) (\n    {inputs()}\n);\n" + """
    wire [TILE-1:0] reference_enable, candidate_enable;
    wire [8*TILE-1:0] reference_data, candidate_data;
    result_write_reference #(.TILE(TILE),.PE_COUNT(PE_COUNT)) u_reference (.*,
        .o_write_enable(reference_enable), .o_write_data(reference_data));
    result_write_candidate #(.TILE(TILE),.PE_COUNT(PE_COUNT)) u_candidate (.*,
        .o_write_enable(candidate_enable), .o_write_data(candidate_data));
    always_comb begin
        assert(reference_enable==candidate_enable);
        for (int entry=0;entry<TILE;entry++)
            if (reference_enable[entry])
                assert(reference_data[8*entry+:8]==candidate_data[8*entry+:8]);
    end
endmodule
""")
    summary = {"reference_rev": args.reference_rev,
               "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
               "method": "SAT of result-write expressions extracted from both RTL revisions; every state and opcode",
               "runs": []}
    for configuration in args.configurations:
        tile, pes = map(int, configuration.split(":"))
        folder = out / f"tile{tile}_pe{pes}"
        folder.mkdir(exist_ok=True)
        script = folder / "run.ys"
        script.write_text(f"read_slang --top result_write_formal -GTILE={tile} -GPE_COUNT={pes} " +
                          " ".join(shlex.quote(str(path)) for path in [*sources, formal]) +
                          "\nprep -top result_write_formal -flatten\nopt_clean\nchformal -lower\n" +
                          "sat -prove-asserts -verify -show-inputs -show-outputs\n")
        with (folder / "formal.log").open("w") as stream:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--out", str(out),
                                     "--worker", str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        log = (folder / "formal.log").read_text()
        passed = result.returncode == 0 and "SAT proof finished - no model found: SUCCESS" in log
        record = {"tile": tile, "pe_count": pes, "passed": passed}
        summary["runs"].append(record)
        summary["passed"] = all(item["passed"] for item in summary["runs"])
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(record), flush=True)
        if not passed:
            print(log[-12000:])
            raise SystemExit(1)
    if args.synthesis:
        measure = out / "measure.sv"
        lines = [f"module result_write_measure #(parameter bit p_reference=1'b0, {PARAMETERS}) (",
                 f"    input logic clk, {inputs()}, {OUTPUTS});"]
        for kind, name, unpacked in INPUTS:
            lines += [f"    {kind} {name}_q {unpacked};",
                      f"    always_ff @(posedge clk) {name}_q<={name};"]
        lines += ["    wire [TILE-1:0] write_enable;", "    wire [8*TILE-1:0] write_data;",
                  "    always_ff @(posedge clk) o_write_enable<=write_enable;",
                  "    for (genvar entry=0;entry<TILE;entry++) begin : g_write",
                  "        always_ff @(posedge clk) if (write_enable[entry]) o_write_data[8*entry+:8]<=write_data[8*entry+:8];",
                  "    end"]
        for label, condition in (("reference", "if (p_reference)"), ("candidate", "else")):
            lines += [f"    {condition} begin : g_{label}",
                      f"        result_write_{label} #(.TILE(TILE),.PE_COUNT(PE_COUNT)) u_write (",
                      ",\n".join(f"            .{name}({name}_q)" for _, name, _ in INPUTS) + ",",
                      "            .o_write_enable(write_enable), .o_write_data(write_data));", "    end"]
        lines.append("endmodule")
        measure.write_text("\n".join(lines) + "\n")
        cases = {"result_" + label: {"top": "result_write_measure", "options": ["-Gp_reference=" + str(value)],
                 "sources": [str(path) for path in [*sources, measure]],
                 "configuration": "TILE16 PE8, registered source values and result storage"}
                 for label, value in (("reference", 1), ("candidate", 0))}
        case_file = out / "cases.json"
        case_file.write_text(json.dumps(cases, indent=2) + "\n")
        command = [sys.executable, str(args.synth_script.resolve()), "--source-root", str(ROOT),
                   "--case-config", str(case_file), "--cases", *cases, "--out", str(out / "synthesis")]
        if args.lock_file:
            command += ["--lock-file", str(args.lock_file.resolve())]
        subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
