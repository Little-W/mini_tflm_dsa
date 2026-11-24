#!/usr/bin/env python3
"""验证配置准备阶段保存的模坐标区间和运行阶段的范围选择。"""
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
SOURCES = (
    "rtl/common/parallel_prefix_add.sv",
    "rtl/common/add_equal.sv",
    "rtl/npu/conv/conv_coordinate_step.sv",
    "rtl/npu/conv/conv_coordinate_range.sv",
    "rtl/npu/conv/conv_im2col_geometry.sv",
    "rtl/npu/conv/conv_im2col_descriptor.sv",
    "rtl/common/parallel_unsigned_compare.sv",
)


def range_model(width: int) -> str:
    return f"""module comparison(input logic [{width-1}:0] i_base,i_delta,
input logic [15:0] i_limit,output logic equivalent);
wire [{width-1}:0] lower={width}'(0)-i_delta;
wire [{width-1}:0] upper={width}'(i_limit)-i_delta;
wire [{width-1}:0] coordinate=i_base+i_delta;
wire block_cross=(|i_delta[15:0]) && i_delta[15:0]<=i_limit;
wire valid;
conv_coordinate_range #(.p_width({width})) dut(
  .i_base,.i_lower(lower),.i_upper(upper),.i_block_cross(block_cross),.o_valid(valid));
assign equivalent=valid==(coordinate<{width}'(i_limit));
endmodule
"""


