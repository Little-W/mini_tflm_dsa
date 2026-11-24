#!/usr/bin/env python3
"""验证组范围资格在配置、解码和连续描述符接收阶段的保存。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SOURCES = ("rtl/common/add_equal.sv", "rtl/npu/conv/conv_im2col_descriptor.sv")


def model(source: str) -> str:
    first = source.index("  // 组内范围按描述符列数拆分")
    last = source.index("  // 像素候选", first)
    logic = source[first:last]
    columns = re.search(r"^  assign prepared_columns = .*;$", source, re.M)
    if columns is None:
        raise ValueError("Prepared column expression is unavailable")
    return """module comparison #(parameter int p_size=16)(
input logic i_clk,i_rst_n,input logic [1:0] i_event,
input logic i_valid,i_window_select,input logic [15:0] i_group,i_channel,i_window_channel,
input logic [$clog2(p_size+1)-1:0] i_tile_cols,output logic equivalent);
localparam int p_tile_count_w=$clog2(p_size+1);
localparam bit p_register_descriptor=0;
localparam logic [3:0] K_DECODE=4'b0100;
typedef struct packed {logic [15:0] group_c;} cfg_t;
cfg_t i_c;
logic [15:0] i_ch0_q,accepted_channel;
logic [p_tile_count_w-1:0] i_cols_q,prepared_columns;
wire [31:0] i_ch0={16'b0,i_ch0_q};
wire i_cfg_valid=i_event==1;
wire i_cfg_ready=1'b1;
wire o_tile_commit=i_event[1];
wire channel_descriptor_valid=i_valid;
wire o_incoming_next_position_fast=(i_event==3) && i_window_select;
wire [15:0] o_window_next_ch=i_window_channel;
logic [1:0] phase;
wire [3:0] i_state={1'b0,phase==2,2'b0};
logic i_row_base_valid;
wire i_coordinate_address_valid=i_row_base_valid;
logic incoming_group_fits,incoming_group_fits_reference;
always_comb begin
  accepted_channel=i_ch0_q;
  if(o_incoming_next_position_fast)accepted_channel=o_window_next_ch;
end
always_ff @(posedge i_clk or negedge i_rst_n)begin
  if(!i_rst_n)begin
    i_c<='0;i_ch0_q<=0;i_cols_q<=p_tile_count_w'(p_size);
    i_row_base_valid<=0;phase<=0;
  end else if(i_cfg_valid&&i_cfg_ready)begin
    i_c.group_c<=i_group;i_row_base_valid<=0;phase<=0;
  end else if(o_tile_commit)begin
    if(!channel_descriptor_valid)begin end
    else begin
      i_cols_q<=prepared_columns;
      i_row_base_valid<=0;
      if(i_event==3)begin
        i_ch0_q<=accepted_channel;i_row_base_valid<=1;phase<=0;
      end else phase<=1;
    end
  end else case(phase)
    1:begin i_ch0_q<=i_channel;phase<=2;end
    2:phase<=3;
    3:begin i_row_base_valid<=1;phase<=0;end
    default:;
  endcase
end
""" + columns.group(0) + "\n" + logic + """
wire mathematical_fit=32'(i_cols_q)<=32'(i_c.group_c)-i_ch0;
`ifdef SYNTHESIS
assign equivalent=!i_rst_n ||
  (incoming_group_fits_reference==mathematical_fit &&
   (!i_row_base_valid || incoming_group_fits==mathematical_fit));
`else
assign equivalent=!i_rst_n || !i_row_base_valid ||
  incoming_group_fits===incoming_group_fits_reference;
`endif
endmodule
"""


BENCH = """module tb #(parameter int p_size=16);
logic i_clk=0,i_rst_n=0;
logic [1:0] i_event;
logic i_valid,i_window_select;
logic [15:0] i_group,i_channel,i_window_channel;
logic [$clog2(p_size+1)-1:0] i_tile_cols;
wire equivalent;
integer checks=0;
comparison #(.p_size(p_size)) dut(.*);
task automatic tick;
  #1;i_clk=1;#1;i_clk=0;
  if(equivalent!==1'b1)$fatal(1,"Saved group range mismatch size=%0d check=%0d",p_size,checks);
  checks++;
endtask
task automatic run_case;
  i_rst_n=0;i_event=0;tick();i_rst_n=1;i_event=1;tick();
  i_event=2;tick();i_event=0;tick();tick();tick();
  i_event=3;tick();tick();i_event=0;tick();
endtask
initial begin
  i_group=0;i_channel=0;i_window_channel=0;i_tile_cols=0;
  i_valid=1;i_window_select=0;run_case();
  for(int trial=0;trial<16;trial++)begin
    i_group=16'($urandom());i_channel=16'($urandom());
    i_window_channel=16'($urandom());i_tile_cols=$bits(i_tile_cols)'($urandom());
    i_valid=1;i_window_select=1;run_case();
    for(int field=0;field<5;field++)begin
      for(int index=0;index<16;index++)begin
        for(int unknown=0;unknown<2;unknown++)begin
          i_group=16'($urandom());i_channel=16'($urandom());
          i_window_channel=16'($urandom());i_tile_cols=$bits(i_tile_cols)'($urandom());
          i_valid=1;i_window_select=1;
          case(field)
            0:i_group[index]=unknown?1'bz:1'bx;
            1:i_channel[index]=unknown?1'bz:1'bx;
            2:i_window_channel[index]=unknown?1'bz:1'bx;
            3:i_tile_cols[index%$bits(i_tile_cols)]=unknown?1'bz:1'bx;
            4:i_window_select=unknown?1'bz:1'bx;
          endcase
          run_case();
        end
      end
    end
  end
  i_rst_n=0;tick();i_rst_n=1;
  for(int trial=0;trial<32768;trial++)begin
    i_event=2'($urandom());i_valid=1'($urandom());i_window_select=1'($urandom());
    i_group=16'($urandom());i_channel=16'($urandom());
    i_window_channel=16'($urandom());i_tile_cols=$bits(i_tile_cols)'($urandom());tick();
  end
  $display("SAVED_GROUP_RANGE_FOUR_STATE_PASS size=%0d checks=%0d",p_size,checks);$finish;
end
endmodule
"""


def run(command: list[str], log: Path, timeout: int) -> None:
    with log.open("w") as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=timeout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [root / name for name in SOURCES]
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest()
              for name, path in zip(SOURCES, sources)}
    model_file = out / "model.sv"
    model_file.write_text(model(sources[1].read_text()))
    bench = out / "bench.sv"
    bench.write_text(BENCH)
    helper = out / "add_equal.sv"
    helper.write_text(sources[0].read_text().replace("parameter int unsigned", "parameter integer"))
    worker = [sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker"]
    report = {"passed": False, "sources_sha256": hashes, "saved_state_bits": 1,
              "proof_depth": 10, "reset_at_step": 1, "value_assumptions": [], "cases": []}
    for size in (4, 16, 32, 256, 32768):
        script = out / f"size{size}.ys"
        script.write_text(f"read_slang --top comparison -Gp_size={size} -D SYNTHESIS=1 " +
                          shlex.join(map(str, (sources[0], model_file))) + "\n" +
                          "prep -top comparison -flatten\nsetattr -unset keep\nasync2sync\nopt\ncheck -assert\n" +
                          "sat -seq 10 -set-def-inputs -set-at 1 i_rst_n 0 -prove equivalent 1 -verify\n")
        log = script.with_suffix(".log")
        run(worker + [str(script)], log, 180)
        binary = out / f"size{size}.vvp"
        run([shutil.which("iverilog") or "iverilog", "-g2012", "-s", "tb",
             f"-Ptb.p_size={size}", "-o", str(binary), str(helper), str(model_file), str(bench)],
            out / f"size{size}.build.log", 60)
        run([shutil.which("vvp") or "vvp", str(binary)], out / f"size{size}.run.log", 120)
        output = (out / f"size{size}.run.log").read_text().strip()
        if "SAVED_GROUP_RANGE_FOUR_STATE_PASS" not in output:
            raise AssertionError(output)
        report["cases"].append({"size": size, "passed": True, "four_state": output,
                                "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()})
        print(output, flush=True)
    report["sources_unchanged"] = hashes == {
        name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in zip(SOURCES, sources)}
    if not report["sources_unchanged"]:
        raise RuntimeError("Saved group range sources changed during validation")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
