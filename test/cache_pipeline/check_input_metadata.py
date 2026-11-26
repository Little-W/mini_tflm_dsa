#!/usr/bin/env python3
"""验证正式请求和预读请求的元数据读取、写入转发及命中保存。"""
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
METADATA = Path("rtl/npu/dma/cache/conv_cache_metadata_way.sv")
SELECTOR = Path("rtl/common/onehot_mux.sv")
PORTS = """input logic clk,rst_n,cfg_accept,bypass_q,req_fire,lookup_input_valid,
input logic request_count,request_head,preview_source_select,lookup_valid_saved,
input logic [1:0] fg_state,
input logic [31:0] head_address,request_address,preview_address,work_address,demand_addr,
input logic [SI-1:0] head_set,request_set,preview_set,work_set,demand_set,demand_fill_set,
input logic i_metadata_enable,i_clearing,i_metadata_fill,i_fill_selected,i_metadata_fill_good,i_bypass,
input logic [SI-1:0] i_clear_set,i_fill_set,
input logic [SETS-1:0][31:LB] tag_memory,
input logic [SETS-1:0] valid_memory"""
NAMES = ("clk", "rst_n", "cfg_accept", "bypass_q", "req_fire", "lookup_input_valid",
         "request_count", "request_head", "preview_source_select", "lookup_valid_saved",
         "fg_state", "head_address", "request_address", "preview_address", "work_address",
         "demand_addr", "head_set", "request_set", "preview_set", "work_set", "demand_set",
         "demand_fill_set", "i_metadata_enable", "i_clearing", "i_metadata_fill", "i_fill_selected",
         "i_metadata_fill_good", "i_bypass", "i_clear_set", "i_fill_set", "tag_memory", "valid_memory")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assignment(source, name):
    match = re.search(r"\bassign\s+" + re.escape(name) + r"\s*=.*?;", source, re.S)
    if match is None:
        raise RuntimeError("缺少实际信号赋值：" + name)
    return match.group()