def prepared_model(source: str, descriptor: str) -> str:
    first = source.index("  assign bound_a[0] = i_row_base_ix;\n")
    last = source.index("  // 数据字匹配", first)
    body = source[first:last]
    first = descriptor.index("  if (!p_register_descriptor) begin : g_direct_candidate_geometry\n")
    last = descriptor.index("  if (!p_register_descriptor) begin : g_direct_kernel_end\n", first)
    candidates = descriptor[first:last]
    first = descriptor.index("  assign window_forward_padding_reference = ")
    last = descriptor.index("  assign incoming_skip_ix = ", first)
    saved_padding = descriptor[first:last]
    return """module comparison #(parameter int p_check_group=-1)(
input logic i_clk,i_start,i_window_write,input logic [196:0] configuration,
input logic [141:0] runtime_data,output logic equivalent);
localparam int p_coord_w=35;
localparam bit p_register_descriptor=0;
typedef struct packed {
  logic [15:0] stride_w,stride_h,dilation_w,dilation_h,input_w,input_h;
} cfg_t;
cfg_t i_c;
logic signed [32:0] i_row_wrap_dx,i_tap_wrap_dx;
logic signed [34:0] o_tap_pair_dx;
logic [1:0] i_address_step_phase=0;
logic prepared=0,window_prepared=0;
logic signed [34:0] i_row_base_ix,i_row_base_iy,i_ix,i_iy;
logic o_row_wrap,o_tap_wrap;
logic [34:0] bound_a[7],bound_b[7],o_bound_sum[7];
logic [15:0] bound_limit[7];
logic [6:0] bound_valid_reference,o_bound_valid;
logic [2:0] o_skip_bound_valid,o_window_padding;
assign {i_row_base_ix,i_row_base_iy,i_ix,i_iy,o_row_wrap,o_tap_wrap}=runtime_data;
always_ff @(posedge i_clk) begin
  if(i_start)begin
    {i_c,i_row_wrap_dx,i_tap_wrap_dx,o_tap_pair_dx}<=configuration;
    i_address_step_phase<=2;prepared<=0;window_prepared<=0;
  end else begin
    if(prepared)window_prepared<=1;
    case(i_address_step_phase)
      2: i_address_step_phase<=1;
      1: i_address_step_phase<=3;
      3: begin i_address_step_phase<=0;prepared<=1;end
      default: ;
    endcase
  end
end
""" + body + """
logic [6:0] reference_valid;
logic [34:0] reference_sum[7];
for(genvar axis=0;axis<7;axis++)begin:g_reference
  assign reference_sum[axis]=bound_a[axis]+bound_b[axis];
  assign reference_valid[axis]=reference_sum[axis]<35'(bound_limit[axis]);
end
wire [34:0] pair_sum=i_row_base_ix+o_tap_pair_dx;
wire [34:0] double_sum=i_row_base_ix+(35'(i_c.dilation_w)<<1);
wire [2:0] reference_skip={i_row_base_iy<35'(i_c.input_h),
  double_sum<35'(i_c.input_w),pair_sum<35'(i_c.input_w)};
wire [34:0] window_forward_sum=reference_sum[0]+35'(i_c.dilation_w);
wire [34:0] window_backward_sum=reference_sum[0]-35'(i_c.dilation_w);
wire [34:0] window_previous_sum=reference_sum[1]-35'(i_c.dilation_h);
wire [2:0] reference_window={
  !(window_forward_sum<35'(i_c.input_w)) || !(window_previous_sum<35'(i_c.input_h)),
  !(window_backward_sum<35'(i_c.input_w)) || !reference_valid[1],
  !(window_forward_sum<35'(i_c.input_w)) || !reference_valid[1]};
wire i_rst_n=1'b1;
wire window_prepare_write=i_window_write && window_prepared && !i_start;
logic window_next_valid=0;
logic [2:0] saved_window_reference;
logic signed [34:0] window_next_ix,window_next_iy;
logic window_forward_padding,window_backward_padding,window_previous_padding;
logic window_forward_padding_reference,window_backward_padding_reference,window_previous_padding_reference;
wire [2:0] i_window_padding=o_window_padding;
wire [6:0] i_bound_valid=o_bound_valid;
wire [2:0] i_skip_bound_valid=o_skip_bound_valid;
wire signed [34:0] i_tap_pair_dx=o_tap_pair_dx;
logic [6:0][34:0] candidate_coordinate_sum;
logic [6:0] candidate_coordinate_valid;
always_ff @(posedge i_clk)begin
  if(i_start)window_next_valid<=0;
  else if(window_prepare_write)window_next_valid<=1;
  if(window_prepare_write)begin
    saved_window_reference<=i_window_padding;
    window_next_ix<=o_bound_sum[0];window_next_iy<=o_bound_sum[1];
  end
end
""" + candidates + saved_padding + """
wire [2:0] actual_padding={window_previous_padding,window_backward_padding,window_forward_padding};
wire [2:0] reference_padding={window_previous_padding_reference,
  window_backward_padding_reference,window_forward_padding_reference};
if(p_check_group<0)begin:g_four_state
  assign equivalent=(!prepared || o_bound_valid===reference_valid) &&
      (!window_next_valid || actual_padding===reference_padding);
end else if(p_check_group<7)begin:g_axis
  assign equivalent=!prepared || {o_bound_sum[p_check_group],o_bound_valid[p_check_group]}==
      {reference_sum[p_check_group],reference_valid[p_check_group]};
end else if(p_check_group<10)begin:g_skip
  assign equivalent=!prepared || o_skip_bound_valid[p_check_group-7]==reference_skip[p_check_group-7];
end else if(p_check_group<16)begin:g_window_endpoint
  localparam int step=p_check_group-10;
  wire [34:0] base_delta=step==4 ? 35'd0 : step<4 ?
    (step%2==0 ? 35'(i_c.stride_w) : 35'(i_row_wrap_dx)) : 35'(i_c.stride_h);
  wire [34:0] delta=base_delta+(step<2 ? 35'(i_c.dilation_w) :
      step<4 ? -35'(i_c.dilation_w) : -35'(i_c.dilation_h));
  wire [15:0] limit_value=step<4 ? i_c.input_w : i_c.input_h;
  wire [34:0] expected_lower=35'd0-delta;
  wire [34:0] expected_upper=35'(limit_value)-delta;
  wire expected_cross=(|delta[15:0]) && delta[15:0]<=limit_value;
  assign equivalent=!window_prepared ||
    {g_prepared_bounds.window_lower_q[step],g_prepared_bounds.window_upper_q[step],
     g_prepared_bounds.window_cross_q[step]}=={expected_lower,expected_upper,expected_cross};
end else begin:g_saved_window
  assign equivalent=!window_next_valid || actual_padding==saved_window_reference;
end
endmodule
"""


