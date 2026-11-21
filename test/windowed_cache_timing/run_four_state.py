#!/usr/bin/env python3
"""使用实际 RTL 表达式检查缓存查询和有效位保存的四态行为。"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "build/windowed_cache_timing"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assignment(source, name):
    match = re.search(r"  assign " + re.escape(name) + r"\s*=.*?;", source, re.S)
    if match is None:
        raise RuntimeError(f"Missing RTL assignment: {name}")
    return match[0]


def run_test(out, name, source, sources=()):
    generated = out / f"{name}.sv"
    binary = out / name
    generated.write_text(source)
    with (out / f"{name}.compile.log").open("w") as log:
        subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(binary),
                        str(generated), *map(str, sources)], check=True,
                       stdout=log, stderr=subprocess.STDOUT)
    completed = subprocess.run(["vvp", str(binary)], text=True,
                               capture_output=True, timeout=120, check=True)
    log = out / f"{name}.log"
    log.write_text(completed.stdout + completed.stderr)
    match = re.search(r"FOUR_STATE_PASS checks=(\d+)", completed.stdout)
    if match is None:
        raise RuntimeError(str(log))
    return {"name": name, "passed": True, "checks": int(match[1]),
            "generated_sha256": digest(generated), "log_sha256": digest(log)}


def control_test(source, sets, ways, depth):
    si = (sets - 1).bit_length()
    wi = max(1, (ways - 1).bit_length())
    dcw = depth.bit_length()
    inputs = [("fg_state", 2), ("bypass_q", 1), ("configured", 1),
              ("clearing", 1), ("work_valid", 1), ("response_count", dcw),
              ("lookup_snapshot_valid", 1), ("work_word_matches_q", 1),
              ("work_snapshot_matches_q", 1), ("demand_word_matches_q", 1),
              ("lookup_snapshot_set", si), ("demand_fill_set", si),
              ("demand_set", si), ("work_set", si), ("work_range", 1),
              ("demand_range", 1), ("demand_filled", 1),
              ("work_tag_hits", ways), ("demand_tag_hits", ways),
              ("select_way", wi), ("demand_fill_way", wi), ("select_set", si),
              ("demand_addr", 32), ("select_addr", 32), ("completing_demand", 1)]
    width = sum(n for _, n in inputs)
    declarations = "\n".join(f"  logic [{n-1}:0] {name};" for name, n in inputs)
    drive = "{" + ",".join(name for name, _ in inputs) + "}"
    common = "\n".join(assignment(source, name) for name in
                       ("req_fire", "lookup_set", "lookup_range",
                        "work_lookup_ready", "demand_lookup_ready", "lookup_ready", "lookup_hit"))
    common = common.replace("work_request.set_index", "work_set")
    if "localparam int p_address_compare_groups" in source:
        begin = source.index("  localparam int p_address_compare_groups")
        end = source.index('  (* keep = "true" *) logic select_common_ready', begin)
        common += "\nlogic [31:0] pf_addr; assign pf_addr = 32'd0;\n" + source[begin:end]

    if "logic work_capacity_ready, work_snapshot_ready;" in source:
        begin = source.index('  (* keep = "true" *) logic work_capacity_ready, work_snapshot_ready;')
        end = source.index("  assign req_fire", begin)
        common += source[begin:end]
    else:
        common += assignment(source, "work_ready")
    begin = source.index("  always_comb begin\n    lookup_way = '0;")
    end = source.index("\n\n  always_comb begin\n    pf_hit_raw", begin)
    common += source[begin:end]
    begin = source.index("  logic [WAYS-1:0] demand_selected_victim;")
    end = source.index("\n  always_comb begin\n    select_launch =", begin)
    victim = source[begin:end]
    begin = source.index("  end else begin : g_queued_response_lookup")
    begin = source.index("\n", begin) + 1
    end = source.index("    assign core_rsp_data", begin)
    fast = source[begin:end]
    if "logic select_demand_snapshot_ready, select_demand_request_ready;" in source:
        begin = source.index('  (* keep = "true" *) logic select_demand_snapshot_ready, select_demand_request_ready;')
        end = source.index("  logic [WAYS-1:0] demand_selected_victim;", begin)
        demand = source[begin:end]
    else:
        demand = assignment(source, "select_demand_ready")
    return f"""module tb;
  localparam integer SETS={sets}, WAYS={ways}, DEMAND_DEPTH={depth};
  localparam integer SI={si}, WI={wi}, DQ_CW={dcw}, INPUT_WIDTH={width};
  localparam logic [1:0] FG_IDLE=0, FG_MISS=1, FG_RESP=2;
{declarations}
  logic work_ready, req_fire, work_lookup_ready, demand_lookup_ready;
  logic lookup_ready, lookup_hit, lookup_range;
  logic [SI-1:0] lookup_set;
  logic [WI-1:0] lookup_way;
  logic select_victim_conflict, fast_hit_response, select_demand_ready;
  logic expected_victim, expected_fast, expected_work_ready, expected_demand_ready;
  logic [INPUT_WIDTH-1:0] stimulus, saved;
  logic [31:0] random_state=32'h638f_29c5;
  integer checks=0;
  assign {drive}=stimulus;
{common}
{victim}
{fast}
{demand}
  assign expected_work_ready=configured && !clearing && (bypass_q || work_lookup_ready) &&
      response_count<DQ_CW'(DEMAND_DEPTH) && (fg_state==FG_IDLE || fg_state==FG_RESP);
  assign expected_victim=fg_state==FG_MISS && lookup_hit &&
      select_set==lookup_set && select_way==lookup_way;
  assign expected_fast=fg_state==FG_IDLE && work_valid && expected_work_ready && lookup_range && lookup_hit;
  assign expected_demand_ready=fg_state==FG_MISS && demand_addr==select_addr &&
      (bypass_q || lookup_ready) && lookup_range && !completing_demand;
  task automatic check;
    begin
      #1;
      if (select_victim_conflict !== expected_victim || fast_hit_response !== expected_fast ||
          work_ready !== expected_work_ready || select_demand_ready !== expected_demand_ready)
        $fatal(1,"control stimulus=%b victim=%b/%b fast=%b/%b work=%b/%b demand=%b/%b",stimulus,
          select_victim_conflict,expected_victim,fast_hit_response,expected_fast,
          work_ready,expected_work_ready,select_demand_ready,expected_demand_ready);
      checks=checks+4;
    end
  endtask
  task automatic randomize;
    begin
      for(integer bit_index=0; bit_index<INPUT_WIDTH; bit_index=bit_index+1) begin
        random_state={{random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]}};
        stimulus[bit_index]=random_state[0];
      end
    end
  endtask
  initial begin
    for(integer trial=0;trial<2048;trial=trial+1) begin
      randomize();
      if(trial%2==0) stimulus[33 +: 32]=stimulus[1 +: 32];
      check(); saved=stimulus;
      for(integer bit_index=0;bit_index<INPUT_WIDTH;bit_index=bit_index+1) begin
        stimulus=saved;stimulus[bit_index]=1'bx;check();
        stimulus=saved;stimulus[bit_index]=1'bz;check();
      end
      stimulus=saved;
      for(integer bit_index=0;bit_index<INPUT_WIDTH;bit_index=bit_index+1)
        if(random_state[(bit_index+trial)%32]) stimulus[bit_index]=(bit_index%2)?1'bx:1'bz;
      check();
    end
    $display("FOUR_STATE_PASS checks=%0d",checks);$finish;
  end