def model(name, cache, metadata):
    controller = controller_module(cache)
    cache = request_module(cache)
    metadata = module_definition(metadata, "conv_cache_metadata_way")
    raw = "o_lookup_source_tags" in metadata
    count = 4 if raw else 3
    tag_name = "lookup_source_tags" if raw else "lookup_candidate_tags"
    valid_name = "lookup_source_valid_next" if raw else "lookup_candidate_valid_next"
    metadata_valid = "o_lookup_source_valid" if raw else "o_lookup_candidate_valid"
    metadata_tags = "o_lookup_source_tags" if raw else "o_lookup_candidate_tags"
    start = cache.index("  end else begin : g_direct_tag_compare")
    start = cache.index("\n", start) + 1
    end = cache.index("  if (DEMAND_DEPTH == 1) begin : g_direct_response_lookup", start)
    direct = cache[start:end].rsplit("  end", 1)[0]
    if "logic [WAYS-1:0] lookup_valid_next;" not in direct:
        direct = ("    logic [WAYS-1:0] lookup_valid_next;\n"
                  "    logic [WAYS-1:0][31:LB] lookup_tag_raw;\n"
                  "    logic [WAYS-1:0][3:0][31:LB] lookup_source_tags;\n"
                  "    logic [WAYS-1:0][3:0] lookup_source_valid_next;\n" + direct)
    registered_tags = "lookup_forwarded_valid_q" in direct
    first = direct.index("    // 配置接收")
    last = direct.index("    // 单个在途请求", first)
    direct = direct[:first] + "    assign cache_active_q=1'b1;\n" + direct[last:]
    direct = direct.replace("request_queue[request_head]", "head_request")
    # 单独声明过程赋值的位，其余位继续使用原有连续赋值。
    direct = direct.replace("work_candidate_hits[3]", "input_demand_hit")
    direct = direct.replace("logic [3:0] work_candidate_hits;",
        "logic [3:0] work_candidate_hits;\n    logic input_demand_hit;\n"
        "    assign work_candidate_hits[3]=input_demand_hit;")
    registered_capture = ""
    if registered_tags:
        direct = direct.replace("work_request.address", "registered_work_address")
        direct = direct.replace("demand_addr[", "registered_demand_address[")
        registered_capture = """
  logic [0:0][31:LB] lookup_tag;
  logic [31:0] registered_work_address,registered_demand_address;
  always_ff @(posedge clk) begin
    lookup_tag[0]<=tags_raw_data[0];
    registered_work_address<=lookup_read_request.address;
    if(req_fire) registered_demand_address<=work_address;
    else registered_demand_address<=demand_addr;
  end
"""

    if "  if (DEMAND_DEPTH == 1) begin : g_direct_read_source" in cache:
        start = cache.index("  if (DEMAND_DEPTH == 1) begin : g_direct_read_source")
    else:
        start = cache.index("  always_comb begin\n    lookup_read_request = request_count")
    end = cache.index("  logic [3:0][31:2] lookup_candidate_word", start)
    lookup = cache[start:end]
    lookup = lookup.replace("request_queue[DQ_AW'(request_head + DQ_AW'(1))]", "head_request")
    lookup = lookup.replace("request_queue[request_head]", "head_request")
    # 单名额队列的计数宽度为一位，下一队列位置分支不会被选择。
    assert ("localparam int DQ_CW=$clog2(DEMAND_DEPTH+1);" in cache or
            "localparam int p_queue_count_width = $clog2(p_demand_depth+1)" in cache)

    start = metadata.index("      assign valid_i_rd_addr[0]", metadata.index("g_saved_lookup_valid"))
    end = metadata.index("      always_ff", start)
    valid_reads = metadata[start:end]
    start = metadata.index("    if (DEMAND_DEPTH == 1) begin : g_lookup_candidate_tags")
    end = metadata.index("    assign o_tags[0]", start)
    tag_reads = metadata[start:end]
    write_controls = "\n".join(assignment(metadata, name)
        for name in ("valid_i_wr_en", "valid_i_wr_addr", "valid_i_wr_data"))
    if "valid_clear_write" in metadata:
        write_controls += "\n" + "\n".join(assignment(metadata, name)
            for name in ("valid_clear_write", "valid_fill_write", "valid_fill_data"))
    ports = f"""module {name} #(parameter integer SETS=4,SI=$clog2(SETS),LB=7)(
{PORTS},output logic [1:0] observed);
  localparam integer WAYS=1,DEMAND_DEPTH=1,DQ_CW=1,DQ_AW=1,WI=1;
  localparam bit p_preview_request=1'b1,p_parallel_preview=1'b1;
  localparam integer p_valid_read_ports={10 if raw else 9},p_tag_read_ports={9 if raw else 8};
  localparam logic [1:0] FG_IDLE=0,FG_MISS=1,FG_RESP=2;
  typedef struct packed {{logic [31:0] address;logic [SI-1:0] set_index;}} demand_t;
  demand_t incoming_request,preview_request,work_request,lookup_input_request;
  demand_t head_request,lookup_read_request;
  logic [SI-1:0] lookup_set,lookup_read_set;
  logic [31:2] lookup_read_word;
  logic [3:0][SI-1:0] lookup_candidate_set;
  logic [3:0][SI-1:0] i_lookup_candidate_set;
  logic [1:0][SI-1:0] i_lookup_input_set;
  logic [5:0][SI-1:0] i_read_set;
  logic [p_valid_read_ports-1:0][SI-1:0] valid_i_rd_addr;
  logic [p_valid_read_ports-1:0][0:0] valid_o_rd_data;
  logic valid_i_wr_en,valid_clear_write,valid_fill_write,valid_fill_data;
  logic [SI-1:0] valid_i_wr_addr;
  logic [0:0] valid_i_wr_data;
  logic [p_tag_read_ports-1:0][SI-1:0] tags_i_rd_addr;
  logic [p_tag_read_ports-1:0][31:LB] tags_raw_data;
  logic [{count-1}:0] {metadata_valid};
  logic [{count-1}:0][31:LB] {metadata_tags};
  logic lookup_valid_raw;
  logic [0:0] work_tag_hits,demand_tag_hits,fill_way;
  assign fill_way=1'b0;
  if(1) begin:g_saved_fill_match
    wire fill_active_q=1'b0,lookup_fill_set_match_q=1'b0;
  end
  assign incoming_request={{request_address,request_set}};
  assign preview_request={{preview_address,preview_set}};
  assign work_request={{work_address,work_set}};
  assign head_request={{head_address,head_set}};
  assign lookup_input_request=preview_source_select ? preview_request : incoming_request;
  {assignment(cache, 'lookup_set')}
{lookup}
  assign lookup_candidate_set={{(bypass_q ? demand_fill_set : demand_set),
                               lookup_input_request.set_index,head_set,head_set}};
  assign i_lookup_candidate_set=lookup_candidate_set;
  assign i_lookup_input_set={{preview_set,request_set}};
  assign i_read_set={{ {{5*SI{{1'b0}}}},lookup_read_set}};
{write_controls}
{valid_reads}
  for(genvar p=1;p<6;p++) begin:g_unused_valid
    assign valid_i_rd_addr[p]='0;
  end
  for(genvar p=0;p<p_valid_read_ports;p++) begin:g_valid_data
    assign valid_o_rd_data[p][0]=valid_memory[valid_i_rd_addr[p]];
  end
  assign tags_i_rd_addr[0]=lookup_read_set;
  for(genvar p=1;p<5;p++) begin:g_unused_tags
    assign tags_i_rd_addr[p]='0;
  end
  for(genvar p=0;p<p_tag_read_ports;p++) begin:g_tag_data
    assign tags_raw_data[p]=tag_memory[tags_i_rd_addr[p]];
  end
{tag_reads}
{registered_capture}
{direct}
  assign lookup_tag_raw[0]=tags_raw_data[0];
  assign {tag_name}[0]={metadata_tags};
  assign lookup_valid_raw=valid_i_wr_en && valid_i_wr_addr==lookup_read_set ?
      valid_i_wr_data[0] : valid_o_rd_data[0][0];
  always_comb begin
    lookup_valid_next[0]=lookup_valid_raw;
    {valid_name}[0]={metadata_valid};
    case(^{{rst_n,cfg_accept}})
      1'b0,1'b1:begin end
      default:begin
        lookup_valid_next[0]=lookup_valid_saved;
        {valid_name}[0]={count}'({{{count}{{lookup_valid_saved}}}});
      end
    endcase
  end
  assign observed={{work_tag_hits[0],demand_tag_hits[0]}};
endmodule
"""
    if "conv_cache_lookup_valid_select u_valid_select" in controller:
        ports = ports.replace("    lookup_valid_next[0]=lookup_valid_raw;", "")
        ports = ports.replace("        lookup_valid_next[0]=lookup_valid_saved;", "")
        capture = f"""  conv_cache_lookup_valid_select u_valid_select (
    .rst_n(rst_n),.i_cfg_accept(cfg_accept),.i_foreground_state(fg_state),
    .i_request_occupied(request_count),.i_request_fire(req_fire),
    .i_input_valid(lookup_input_valid),.i_preview_selected(preview_source_select),
    .i_source_valid({metadata_valid}),.i_address_valid(lookup_valid_raw),
    .i_saved_valid(lookup_valid_saved),.o_valid(lookup_valid_next[0]));
"""
        ports = ports.replace("  assign observed=", capture + "  assign observed=")
    return ports


