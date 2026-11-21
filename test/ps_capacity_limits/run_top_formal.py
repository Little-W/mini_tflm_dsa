#!/usr/bin/env python3
"""直接提取 NPU 顶层容量表达式，证明实例连接与全部容量标志一致。"""
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
PORTS = """
    input logic [31:0] cfg_w_reuse_eff_s2, cfg_ia_reuse_eff_s2,
    input logic [31:0] cfg_stream_k_s2, cfg_stream_m_s2, cfg_n_s2,
    input logic [31:0] shared_ia_banks_q, ps_control_q,
    input logic cfg_compact_s2,
    input logic [p_rows_width-1:0] i_ps_rows,
    input logic [p_frames_width-1:0] i_ps_frames,
    input logic i_raw_fits_q, i_long_fits_q
"""
PARAMETERS = """
    parameter int p_max_rows = 512,
    parameter int p_rows_width = $clog2(p_max_rows+1),
    parameter int p_frames_width = 5,
    parameter int p_total_banks = 7,
    parameter int p_bank_bytes = 8192
"""


def section(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


def abstract_capture(text, target, expression):
    """组合公式比较直接使用寄存器的输入，时序关系由配置流水测试验证。"""
    if f"logic [" not in text or f" {target};" not in text:
        return text
    capture = (r"        always_ff @\(posedge clk\) begin\n"
               r"            if \(cfg_stage2_valid && cfg_capacity_phase==[0-7]\)\n"
               rf"                {target} <= {expression};\n        end\n")
    text, count = re.subn(capture, "", text)
    if count != 1:
        raise ValueError(f"Expected one configuration capture for {target}")
    text, count = re.subn(rf"logic (\[[^\n]+\]) {target};",
                         rf"wire \1 {target} = {expression};", text)
    if count != 1:
        raise ValueError(f"Expected one configuration register {target}")
    return text


def capacity_module(text, name, sequential=False):
    active_parts = []
    for field in ('active_ia_cache_blocks', 'active_ps_pool_bytes', 'active_ps_bank_count',
                  'active_ps_bank_depth', 'shared_allocation_invalid'):
        match = re.search(r'    wire (?:\[[^\n;]*?\] )?' + field + r'\s*=.*?;',
                          text, flags=re.S)
        if match is None:
            raise ValueError('Expected allocation expression: ' + field)
        active_parts.append(match[0])
    active = '\n'.join(active_parts) + '\n'
    if 'active_ps_bank_count_q' in active:
        # 同拍保存的派生状态使用其已证明的银行状态关系表示。
        # 完整配置接收与复位关系由 test/ps_allocation_registration 验证。
        count = re.search(r'    wire \[31:0\] requested_ps_bank_count =.*?;',
                          text, flags=re.S)[0]
        invalid = re.search(r'    wire requested_allocation_invalid =.*?;',
                            text, flags=re.S)[0]
        count = count.replace('requested_ps_bank_count', 'active_ps_bank_count_q')
        invalid = invalid.replace('requested_allocation_invalid', 'shared_allocation_invalid_q')
        observers = (count + '\n' + invalid + '\n').replace(
            'requested_shared_ia_banks', 'shared_ia_banks_q')
        active = observers + active
    if "IA_SHAPE_REQUIRED_WIDTH" in text:
        shape_start = "        localparam int unsigned IA_SHAPE_REQUIRED_WIDTH"
    elif "ia_reuse_shape_i_value" in text:
        shape_start = "        logic [REG_WIDTH-1:0] ia_reuse_shape_i_value;"
    else:
        shape_start = "        wire legacy_window_shape_s2"
    shape = shape_start + section(text, shape_start, "        wire ctrl_calc_start")
    if not sequential and 'logic use_frame_commands_s2;' in shape:
        # 组合公式检查直接使用捕获值，实际相位关系由配置流水测试验证。
        capture = (r"        always_ff @\(posedge clk or negedge core_rst_n\) begin\n"
                   r"            if \(!core_rst_n\)\n"
                   r"                use_frame_commands_s2 <= 1'b0;\n"
                   r"            else if \(cfg_stage2_valid && cfg_capacity_phase == 3'd2\)\n"
                   r"                use_frame_commands_s2 <= use_frame_commands_calc;\n"
                   r"        end\n")
        shape, count = re.subn(capture, "", shape)
        if count != 1:
            raise ValueError("Expected one frame-mode configuration capture")
        shape = shape.replace('logic use_frame_commands_s2;',
                              'wire use_frame_commands_s2 = use_frame_commands_calc;')
    if not sequential and 'frame_slice_tiles_calc' in shape:
        shape = abstract_capture(shape, 'frame_slice_tiles_s2', 'frame_slice_tiles_calc')
    bounds = "        wire [IA_REUSE_W-1:0] ext_r_small" + section(
        text, "        wire [IA_REUSE_W-1:0] ext_r_small", "`ifdef GEMPACT_PS_COMPRESS")
    body = "        localparam int CAP_ROWS_W" + section(text,
        "        localparam int CAP_ROWS_W", "\n`else\n        localparam bit PS_REQUIRE_RAW_CAPACITY")
    if not sequential:
        # 同一阶段寄存器作为任意共享状态输入，比较其后全部组合表达式。
        body, count = re.subn(r"        always_ff @\(posedge clk\) begin\n"
                              r"            if \(cfg_stage2_valid && cfg_capacity_phase==[01]\) begin\n"
                              r".*?            end\n        end\n", "", body, flags=re.DOTALL)
        if count != 2:
            raise ValueError("Expected two existing capacity register groups")
        body = body.replace("logic [CAP_ROWS_W-1:0] ps_rows_bounded;",
                            "wire [CAP_ROWS_W-1:0] ps_rows_bounded = i_ps_rows;")
        body = body.replace("logic [CAP_FRAMES_W-1:0] ps_frames_bounded;",
                            "wire [CAP_FRAMES_W-1:0] ps_frames_bounded = i_ps_frames;")
        body = body.replace("logic ps_raw_capacity_fits_q, ps_long_capacity_fits_q;",
                            "wire ps_raw_capacity_fits_q = i_raw_fits_q;\n"
                            "        wire ps_long_capacity_fits_q = i_long_fits_q;")
        if 'ps_admission_rows_calc' in body:
            body = abstract_capture(body, 'ps_admission_rows', 'ps_admission_rows_calc')
    stage_ports = """
    input logic clk, core_rst_n, cfg_stage2_valid, ctrl_sa_ready, frame_scheduler_ready,
    output logic [p_rows_width-1:0] o_rows_state,
    output logic [p_frames_width-1:0] o_frames_state,
    output logic o_raw_state, o_long_state, o_invalid_state, o_fire,
    output logic [2:0] o_phase,
""" if sequential else ""
    header = f"module {name} #(\n{PARAMETERS}) (\n{PORTS},\n" + """
    output logic o_raw_calc, o_long_calc, o_invalid_calc,
    output logic [63:0] o_admission_rows,
    output logic [31:0] o_slice_tiles,
""" + stage_ports + """
    output logic o_bank_in_range
);
    localparam int SIZE=16, SIZE_SHIFT=4, REG_WIDTH=32;
    localparam int IA_REUSE_NUM_MAX=p_max_rows/16;
    localparam int W_REUSE_NUM_MAX=1 << (p_frames_width-1);
    localparam int IA_REUSE_W=$clog2(IA_REUSE_NUM_MAX)+1;
    localparam int W_REUSE_W=p_frames_width;
    localparam int IA_CACHE_BLOCKS=4;
    localparam int SHARED_PHYSICAL_BANKS=p_total_banks;
    localparam int SHARED_BANK_BYTES=p_bank_bytes;
    localparam int SHARED_TOTAL_BYTES=p_total_banks*p_bank_bytes;
    localparam int SHARED_PS_DIRECTORY_ROWS=1024;
    localparam bit SHARED_RAM_ENABLED=1'b1, FRAME_EXEC_ENABLED=1'b1;
    wire ps_raw_capacity_fits, ps_long_capacity_fits;
    wire run_conv=1'b0, cfg_use16_s2=1'b0;
    wire signed [31:0] lhs_zp='0, rhs_zp='0;
    typedef struct packed {logic input_s16; logic signed [15:0] input_offset;} conv_fields_t;
    wire conv_fields_t conv_cfg_q='0;
"""
    stages = ""
    controls = ""
    if sequential:
        phase = "        assign cfg_stage2_fire =" + section(
            text, "        assign cfg_stage2_fire =",
            "        always_ff @(posedge clk) begin\n            if (cfg_start_event)")
        invalid = "        logic ps_capacity_config_invalid;" + section(
            text, "        logic ps_capacity_config_invalid;",
            "        always_ff @(posedge clk or negedge core_rst_n)")
        controls = """
    logic [2:0] cfg_capacity_phase;
    wire cfg_stage2_fire;
""" + phase
        stages = invalid + """
    assign o_rows_state=ps_rows_bounded;
    assign o_frames_state=ps_frames_bounded;
    assign o_raw_state=ps_raw_capacity_fits_q;
    assign o_long_state=ps_long_capacity_fits_q;
    assign o_invalid_state=ps_capacity_config_invalid;
    assign o_fire=cfg_stage2_fire;
    assign o_phase=cfg_capacity_phase;
"""
    return header + controls + active + shape + bounds + body + stages + """
    assign o_raw_calc=ps_raw_capacity_fits_calc;
    assign o_long_calc=ps_long_capacity_fits_calc;
    assign o_invalid_calc=ps_capacity_config_invalid_calc;
    assign o_admission_rows=ps_admission_rows;
    assign o_slice_tiles=frame_slice_tiles_s2;
    assign o_bank_in_range=(active_ps_bank_count<32'(SHARED_PHYSICAL_BANKS));
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-rev", default="8c707c1")
    parser.add_argument("--bank-counts", type=int, nargs="+", default=[6, 7, 8, 9])
    parser.add_argument("--bank-bytes", type=int, nargs="+", default=[2048, 8192])
    parser.add_argument("--max-rows", type=int, default=512)
    parser.add_argument("--frames-width", type=int, default=5)
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass("script " + shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    top_path = ROOT / "rtl/npu/top/npu_top.sv"
    sources = []
    for label in ("reference", "candidate"):
        source = read_rtl_source(args.reference_rev + ":rtl/npu/top/npu_top.sv", cwd=ROOT, text=True) if label == "reference" else top_path.read_text()
        path = out / (label + ".sv")
        path.write_text(capacity_module(source, "capacity_" + label))
        sources.append(path)
    formal = out / "formal.sv"
    instances = []
    for label in ("reference", "candidate"):
        instances += [f"    logic {label}_raw, {label}_long, {label}_invalid, {label}_bank_range;",
                      f"    logic [31:0] {label}_slice;",
                      f"    logic [63:0] {label}_rows;",
                      f"    capacity_{label} #(.p_max_rows(p_max_rows), .p_rows_width(p_rows_width),",
                      "        .p_frames_width(p_frames_width), .p_total_banks(p_total_banks),",
                      f"        .p_bank_bytes(p_bank_bytes)) u_{label} (.*,"]
        instances += [f"        .o_raw_calc({label}_raw), .o_long_calc({label}_long),",
                      f"        .o_invalid_calc({label}_invalid), .o_admission_rows({label}_rows),",
                      f"        .o_bank_in_range({label}_bank_range), .o_slice_tiles({label}_slice));"]
    formal.write_text(f"module capacity_top_formal #(\n{PARAMETERS}) (\n{PORTS});\n" +
                      "\n".join(instances) + """
    always_comb begin
        if (reference_bank_range) begin
            assert(reference_raw==candidate_raw);
            assert(reference_long==candidate_long);
        end
        assert(reference_invalid==candidate_invalid);
        assert(reference_rows==candidate_rows);
        assert(reference_slice==candidate_slice);
    end
endmodule
""")
    sources += [formal, ROOT / "rtl/npu/control/ps_capacity_limits.sv",
                ROOT / "rtl/common/onehot_check.sv",
                ROOT / "rtl/common/parallel_prefix_add.sv",
                ROOT / "rtl/common/unsigned_compare.sv"]
    summary = {"reference_rev": args.reference_rev,
               "method": "SAT of expressions extracted from both npu_top revisions with arbitrary shared register state",
               "source_sha256": {str(top_path.relative_to(ROOT)): hashlib.sha256(top_path.read_bytes()).hexdigest()},
               "generated_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
               "max_rows": args.max_rows, "frames_width": args.frames_width,
               "allocation_input_bits": 32, "properties_per_case": 5, "runs": []}
    for banks in args.bank_counts:
        for bank_bytes in args.bank_bytes:
            folder = out / f"banks{banks}_bytes{bank_bytes}"
            folder.mkdir(exist_ok=True)
            script = folder / "run.ys"
            script.write_text("read_slang --top capacity_top_formal -DGEMMORA_PS_POOL_BYTES=49152 " +
                              f"-Gp_total_banks={banks} -Gp_bank_bytes={bank_bytes} " +
                              f"-Gp_max_rows={args.max_rows} -Gp_frames_width={args.frames_width} " +
                              " ".join(shlex.quote(str(path)) for path in sources) +
                              "\nprep -top capacity_top_formal -flatten\nmemory_map\nopt_clean\n" +
                              "chformal -lower\nsat -prove-asserts -verify -show-inputs -show-outputs\n")
            with (folder / "formal.log").open("w") as stream:
                result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--out", str(out),
                                         "--worker", str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
            log = (folder / "formal.log").read_text()
            passed = result.returncode == 0 and "SAT proof finished - no model found: SUCCESS" in log
            record = {"total_banks": banks, "bank_bytes": bank_bytes, "passed": passed}
            summary["runs"].append(record)
            summary["passed"] = all(item["passed"] for item in summary["runs"])
            (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
            print(json.dumps(record), flush=True)
            if not passed:
                print(log[-12000:])
                raise SystemExit(1)


if __name__ == "__main__":
    main()