endmodule
"""


def validity_test(source, sets):
    si = (sets - 1).bit_length()
    begin = source.index("    end else begin : g_current_lookup_valid")
    begin = source.index("      always_ff", begin)
    end = source.index("      assign valid_read_value[0]", begin)
    capture = source[begin:end]
    width = 2 * si + 7
    return f"""module tb;
  localparam integer SI={si}, SETS={sets}, INPUT_WIDTH={width};
  logic clk=0;
  logic rst_n,cfg_valid,cfg_ready,write_request,write_data,unused0,unused1;
  logic [SI-1:0] valid_i_wr_addr,lookup_read_set,lookup_snapshot_set;
  logic valid_i_wr_en;
  logic [0:0] valid_i_wr_data;
  logic [0:0][0:0] valid_o_rd_data;
  logic lookup_valid_q;
  logic [1:0][SI-1:0] addresses;
  logic [1:0][0:0] values;
  logic [INPUT_WIDTH-1:0] stimulus,saved;
  logic [31:0] random_state=32'h1942_cd75;
  integer checks=0;
  assign {{rst_n,cfg_valid,cfg_ready,write_request,write_data,unused0,unused1,
           valid_i_wr_addr,lookup_read_set}}=stimulus;
  assign valid_i_wr_en=rst_n && !(cfg_valid&&cfg_ready) && write_request;
  assign valid_i_wr_data[0]=write_data;
  assign addresses[0]=lookup_snapshot_set;
  assign addresses[1]=lookup_read_set;
  assign valid_o_rd_data[0][0]=values[1][0];
  regfile #(.p_data_width(1),.p_depth(SETS),.p_addr_width(SI),.p_write_unit(1),
    .p_read_ports(2),.p_sync_read(1'b0)) u_storage(
    .clk(clk),.i_wr_en(valid_i_wr_en),.i_wr_addr(valid_i_wr_addr),
    .i_wr_data(valid_i_wr_data),.i_wr_mask(1'b1),.i_rd_en(2'b11),
    .i_rd_addr(addresses),.o_rd_data(values));
  always_ff @(posedge clk) begin
    if(!rst_n) begin end
    else if(cfg_valid&&cfg_ready) begin end
    else lookup_snapshot_set<=lookup_read_set;
  end
{capture}
  task automatic check;
    begin
      #1;clk=1;#1;
      if(lookup_valid_q !== values[0][0])
        $fatal(1,"valid stimulus=%b stored=%b expected=%b",stimulus,lookup_valid_q,values[0][0]);
      checks=checks+1;clk=0;#1;
    end
  endtask
  task automatic randomize;
    begin
      for(integer bit_index=0;bit_index<INPUT_WIDTH;bit_index=bit_index+1) begin
        random_state={{random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]}};
        stimulus[bit_index]=random_state[0];
      end
    end
  endtask
  initial begin
    for(integer address=0;address<SETS;address=address+1) begin
      stimulus={{1'b1,1'b0,1'b0,1'b1,address[0],2'b00,SI'(address),SI'(address)}};
      check();
    end
    for(integer trial=0;trial<4096;trial=trial+1) begin
      randomize();check();saved=stimulus;
      for(integer bit_index=0;bit_index<INPUT_WIDTH;bit_index=bit_index+1) begin
        stimulus=saved;stimulus[bit_index]=1'bx;check();
        stimulus=saved;stimulus[bit_index]=1'bz;check();
      end
      stimulus=saved;
      for(integer bit_index=0;bit_index<INPUT_WIDTH;bit_index=bit_index+1)
        if(random_state[(bit_index+trial)%32]) stimulus[bit_index]=(bit_index%2)?1'bx:1'bz;
      check();
    end
    $display("FOUR_STATE_PASS checks=%0d",checks);$finish;
  end
endmodule
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=BASE/"four_state")
    args = parser.parse_args()
    root = args.source_root.resolve()
    rtl = root / "rtl/npu/dma/cache/conv_read_cache.sv"
    storage = root / "rtl/common/regfile.v"
    source = rtl.read_text().split("module conv_windowed_cache #(", 1)[1]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes = {str(path): digest(path) for path in (rtl, storage, Path(__file__))}
    records = []
    for sets, ways, depth in ((2, 1, 2), (16, 2, 2), (4, 2, 4)):
        records.append(run_test(out, f"control_{sets}_{ways}_{depth}",
                                control_test(source, sets, ways, depth)))
        print(json.dumps(records[-1]), flush=True)
    for sets in (2, 16):
        records.append(run_test(out, f"validity_{sets}", validity_test(source, sets), [storage]))
        print(json.dumps(records[-1]), flush=True)
    assert hashes == {path: digest(Path(path)) for path in hashes}
    (out / "summary.json").write_text(json.dumps({"passed": True,
        "source_sha256": hashes, "profiles": records,
        "total_checks": sum(record["checks"] for record in records)}, indent=2) + "\n")


if __name__ == "__main__":
    main()