def window_candidate_model(descriptor: str) -> str:
    first = descriptor.index("  if (!p_register_descriptor) begin : g_direct_candidate_geometry\n")
    last = descriptor.index("  if (!p_register_descriptor) begin : g_direct_kernel_end\n", first)
    body = descriptor[first:last]
    first = descriptor.index("  assign window_forward_padding_reference = ")
    last = descriptor.index("  if (!p_register_descriptor) begin : g_saved_window_padding\n", first)
    flags = descriptor[first:last]
    return """module comparison #(parameter int p_check_group=0)(
input logic [34:0] window_next_ix,window_next_iy,
input logic [63:0] configuration,output logic equivalent);
localparam int p_coord_w=35;
localparam bit p_register_descriptor=0;
typedef struct packed {logic [15:0] dilation_w,dilation_h,input_w,input_h;} cfg_t;
cfg_t i_c;
assign i_c=configuration;
wire [34:0] i_row_base_ix=0,i_row_base_iy=0,i_tap_pair_dx=0;
wire [6:0] i_bound_valid=0;
wire [2:0] i_skip_bound_valid=0;
logic [6:0][34:0] candidate_coordinate_sum;
logic [6:0] candidate_coordinate_valid;
logic window_forward_padding_reference,window_backward_padding_reference,window_previous_padding_reference;
""" + body + flags + """
wire [34:0] forward_coordinate=window_next_ix+35'(i_c.dilation_w);
wire [34:0] backward_coordinate=window_next_ix-35'(i_c.dilation_w);
wire [34:0] previous_coordinate=window_next_iy-35'(i_c.dilation_h);
wire [2:0] expected={
  forward_coordinate>=35'(i_c.input_w) || previous_coordinate>=35'(i_c.input_h),
  backward_coordinate>=35'(i_c.input_w) || window_next_iy>=35'(i_c.input_h),
  forward_coordinate>=35'(i_c.input_w) || window_next_iy>=35'(i_c.input_h)};
wire [2:0] actual={window_previous_padding_reference,
  window_backward_padding_reference,window_forward_padding_reference};
assign equivalent=actual[p_check_group]==expected[p_check_group];
endmodule
"""


def window_selection_model(source: str) -> str:
    first = source.index("    assign o_window_padding[0] = ")
    last = source.index("    for (genvar axis", first)
    body = source[first:last]
    return """module comparison(input logic o_row_wrap,input logic [5:0] window_valid,
input logic base_y_valid,next_y_valid,output logic equivalent);
logic [6:0] o_bound_valid;
logic [2:0] o_window_padding;
assign o_bound_valid={5'b0,o_row_wrap?next_y_valid:base_y_valid,1'b0};
""" + body + """
logic [2:0][1:0] selected_axes;
always_comb begin
  if(o_row_wrap)begin
    selected_axes[0]={window_valid[1],next_y_valid};
    selected_axes[1]={window_valid[3],next_y_valid};
    selected_axes[2]={window_valid[1],window_valid[5]};
  end else begin
    selected_axes[0]={window_valid[0],base_y_valid};
    selected_axes[1]={window_valid[2],base_y_valid};
    selected_axes[2]={window_valid[0],window_valid[4]};
  end
end
assign equivalent=o_window_padding==
  {!(&selected_axes[2]),!(&selected_axes[1]),!(&selected_axes[0])};
endmodule
"""


