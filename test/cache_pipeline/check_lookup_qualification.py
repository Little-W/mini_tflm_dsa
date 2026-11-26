#!/usr/bin/env python3
"""验证缓存读取冲突、快照资格及四态选择的实际 RTL 表达式。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from rtl_source_view import read_sources, module_definition, request_module, controller_module, source_manifest
import re
import runpy
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
CACHE = Path("rtl/npu/dma/cache/conv_windowed_cache.sv")
SELECTOR = Path("rtl/common/onehot_mux.sv")
PORTS = """input logic [1:0] fg_state,
input logic request_count,req_fire,lookup_input_valid,preview_source_select,bypass_q,windowed_q,
input logic req_window_index_valid,preview_index_valid,ram_wen,metadata_enable,metadata_fill_good,
input logic [31:0] head_address,req_addr,preview_addr,demand_addr,span_addr,req_window_index,preview_index,
input logic [SI-1:0] head_set,demand_set,demand_fill_set,fill_set"""
NAMES = ("fg_state", "request_count", "req_fire", "lookup_input_valid", "preview_source_select",
         "bypass_q", "windowed_q", "req_window_index_valid", "preview_index_valid", "ram_wen",
         "metadata_enable", "metadata_fill_good", "head_address", "req_addr", "preview_addr",
         "demand_addr", "span_addr", "req_window_index", "preview_index", "head_set", "demand_set",
         "demand_fill_set", "fill_set")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def model(name, source):
    controller = controller_module(source)
    source = request_module(source)
    start = source.index("  function automatic logic [SI-1:0] cache_set")
    function = source[start:source.index("  endfunction", start) + len("  endfunction")]
    if "  if (DEMAND_DEPTH == 1) begin : g_direct_read_source" in source:
        start = source.index("  if (DEMAND_DEPTH == 1) begin : g_direct_read_source")
    else:
        start = source.index("  always_comb begin\n    lookup_read_request = request_count")
    end = source.index("  if (DEMAND_DEPTH == 1) begin : g_saved_fill_match", start)
    lookup = source[start:end]
    lookup = lookup.replace("request_queue[DQ_AW'(request_head + DQ_AW'(1))]", "head_request")
    lookup = lookup.replace("request_queue[request_head]", "head_request")
    lookup = lookup.replace("  logic metadata_enable, metadata_fill_good;", "")
    if "module conv_cache_request_path" in source:
        start = controller.index("  localparam int WAY_DEPTH")
        end = controller.index("  logic [WAYS-1:0] metadata_lookup_valid_next", start)
        qualification = controller[start:end]
        start = source.index("  logic [1:0][1:0] input_conflict_results;")
        end = source.index("  // 快照内容在时钟边沿保存", start)
        qualification += source[start:end]
        declaration = re.search(r"^  logic \[1:0\] lookup_candidate_select;", source, re.M)
        if declaration is None:
            raise RuntimeError("未找到候选选择编号的完整类型")
        lookup = declaration[0] + "\n" + lookup
    else:
        start = source.index("  localparam int WAY_DEPTH")
        end = source.index("  for (genvar data_way", start)
        qualification = source[start:end]
    qualification = qualification.replace("request_queue[request_head]", "head_request")
    # 过程赋值的元素使用独立变量，其余元素保留连续赋值。
    first = qualification.index("    if (candidate == 2) begin : g_input")
    last = qualification.index("    end else begin : g_stored", first)
    selected = qualification[first:last]
    selected = selected.replace("lookup_candidate_fill_match[candidate]", "input_fill_match")
    selected = selected.replace("lookup_candidate_conflict[candidate]", "input_row_conflict")
    selected = selected.replace("begin : g_input", "begin : g_input\n"
        "      logic input_fill_match,input_row_conflict;\n"
        "      assign lookup_candidate_fill_match[candidate]=input_fill_match;\n"
        "      assign lookup_candidate_conflict[candidate]=input_row_conflict;")
    qualification = qualification[:first] + selected + qualification[last:]
    values = re.findall(r"\blookup_snapshot_valid\s*<=\s*(.*?);", source, re.S)
    if len(values) != 3:
        raise RuntimeError("快照有效状态的更新数量不符")
    return f"""module {name} #(parameter integer SI=4,LB=7,BUS_WIDTH=64,READ_WIDTH=128)(
{PORTS},output logic [1:0] observed);
  localparam integer SETS=1<<SI,LINE_BYTES=1<<LB,WB=LB-2;
  localparam integer DEMAND_DEPTH=1,DQ_CW=1,DQ_AW=1;
  localparam logic [1:0] FG_IDLE=0,FG_MISS=1,FG_RESP=2;
  typedef struct packed {{logic [31:0] address;logic [SI-1:0] set_index;}} demand_t;
  demand_t incoming_request,preview_request,head_request,lookup_input_request,lookup_read_request;
  logic [SI-1:0] lookup_set,lookup_read_set;
  logic [31:2] lookup_read_word;
  logic [3:0][SI-1:0] lookup_candidate_set;
  logic [1:0][SI-1:0] lookup_input_set;
  logic spec_read_conflict;
{function}
  assign incoming_request={{req_addr,cache_set(req_addr,windowed_q && req_window_index_valid,req_window_index)}};
  assign preview_request={{preview_addr,cache_set(preview_addr,windowed_q && preview_index_valid,preview_index)}};
  assign head_request={{head_address,head_set}};
  assign lookup_input_request=preview_source_select ? preview_request : incoming_request;
  assign lookup_set=bypass_q ? demand_fill_set : demand_set;
{lookup}
{qualification}
  assign observed={{({values[-1]}),spec_read_conflict}};
