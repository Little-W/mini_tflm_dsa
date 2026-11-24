#!/usr/bin/env python3
"""验证缓存原始输入地址的并行字比较及四态选择行为。"""
from __future__ import annotations

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
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
SOURCE = Path("rtl/npu/dma/cache/conv_windowed_cache.sv")
SELECTOR = Path("rtl/common/onehot_mux.sv")
PORTS = """input logic preview_source_select,
input logic [31:0] request_address, preview_address, work_address, demand_addr"""
NAMES = ("preview_source_select", "request_address", "preview_address", "work_address", "demand_addr")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assignment(source, name):
    result = re.search(r"\bassign\s+" + re.escape(name) + r"\s*=.*?;", source, re.S)
    if result is None:
        raise RuntimeError("缺少实际 RTL 表达式：" + name)
    return result.group()


def unit(name, source, parallel):
    if parallel:
        start = source.index("  // 两种输入地址并行比较")
        end = source.index("  assign lookup_idle_demand_match", start)
        word = source[start:end]
    else:
        word = assignment(source, "lookup_input_matches")
    return f"""module {name} (
{PORTS}, output logic [1:0] observed);
  typedef struct packed {{logic [31:0] address;}} demand_t;
  demand_t incoming_request, preview_request, work_request, lookup_input_request;
  logic [1:0] lookup_input_matches;
  (* keep = "true" *) logic [1:0] lookup_preview_matches, lookup_request_matches;
  assign incoming_request.address=request_address;
  assign preview_request.address=preview_address;
  assign work_request.address=work_address;
  assign lookup_input_request=preview_source_select ? preview_request : incoming_request;
{word}
  assign observed=lookup_input_matches;
endmodule
"""


def bench():
    return """module tb;
  localparam integer W=1+128;
  logic preview_source_select;
  logic [31:0] request_address,preview_address,work_address,demand_addr;
  wire [1:0] expected,actual;
  logic [W-1:0] stimulus,saved;
  logic [31:0] random_state=32'h83b5d091;
  integer checks=0;
  assign {preview_source_select,request_address,preview_address,work_address,demand_addr}=stimulus;
  reference u_reference(.*,.observed(expected));
  candidate u_candidate(.*,.observed(actual));
  function automatic logic value(input integer index);
    case(index)
      0:value=1'b0;
      1:value=1'b1;
      2:value=1'bx;
      3:value=1'bz;
    endcase
  endfunction
  task automatic check;
    #1;
    if(expected!==actual)
      $fatal(1,"INPUT_MATCH_MISMATCH stimulus=%b expected=%b actual=%b",stimulus,expected,actual);
    checks=checks+1;
  endtask
  initial begin
    for(integer trial=0;trial<32;trial++) begin
      for(integer b=0;b<W;b++) begin
        random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
        stimulus[b]=random_state[0];
      end
      if(trial%4==0) begin
        stimulus[0 +: 32]=stimulus[96 +: 32];
        stimulus[32 +: 32]=stimulus[64 +: 32];
      end
      if(trial%4==1) stimulus[64 +: 32]=stimulus[96 +: 32];
      if(trial%4==2) stimulus='0;
      saved=stimulus;
      for(integer s=0;s<4;s++) begin
        stimulus=saved;stimulus[W-1]=value(s);check();
        for(integer b=0;b<W-1;b++) begin
          stimulus=saved;stimulus[W-1]=value(s);
          stimulus[b]=1'bx;check();
          stimulus[b]=1'bz;check();
        end
      end
    end
    $display("INPUT_MATCH_FOUR_STATE_PASS checks=%0d",checks);
    $finish;
  end
endmodule
"""


def run(command, log, cwd):
    with log.open("w") as output:
        subprocess.run(list(map(str, command)), cwd=cwd, stdout=output,
                       stderr=subprocess.STDOUT, check=True)