def window_composition() -> dict:
    # 六种步长的坐标表达式逐项比较系数，模加法的结合关系适用于全部三十五位输入。
    def add(left, right):
        return tuple(a + b for a, b in zip(left, right))

    def scale(value, factor):
        return tuple(a * factor for a in value)

    zero = (0,) * 7
    x, y, stride_w, row_wrap, stride_h, dilation_w, dilation_h = (
        tuple(int(index == variable) for index in range(7)) for variable in range(7))
    bases = (x, x, x, x, y, y)
    row_steps = (stride_w, row_wrap, stride_w, row_wrap, zero, stride_h)
    tap_steps = (dilation_w, dilation_w, scale(dilation_w, -1),
                 scale(dilation_w, -1), scale(dilation_h, -1), scale(dilation_h, -1))
    differences = []
    for base, row_step, tap_step in zip(bases, row_steps, tap_steps):
        original = add(add(base, row_step), tap_step)
        prepared = add(base, add(row_step, tap_step))
        difference = add(original, scale(prepared, -1))
        assert difference == zero
        differences.append(difference)
    return {"variables": ["x", "y", "stride_w", "row_wrap", "stride_h", "dilation_w", "dilation_h"],
            "coordinate_modulus": 1 << 35, "coefficient_differences": differences,
            "stages": ["configuration endpoints", "window endpoints", "modular range comparison",
                       "padding selection", "shared window capture"]}


def simulation_model(source: str) -> str:
    # 四态仿真模型显式展开常量循环，各过程通过独立局部变量驱动输出位。
    source = source.replace("logic [5:0] window_cross_q, window_valid;",
                            "logic [5:0] window_cross_q; wire [5:0] window_valid;")
    source = source.replace("logic [6:0] candidate_coordinate_valid;",
                            "wire [6:0] candidate_coordinate_valid;")
    first = source.index("      always_comb begin\n        case (^{candidate_coordinate_i_a[axis]")
    last = source.index("`endif", first)
    body = source[first:last].replace("candidate_coordinate_valid[axis]", "current_valid")
    source = source[:first] + ("      logic current_valid;\n"
                               "      assign candidate_coordinate_valid[axis]=current_valid;\n") + body + source[last:]
    first = source.index("    for (genvar step = 0; step < 6; step++) begin : g_window_range\n")
    last = source.index("    assign o_window_padding[0]", first)
    body = source[first:last].split("\n", 1)[1]
    if not body.endswith("    end\n"):
        raise ValueError("Window range generate block is unavailable")
    body = body[:-len("    end\n")]
    expanded = "".join(f"    if (1) begin : g_window_range_{index}\n" +
                       re.sub(r"\bstep\b", str(index), body) + "    end\n" for index in range(6))
    return source[:first] + expanded + source[last:]


