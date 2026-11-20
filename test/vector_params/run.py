#!/usr/bin/env python3
"""提取向量参数读写 RTL，证明完整存储状态并检查读写周期。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PARAMETERS = """parameter int TILE=16, parameter int BUS_WIDTH=64,
    parameter int PE_COUNT=8,
    localparam int INPUT_INDEX_W=$clog2(4*TILE),
    localparam int ACTIVE_COUNT_W=$clog2(TILE+1),
    localparam int TILE_INDEX_W=$clog2(TILE+PE_COUNT+1)"""
PORTS = """input logic clk, rst_n,
    input logic [5:0] state_bits,
    input logic [2:0] load_kind_bits,
    input logic rd_raw_valid,
    input logic [INPUT_INDEX_W-1:0] rd_col_base,
    input logic [BUS_WIDTH-1:0] rd_raw_data,
    input logic [ACTIVE_COUNT_W-1:0] active,
    input logic [TILE_INDEX_W-1:0] q_issue,
    output logic signed [31:0] o_multiplier,
    output logic [5:0] o_right_shift"""


def extract(source, label, formal):
    types = re.search(r"typedef enum logic \[5:0\] \{.*?\} state_t;", source, re.DOTALL).group(0)
    types += "\n" + re.search(r"typedef enum logic \[2:0\] \{.*?\} load_t;", source, re.DOTALL).group(0)
    body = f"module vector_params_{label} #({PARAMETERS}) ({PORTS});\n" + types
    body += "\n    state_t state;\n    load_t load_kind;\n" + \
            "    assign state=state_t'(state_bits);\n    assign load_kind=load_t'(load_kind_bits);\n"
    if label == "reference":
        marker = "  for (genvar entry=0;entry<TILE;entry++) begin : g_parameter_write"
        writes = marker + source.split(marker, 1)[1].split(
            "  for (genvar entry=0;entry<TILE;entry++) begin : g_accumulator_write", 1)[0]
        body += "    logic signed [31:0] bias_buf[TILE], mult_buf[TILE];\n" + \
                "    logic [5:0] right_shift_buf[TILE];\n" + writes
        body += "    assign o_multiplier=(q_issue<TILE) ? mult_buf[q_issue] : 32'sd0;\n" + \
                "    assign o_right_shift=(q_issue<TILE) ? right_shift_buf[q_issue] : 6'd0;\n"
        alias = "{right_shift_buf[entry], mult_buf[entry]}"
    else:
        marker = "  logic params_i_wr_en;"
        body += marker + source.split(marker, 1)[1].split(
            "  for (genvar entry=0;entry<TILE;entry++) begin : g_accumulator_write", 1)[0]
        body += "    assign o_multiplier=params_o_multiplier;\n" + \
                "    assign o_right_shift=params_o_right_shift;\n"
        alias = "u_quant_params.g_bank[entry%(BUS_WIDTH/32)].u_regfile.mem[entry/(BUS_WIDTH/32)]"
    if formal:
        body += "    (* keep *) wire [38*TILE-1:0] formal_params;\n" + \
                "    for (genvar entry=0;entry<TILE;entry++) begin : g_formal\n" + \
                "        assign formal_params[38*entry+:38]=" + alias + ";\n    end\n"
    return body + "endmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-rev", default="3f2e612")
    parser.add_argument("--configurations", nargs="+", default=["8:32", "16:32", "16:64", "17:64", "32:64", "16:128"])
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--synthesis", action="store_true")
    parser.add_argument("--verilator", default="verilator-modern")
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
    paths = [source_path, ROOT / "rtl/npu/conv/vector_quant_params.sv", ROOT / "rtl/common/REGFILE.v"]
    reference = subprocess.check_output(["git", "show", args.reference_rev + ":rtl/npu/conv/vector_engine.sv"],
                                        cwd=ROOT, text=True)
    for label, source in (("reference", reference), ("candidate", source_path.read_text())):
        for formal in (False, True):
            name = label + ("_formal" if formal else "") + ".sv"
            (out / name).write_text(extract(source, label, formal))
    formal = out / "formal.sv"
    formal.write_text(f"module vector_params_formal #({PARAMETERS}) (" +
                     PORTS.split(",\n    output", 1)[0] + ",\n    output wire state_equal, output_equal);\n" + """
    wire signed [31:0] reference_multiplier, candidate_multiplier;
    wire [5:0] reference_shift, candidate_shift;
    vector_params_reference #(.TILE(TILE),.BUS_WIDTH(BUS_WIDTH),.PE_COUNT(PE_COUNT)) u_reference (.*,
        .o_multiplier(reference_multiplier), .o_right_shift(reference_shift));
    vector_params_candidate #(.TILE(TILE),.BUS_WIDTH(BUS_WIDTH),.PE_COUNT(PE_COUNT)) u_candidate (.*,
        .o_multiplier(candidate_multiplier), .o_right_shift(candidate_shift));
    assign state_equal=(u_reference.formal_params==u_candidate.formal_params);
    assign output_equal=({reference_shift,reference_multiplier}=={candidate_shift,candidate_multiplier});