def bench():
    declarations = PORTS.replace("input logic", "logic").replace(",\n", ";\n") + ";\n"
    names = ",".join(name for name in NAMES if name != "clk")
    return f"""module tb;
  localparam integer SETS=4,SI=2,LB=7;
  {declarations}
  logic [1:0] expected,actual;
  localparam integer W=177+8*SI+SETS*(33-LB);
  logic [W-1:0] stimulus,saved;
  logic [31:0] random_state=32'h7458b621;
  integer checks=0;
  assign {{{names}}}=stimulus;
  reference u_reference(.*,.observed(expected));
  candidate u_candidate(.*,.observed(actual));
  task automatic check;
    clk=0;#1;clk=1;#1;
    if(expected!==actual)
      $fatal(1,"METADATA_FOUR_STATE_MISMATCH stimulus=%b expected=%b actual=%b",stimulus,expected,actual);
    checks=checks+1;clk=0;
  endtask
  initial begin
    clk=0;
    for(integer trial=0;trial<128;trial++) begin
      for(integer b=0;b<W;b++) begin
        random_state={{random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]}};
        stimulus[b]=random_state[0];
      end
      if(trial%4==0) begin
        stimulus='0;
        stimulus[0+:SETS]='1;
      end
      if(trial%4==1) begin
        stimulus='1;
      end
      check();saved=stimulus;
      for(integer b=0;b<W;b++) begin
        stimulus=saved;stimulus[b]=1'bx;check();
        stimulus[b]=1'bz;check();
      end
      stimulus=saved;
      for(integer b=0;b<W;b++)
        if(random_state[b%32]) stimulus[b]=(b%2)?1'bx:1'bz;
      check();
    end
    if(checks!=128*(2+2*W)) $fatal(1,"Unexpected metadata coverage %0d",checks);
    $display("METADATA_FOUR_STATE_PASS checks=%0d",checks);$finish;
  end
endmodule
"""