endmodule
"""


def support(source):
    return '\n'.join(module_definition(source, name) for name in ('conv_cache_input_set_match', 'conv_cache_lookup_qualification')) + '\n'

def bench():
    declarations = PORTS.replace("input logic", "logic").replace(",\n", ";\n") + ";\n"
    return f"""module tb;
  localparam integer SI=8,LB=7,BUS_WIDTH=64,READ_WIDTH=128,W=237+4*SI;
  {declarations}
  logic [W-1:0] stimulus,saved;
  logic [31:0] random_state=32'h7936eb45;
  logic [1:0] expected,actual;
  integer checks=0;
  assign {{{','.join(NAMES)}}}=stimulus;
  reference #(.SI(SI)) u_reference(.*,.observed(expected));
  candidate #(.SI(SI)) u_candidate(.*,.observed(actual));
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
      $fatal(1,"LOOKUP_FOUR_STATE_MISMATCH input=%b expected=%b actual=%b",stimulus,expected,actual);
    checks++;
  endtask
  initial begin
    for(integer trial=0;trial<16;trial++) begin
      for(integer b=0;b<W;b++) begin
        random_state={{random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]}};
        stimulus[b]=random_state[0];
      end
      if(trial%4==0) stimulus='0;
      if(trial%4==1) stimulus='1;
      if(trial%4==2) begin
        for(integer address_index=1;address_index<7;address_index++)
          stimulus[4*SI+32*address_index+:32]=stimulus[4*SI+:32];
        for(integer set_index=1;set_index<4;set_index++)
          stimulus[SI*set_index+:SI]=stimulus[0+:SI];
      end
      saved=stimulus;
      for(integer controls=0;controls<16384;controls++) begin
        stimulus=saved;
        for(integer b=0;b<7;b++) stimulus[W-7+b]=value((controls>>(2*b))&3);
        check();
      end
      for(integer b=0;b<W;b++) begin
        stimulus=saved;stimulus[b]=1'bx;check();
        stimulus[b]=1'bz;check();
      end
      stimulus=saved;
      for(integer b=0;b<W;b++)
        if(random_state[b%32]) stimulus[b]=(b%2)?1'bx:1'bz;
      check();
    end
    $display("LOOKUP_FOUR_STATE_PASS checks=%0d",checks);$finish;
  end