endmodule
""")
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    summary = {"reference_rev": args.reference_rev, "sources_sha256": hashes,
               "method": "Complete-state equivalence of actual parameter write and read RTL; all encoded inputs",
               "runs": []}
    for configuration in args.configurations:
        tile, bus = map(int, configuration.split(":"))
        folder = out / f"tile{tile}_bus{bus}"
        folder.mkdir(exist_ok=True)
        options = [f"-GTILE={tile}", f"-GBUS_WIDTH={bus}"]
        sources = [out / "reference_formal.sv", out / "candidate_formal.sv", *paths[1:], formal]
        commands = ["read_slang --top vector_params_formal " + " ".join(options) + " " +
                    " ".join(shlex.quote(str(path)) for path in sources),
                    "prep -top vector_params_formal -flatten", "memory_map", "opt -full",
                    "sat -seq 1 -set-at 1 state_equal 1 -prove output_equal 1 -verify",
                    "sat -seq 2 -set-at 1 state_equal 1 -prove-skip 1 -prove state_equal 1 -prove output_equal 1 -verify"]
        script = folder / "run.ys"
        script.write_text("\n".join(commands) + "\n")
        with (folder / "formal.log").open("w") as stream:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--out", str(out),
                                     "--worker", str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        log = (folder / "formal.log").read_text()
        record = {"tile": tile, "bus_width": bus,
                  "formal_passed": result.returncode == 0 and log.count("SAT proof finished - no model found: SUCCESS") == 2,
                  "equivalent_storage_bits": 38 * tile}
        summary["runs"].append(record)
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(record), flush=True)
        if not record["formal_passed"]:
            print(log[-16000:])
            raise SystemExit(1)
        if args.simulate:
            sources = [out / "reference.sv", out / "candidate.sv", *paths[1:], HERE / "tb_vector_params.sv"]
            command = [args.verilator, "--binary", "--timing", "--assert", "-Wno-fatal",
                       "--top-module", "tb_vector_params", *options, "-j", "2",
                       "--Mdir", str(folder / "obj"), *map(str, sources)]
            with (folder / "compile.log").open("w") as stream:
                subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
            result = subprocess.run([str(folder / "obj/Vtb_vector_params")], cwd=ROOT,
                                    capture_output=True, text=True, check=True)
            (folder / "simulation.log").write_text(result.stdout + result.stderr)
            passed_line = next(line for line in result.stdout.splitlines() if line.startswith("VECTOR_PARAMS_PASS"))
            record["simulation"] = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", passed_line)}
            print(passed_line, flush=True)
            (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if args.synthesis:
        cases = {}
        for bus in (32, 64):
            for label in ("reference", "candidate"):
                cases[f"params_{label}_bus{bus}"] = {
                    "top": "vector_params_" + label, "options": ["-GTILE=16", f"-GBUS_WIDTH={bus}"],
                    "sources": [str(out / (label + ".sv")), *map(str, paths[1:])],
                    "configuration": f"16 multiplier/shift entries, {bus}-bit DMA, asynchronous scalar read"}
        case_file = out / "cases.json"
        case_file.write_text(json.dumps(cases, indent=2) + "\n")
        command = [sys.executable, str(args.synth_script.resolve()), "--source-root", str(ROOT),
                   "--case-config", str(case_file), "--cases", *cases, "--out", str(out / "synthesis")]
        if args.lock_file:
            command += ["--lock-file", str(args.lock_file.resolve())]
        subprocess.run(command, cwd=ROOT, check=True)
    if hashes != {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}:
        raise RuntimeError("Sources changed while verification was running")
    summary["passed"] = True
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