def run(command, log, cwd):
    with log.open("w") as output:
        subprocess.run(list(map(str, command)), cwd=cwd, stdout=output,
                       stderr=subprocess.STDOUT, check=True)


def measure_cases(root, out, models, support):
    cases = {}
    for label, source in models.items():
        path = out / (label + ".sv")
        path.write_text(source + support)
        cases[label] = dict(top=label, sources=[str(path), str(root / SELECTOR)],
            options=["-GSETS=16", "-GSI=4", "-GLB=7"],
            configuration="真实元数据读取和命中保存，存储内容为自由输入")
    config = out / "synthesis_cases.json"
    config.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    mapped_root = out / "mapping"
    run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--source-root", root,
         "--case-config", config, "--cases", "reference", "candidate", "--out", mapped_root],
        out / "mapping.log", root)
    helper = runpy.run_path(str(ROOT / "test/conv_frontend/tools/measure_complete_paths.py"))
    records = {}
    for label in models:
        folder = mapped_root / label
        module = json.loads((folder / "mapped.json").read_text())["modules"][label]
        observed, counts = helper["add_interface_boundaries"](module)
        report = helper["measure"](module)
        groups = {}
        for name, prefixes in (("preview_set", ("preview_set",)),
                               ("input_sets", ("preview_set", "request_set")),
                               ("input_addresses", ("preview_address", "request_address")),
                               ("selection", ("request_count", "preview_source_select", "fg_state", "req_fire"))):
            starts, ends = set(), set()

            def source(cell_name, cell, port):
                selected = any(cell_name.startswith("__measurement_interface__input:" + p + "[")
                               for p in prefixes)
                if selected:
                    starts.add((cell_name, port))
                return selected

            def target(cell_name, cell, port):
                selected = not cell_name.startswith("__measurement_interface__")
                if selected:
                    ends.add((cell_name, port))
                return selected

            paths = helper["connected_paths"](observed, root_filter=source, sink_filter=target)
            register_count = len({name for name, _ in ends})
            if not paths["graph_complete"] or not starts or register_count < 2:
                raise RuntimeError("元数据局部连接图不完整")
            groups[name] = dict(selected_start_ports=len(starts), selected_endpoint_ports=len(ends),
                selected_endpoint_registers=register_count,
                maximum_combinational_cells=paths["longest_register_path_cells"], graph_complete=True,
                paths=paths["register_to_register_paths"])
        report["critical_scopes"].update(groups)
        report["scope"] = "实际元数据组合逻辑与接收状态，标签和有效位内容为自由输入"
        (folder / "complete_paths.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        records[label] = dict(maximum_combinational_cells=report["maximum_combinational_cells"],
            interface_bits=counts, resources=report["resources"],
            critical_scopes={name: {k: v for k, v in record.items() if k != "paths"}
                             for name, record in groups.items()},
            mapped_sha256=digest(folder / "mapped.json"), report_sha256=digest(folder / "complete_paths.json"))
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--reference-ref", default="56d098ed")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--map", action="store_true")
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    original = args.reference_root.resolve() if args.reference_root else None
    out.mkdir(parents=True, exist_ok=True)
    sources = {str(p): digest(root / p) for p in (CACHE, METADATA, SELECTOR)}
    reference_sources = {path: read_sources(original, path) if original else
        read_reference_file(ROOT, args.reference_ref, path, text=True)
        for path in (CACHE, METADATA)}
    models = {"reference": model("reference", reference_sources[CACHE], reference_sources[METADATA]),
              "candidate": model("candidate", read_sources(root, CACHE), read_sources(root, METADATA))}
    combined_sources = read_sources(root, CACHE) + "\n" + read_sources(root, METADATA)
    support_names = ["conv_cache_valid_forward", "conv_cache_tag_qualification", "conv_cache_snapshot_equal"]
    if "conv_cache_lookup_valid_select u_valid_select" in controller_module(combined_sources):
        support_names.append("conv_cache_lookup_valid_select")
    support = "\n".join(module_definition(combined_sources, name) for name in support_names) + "\n"
    connection = ",".join(f".{name}({name})" for name in NAMES)
    comparison = "\n".join(models.values()) + support + f"""module comparison #(
  parameter integer SETS=4,SI=$clog2(SETS),LB=7)(
{PORTS},output logic equivalent);
  logic [1:0] expected,actual;
  reference #(.SETS(SETS),.SI(SI),.LB(LB)) u_reference({connection},.observed(expected));
  candidate #(.SETS(SETS),.SI(SI),.LB(LB)) u_candidate({connection},.observed(actual));
  assign equivalent=expected==actual;
endmodule
"""
    proof = out / "comparison.sv"
    proof.write_text(comparison)
    script = out / "formal.ys"
    script.write_text("read_slang --top comparison " + shlex.join([str(proof), str(root / SELECTOR)]) +
        "\nprep -top comparison -flatten\nopt -full\n"
        "sat -seq 2 -prove-skip 1 -set-init-zero -verify -prove equivalent 1 -show-inputs -show-outputs\n")
    run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script],
        out / "formal.log", root)
    if "SAT proof finished - no model found: SUCCESS!" not in (out / "formal.log").read_text():
        raise RuntimeError("元数据读取等价证明未完成")
    four_state = out / "four_state.sv"
    four_state.write_text("\n".join(models.values()) + support + bench())
    binary = out / "four_state.vvp"
    run(["iverilog", "-g2012", "-s", "tb", "-o", binary, four_state, root / SELECTOR],
        out / "four_state_compile.log", root)
    run(["vvp", binary], out / "four_state.log", root)
    match = re.search(r"METADATA_FOUR_STATE_PASS checks=(\d+)", (out / "four_state.log").read_text())
    if match is None or int(match[1]) != 76288:
        raise RuntimeError("元数据四态检查未完成")
    if sources != {str(p): digest(root / p) for p in (CACHE, METADATA, SELECTOR)}:
        raise RuntimeError("验证期间生产源码发生变化")
    result = dict(passed=True, source_sha256=sources,
        reference_root=str(original) if original else None, reference_ref=args.reference_ref if not original else None,
        reference_sha256={str(path): hashlib.sha256(text.encode()).hexdigest()
                          for path, text in reference_sources.items()},
        actual_metadata_read_assignments=True, actual_hit_capture_block=True,
        memory_contents_unconstrained=True, sat_properties=1,
        four_state_input_bits=297, four_state_cases=int(match[1]),
        proof_sha256=digest(proof), formal_log_sha256=digest(out / "formal.log"),
        four_state_log_sha256=digest(out / "four_state.log"))
    if args.map:
        result["mapping"] = measure_cases(root, out, models, support)
    if sources != {str(p): digest(root / p) for p in (CACHE, METADATA, SELECTOR)}:
        raise RuntimeError("验证期间生产源码发生变化")
    result["dependency_sha256"] = source_manifest(root, CACHE)
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