def measure_cases(root, out):
    mapped_root = out / "mapping"
    run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py",
         "--source-root", root, "--case-config", out / "synthesis_cases.json",
         "--cases", "reference", "candidate", "--out", mapped_root],
        out / "mapping.log", root)
    helper = runpy.run_path(str(ROOT / "test/conv_frontend/tools/measure_complete_paths.py"))
    records = {}
    for label in ("reference", "candidate"):
        folder = mapped_root / label
        module = json.loads((folder / "mapped.json").read_text())["modules"][label]
        observed, _ = helper["add_interface_boundaries"](module)
        starts, ends = set(), set()

        def source(name, cell, port):
            matched = name.startswith("__measurement_interface__input:preview_source_select[")
            if matched:
                starts.add((name, port))
            return matched

        def target(name, cell, port):
            matched = name.startswith("__measurement_interface__output:observed[")
            if matched:
                ends.add((name, port))
            return matched

        paths = helper["connected_paths"](observed, root_filter=source, sink_filter=target)
        if not paths["graph_complete"] or not starts or len(ends) != 2:
            raise RuntimeError("局部输入匹配电路的连接图不完整")
        report = helper["measure"](module)
        report["critical_scopes"]["source_selection"] = dict(
            selected_start_ports=len(starts), selected_endpoint_ports=len(ends),
            scope_available=True, maximum_combinational_cells=paths["longest_register_path_cells"],
            graph_complete=paths["graph_complete"], paths=paths["register_to_register_paths"])
        report["scope"] = "Extracted word comparisons with unconstrained interface inputs"
        (folder / "complete_paths.json").write_text(json.dumps(report, indent=2) + "\n")
        records[label] = dict(graph_complete=True, selected_start_ports=len(starts),
            selected_endpoint_ports=len(ends),
            selection_depth=paths["longest_register_path_cells"],
            maximum_combinational_cells=report["maximum_combinational_cells"],
            resources=report["resources"], mapped_sha256=digest(folder / "mapped.json"),
            report_sha256=digest(folder / "complete_paths.json"))
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--reference-ref", default="e29735a7")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--map", action="store_true", help="使用生产综合命令测量局部完整连接图")
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (root / SOURCE).read_text()
    original = ((args.reference_root.resolve() / SOURCE).read_text()
                if args.reference_root else read_reference_file(ROOT, args.reference_ref, SOURCE, text=True))
    models = {"reference": unit("reference", original, False),
              "candidate": unit("candidate", current, True)}
    ports = ",".join(f".{name}({name})" for name in NAMES)
    comparison = "\n".join(models.values()) + f"""module comparison (
{PORTS},output logic equivalent);
  logic [1:0] expected,actual;
  reference u_reference({ports},.observed(expected));
  candidate u_candidate({ports},.observed(actual));
  assign equivalent=expected==actual;
endmodule
"""
    proof = out / "comparison.sv"
    proof.write_text(comparison)
    script, log = out / "formal.ys", out / "formal.log"
    script.write_text("read_slang --top comparison " +
        shlex.join([str(proof), str(root / SELECTOR)]) + "\n" +
        "prep -top comparison -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
    run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log, root)
    if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
        raise RuntimeError("输入地址匹配形式证明未完成")
    four_state = out / "four_state.sv"
    four_state.write_text("\n".join(models.values()) + bench())
    binary = out / "four_state.vvp"
    run(["iverilog", "-g2012", "-s", "tb", "-o", binary, four_state, root / SELECTOR],
        out / "four_state_compile.log", root)
    run(["vvp", binary], out / "four_state.log", root)
    count = re.search(r"INPUT_MATCH_FOUR_STATE_PASS checks=(\d+)",
                      (out / "four_state.log").read_text())
    if count is None or int(count[1]) != 32896:
        raise RuntimeError("四态输入匹配检查未完成")
    cases = {}
    for label, source in models.items():
        path = out / f"{label}.sv"
        path.write_text(source)
        cases[label] = dict(top=label, sources=[str(path), str(root / SELECTOR)], options=[],
                            configuration="原始输入字地址匹配，选择信号为独立输入")
    (out / "synthesis_cases.json").write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n")
    if current != (root / SOURCE).read_text():
        raise RuntimeError("验证期间缓存源码发生变化")
    result = dict(passed=True, source_sha256=digest(root / SOURCE),
        selector_sha256=digest(root / SELECTOR),
        reference_sha256=hashlib.sha256(original.encode()).hexdigest(),
        actual_rtl_expressions=True, external_inputs_constrained=False,
        sat_properties=1, matched_words=2, formal_log_sha256=digest(log),
        four_state_cases=int(count[1]), proof_sha256=digest(proof),
        four_state_log_sha256=digest(out / "four_state.log"))
    if args.map:
        result["mapping"] = measure_cases(root, out)
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