endmodule
"""


def run(command, log, cwd):
    with log.open("w") as stream:
        subprocess.run(list(map(str, command)), cwd=cwd, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def measure(root, out, cases):
    config = out / "synthesis_cases.json"
    config.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--source-root", root,
         "--case-config", config, "--cases", *cases, "--out", out / "mapping"],
        out / "mapping.log", root)
    helper = runpy.run_path(str(ROOT / "test/conv_frontend/tools/measure_complete_paths.py"))
    records = {}
    for label in cases:
        folder = out / "mapping" / label
        module = json.loads((folder / "mapped.json").read_text())["modules"][cases[label]["top"]]
        graph, counts = helper["add_interface_boundaries"](module)
        report = helper["measure"](module)
        selected = set()

        def start(cell_name, cell, port):
            wanted = any(cell_name.startswith("__measurement_interface__input:" + name + "[")
                         for name in ("preview_addr", "preview_index"))
            if wanted:
                selected.add((cell_name, port))
            return wanted

        result = helper["connected_paths"](graph, root_filter=start,
            sink_filter=lambda name, cell, port: name.startswith("__measurement_interface__output:observed["))
        if not result["graph_complete"] or not selected:
            raise RuntimeError("缓存查询资格的局部连接图不完整")
        report["preview_inputs"] = dict(selected_start_ports=len(selected), selected_endpoint_ports=2,
            maximum_combinational_cells=result["longest_register_path_cells"],
            paths=result["register_to_register_paths"], graph_complete=True)
        (folder / "complete_paths.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        records[label] = dict(maximum_combinational_cells=report["maximum_combinational_cells"],
            preview_depth=result["longest_register_path_cells"], selected_start_ports=len(selected),
            selected_endpoint_ports=2, interface_bits=counts, graph_complete=True,
            mapped_sha256=digest(folder / "mapped.json"))
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--reference-ref", default="795c8b14")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--map", action="store_true")
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = read_sources(root, CACHE)
    original = (read_sources(args.reference_root.resolve(), CACHE) if args.reference_root else
        read_reference_file(ROOT, args.reference_ref, CACHE, text=True))
    models = {"reference": model("reference", original), "candidate": model("candidate", current)}
    helpers = support(current)
    connections = ",".join(f".{name}({name})" for name in NAMES)
    proof = out / "comparison.sv"
    proof.write_text("\n".join(models.values()) + helpers + f"""module comparison #(
parameter integer SI=4,LB=7,BUS_WIDTH=64,READ_WIDTH=128)({PORTS},output logic equivalent);
  logic [1:0] expected,actual;
  reference #(.SI(SI),.LB(LB),.BUS_WIDTH(BUS_WIDTH),.READ_WIDTH(READ_WIDTH))
      u_reference({connections},.observed(expected));
  candidate #(.SI(SI),.LB(LB),.BUS_WIDTH(BUS_WIDTH),.READ_WIDTH(READ_WIDTH))
      u_candidate({connections},.observed(actual));
  assign equivalent=expected==actual;
endmodule
""")
    profiles = []
    for si, lb, bus, read in ((1,4,32,32), (4,4,64,128), (4,4,64,256),
                            (4,7,64,128), (8,7,64,128)):
        parameters = dict(SI=si, LB=lb, BUS_WIDTH=bus, READ_WIDTH=read)
        name = f"si{si}_lb{lb}_read{read}"
        script, log = out / f"{name}.ys", out / f"{name}.log"
        script.write_text("read_slang --top comparison " + " ".join(f"-G{k}={v}" for k,v in parameters.items()) +
            " " + shlex.join([str(proof), str(root / SELECTOR)]) +
            "\nprep -top comparison -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log, root)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError("缓存查询资格证明未完成")
        profiles.append(dict(parameters=parameters, passed=True, log_sha256=digest(log)))
    four = out / "four_state.sv"
    four.write_text("\n".join(models.values()) + helpers + bench())
    run(["iverilog", "-g2012", "-s", "tb", "-o", out / "four_state.vvp", four, root / SELECTOR],
        out / "four_state_compile.log", root)
    run(["vvp", out / "four_state.vvp"], out / "four_state.log", root)
    matched = re.search(r"LOOKUP_FOUR_STATE_PASS checks=(\d+)", (out / "four_state.log").read_text())
    if not matched or int(matched[1]) != 16*(16384+2*(237+32)+1):
        raise RuntimeError("缓存查询资格四态检查数量不符")
    report = dict(passed=True, actual_rtl_expressions=True, external_inputs_constrained=False,
        source_sha256=digest(root / CACHE), selector_sha256=digest(root / SELECTOR),
        reference_sha256=hashlib.sha256(original.encode()).hexdigest(), sat_profiles=profiles,
        reference_root=str(args.reference_root.resolve()) if args.reference_root else None,
        reference_ref=None if args.reference_root else args.reference_ref,
        four_state_cases=int(matched[1]), four_state_log_sha256=digest(out / "four_state.log"))
    if args.map:
        cases = {}
        for si in (4,8):
            for label, source in models.items():
                path = out / f"{label}.sv"
                path.write_text(source + helpers)
                cases[f"{label}_si{si}"] = dict(top=label, sources=[str(path),str(root / SELECTOR)],
                    options=[f"-GSI={si}"], configuration="缓存实际读取冲突和快照资格组合表达式")
        report["mapping"] = measure(root, out, cases)
    if current != read_sources(root, CACHE):
        raise RuntimeError("查询资格检查期间缓存源码发生变化")
    report["dependency_sha256"] = source_manifest(root, CACHE)
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