BENCH = """module tb;
logic i_clk=0,i_start=0,i_window_write=0;
logic [196:0] configuration,known_configuration;
logic [141:0] runtime_data,known_runtime;
wire equivalent;
integer checks=0;
comparison dut(.*);
task automatic tick;
  #1;i_clk=1;#1;i_clk=0;
  if(equivalent!==1'b1)$fatal(1,"Prepared coordinate range mismatch check=%0d",checks);
  checks++;
endtask
task automatic run_case;
  i_window_write=0;i_start=1;tick();i_start=0;tick();tick();tick();tick();
  i_window_write=1;tick();i_window_write=0;tick();
endtask
initial begin
  configuration='0;runtime_data='0;run_case();
  configuration='1;runtime_data='1;run_case();
  for(int trial=0;trial<4;trial++)begin
    for(int bit_index=0;bit_index<197;bit_index++)
      known_configuration[bit_index]=1'($urandom());
    for(int bit_index=0;bit_index<142;bit_index++)
      known_runtime[bit_index]=1'($urandom());
    configuration=known_configuration;runtime_data=known_runtime;run_case();
    for(int bit_index=0;bit_index<339;bit_index++)begin
      {configuration,runtime_data}={known_configuration,known_runtime};
      if(bit_index<142)runtime_data[bit_index]=1'bx;
      else configuration[bit_index-142]=1'bx;
      run_case();
      {configuration,runtime_data}={known_configuration,known_runtime};
      if(bit_index<142)runtime_data[bit_index]=1'bz;
      else configuration[bit_index-142]=1'bz;
      run_case();
    end
    configuration='x;runtime_data='x;run_case();
    configuration='z;runtime_data='z;run_case();
  end
  $display("COORDINATE_RANGES_FOUR_STATE_PASS checks=%0d",checks);$finish;
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
    worker = [sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker"]
    report = {"passed": False, "sources_sha256": hashes, "coordinate_width": 35,
              "saved_range_bits": 14 * (2 * 35 + 1), "saved_window_padding_bits": 3,
              "preparation_phase": 3, "window_endpoint_phase": 0,
              "added_protocol_cycles": 0, "range_cases": [], "prepared_cases": []}
    for width in (17, 18, 32, 35, 64):
        model = out / f"range_w{width}.sv"
        model.write_text(range_model(width))
        script = out / f"range_w{width}.ys"
        script.write_text("read_slang --top comparison -D SYNTHESIS=1 " +
                          shlex.join(map(str, (sources[6], sources[3], model))) + "\n" +
                          "prep -top comparison -flatten\ncheck -assert\n" +
                          "sat -set-def-inputs -prove equivalent 1 -verify\n")
        log = script.with_suffix(".log")
        run(worker + [str(script)], log, 180)
        report["range_cases"].append({"coordinate_width": width, "passed": True,
                                      "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()})
        print(f"COORDINATE_RANGE_PASS width={width}", flush=True)
    prepared = out / "prepared.sv"
    prepared.write_text(prepared_model(sources[4].read_text(), sources[5].read_text()))
    for group in range(17):
        script = out / f"prepared_g{group}.ys"
        script.write_text(f"read_slang --top comparison -Gp_check_group={group} -D SYNTHESIS=1 " +
                          shlex.join(map(str, [*sources[:4], sources[6], prepared])) + "\n" +
                          "prep -top comparison -flatten\nsetattr -unset keep\nopt\ncheck -assert\n" +
                          f"sat -seq {6 if group < 16 else 8} -set-def-inputs -prove equivalent 1 -verify\n")
        log = script.with_suffix(".log")
        run(worker + [str(script)], log, 180)
        report["prepared_cases"].append({"group": group, "passed": True,
                                         "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()})
        print(f"PREPARED_COORDINATE_RANGE_PASS group={group}", flush=True)
    report["window_cases"] = []
    for group in range(4):
        model = out / f"window_g{group}.sv"
        model.write_text(window_candidate_model(sources[5].read_text()) if group < 3 else
                         window_selection_model(sources[4].read_text()))
        script = model.with_suffix(".ys")
        parameter = f"-Gp_check_group={group} " if group < 3 else ""
        script.write_text("read_slang --top comparison " + parameter + "-D SYNTHESIS=1 " +
                          shlex.join(map(str, [*sources[:4], sources[6], model])) + "\n" +
                          "prep -top comparison -flatten\nsetattr -unset keep\nopt\ncheck -assert\n" +
                          "sat -set-def-inputs -prove equivalent 1 -verify\n")
        log = script.with_suffix(".log")
        run(worker + [str(script)], log, 180)
        report["window_cases"].append({"group": group, "passed": True,
                                       "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()})
        print(f"WINDOW_COORDINATE_PASS group={group}", flush=True)
    report["composition"] = window_composition()
    simulation_sources = []
    for source in [*sources[:4], sources[6]]:
        local = out / source.name
        local.write_text(source.read_text().replace("parameter int unsigned", "parameter integer"))
        simulation_sources.append(local)
    bench = out / "bench.sv"
    bench.write_text(BENCH)
    simulation = out / "simulation.sv"
    simulation.write_text(simulation_model(prepared.read_text()))
    binary = out / "run.vvp"
    run([shutil.which("iverilog") or "iverilog", "-g2012", "-s", "tb", "-o", str(binary),
         *map(str, simulation_sources), str(simulation), str(bench)], out / "build.log", 60)
    run([shutil.which("vvp") or "vvp", str(binary)], out / "run.log", 600)
    output = (out / "run.log").read_text().strip()
    if "COORDINATE_RANGES_FOUR_STATE_PASS" not in output:
        raise AssertionError(output)
    report["four_state"] = output
    report["sources_unchanged"] = hashes == {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in zip(SOURCES, sources)}
    if not report["sources_unchanged"]:
        raise RuntimeError("Coordinate range sources changed during validation")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(output, flush=True)


if __name__ == "__main__":
    main()
