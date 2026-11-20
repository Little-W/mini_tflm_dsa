#!/usr/bin/env python3
"""证明坐标递增和通道分段比较，以及配置终点寄存器的更新关系。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from position_decode_equivalence import normalize_position_source, POSITION_NOTE

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[3]
SOURCE = 'rtl/npu/conv/conv_im2col_frontend.sv'
START = '  // 递增比较并行处理符号、宽位溢出及低十六位边界。\n'
END = '  always_comb begin\n    col_remaining=cols_q-col_idx;'
DECLARATIONS = ('p_group_low_w', 'p_group_high_w', 'group_high_minus_one_q',
                'last_group_channel_q', 'group_lane_allowed', 'p_coord_max',
                'ix_step_below_limit', 'last_input_col_q', 'kernel_width_valid_q')
TERMINALS = ('last_input_col_q', 'group_high_minus_one_q', 'last_group_channel_q', 'kernel_width_valid_q')


def section(source):
    return source[source.index(START):source.index(END, source.index(START))]


def normalize_stream_source(source):
    source = normalize_position_source(source)
    if START not in source:
        return source
    result = source.replace(section(source), '')
    for name in DECLARATIONS:
        result = re.sub(r'^  (?:logic|localparam) [^\n;]*\b' + name + r'\b[^\n;]*;\n',
                        '', result, flags=re.M)
    for name in TERMINALS:
        result = re.sub(r'^\s*' + name + r'\s*<=\s*[^;]+;\n', '', result, flags=re.M)
    result = result.replace('ix_step_below_limit)', "ix+1<$signed(COORD_W'(c.input_w)))")
    result = result.replace('group_lane_allowed[lane] &&', "17'(lane)<group_remaining &&")
    return result.replace('kernel_width_valid_q', "c.kernel_w!=16'd0")


def assignment(source, name):
    match = re.search(r'\b' + name + r'\s*=\s*([^;]+);', source)
    if not match:
        raise ValueError('Missing expression for ' + name)
    return match.group(1)


def run_proof(out, rtl, top, sequential=False):
    source = out / (top + '.sv')
    source.write_text(rtl)
    script = out / (top + '.ys')
    script.write_text('read_slang --top ' + top + ' ' + shlex.quote(str(source)) + '\n' +
                     'prep -top ' + top + ' -flatten\n' +
                     ('async2sync\nopt\n' if sequential else '') +
                     'sat -verify ' +
                     ('-seq 2 -tempinduct -set-at 1 rst_n 0 ' if sequential else '') +
                     '-prove equivalent 1 -show-inputs -show-outputs\n')
    log = out / (top + '.log')
    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True)
    success = 'Induction step proven: SUCCESS!' if sequential else 'SAT proof finished - no model found: SUCCESS!'
    if success not in log.read_text():
        raise RuntimeError('Proof did not complete: ' + top)
    return {'passed': True, 'proof_source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'proof_log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default='05be5b8')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(args.reference_ref + ':' + SOURCE, cwd=ROOT, text=True)
    if normalize_stream_source(current) != reference:
        raise ValueError('Uncovered changes remain in the frontend source')
    terminal = {}
    reset_section = current[current.index('      pixel_bytes<=0;pf_step_base<=1;'):]
    reset_section, config_section = reset_section.split('    end else if (cfg_valid && cfg_ready) begin', 1)
    config_section = config_section[:config_section.index('\n    end\n  end')]
    for name in TERMINALS:
        values = re.findall(r'\b' + name + r'\s*<=\s*([^;]+);', current)
        if len(values) != 2 or name not in reset_section or name not in config_section:
            raise ValueError('Configuration register ownership changed: ' + name)
        terminal[name] = values
    if re.findall(r'(?<![\w.])c\s*<=\s*([^;]+);', current) != ["'0", 'cfg']:
        raise ValueError('Captured configuration ownership changed')

    def fields(text):
        return text.replace('cfg.input_w', 'cfg_input_w').replace('cfg.group_c', 'cfg_group_c').replace(
            'cfg.kernel_w', 'cfg_kernel_w').replace('c.input_w', 'input_w').replace(
            'c.group_c', 'group_c').replace('c.kernel_w', 'kernel_w')

    body = section(current)
    start = body.index('    logic high_before_end,')
    middle = body.index('    for (genvar lane = 0;', start)
    end = body.index('\n    end\n  end else begin : g_group_lane_range_wide', middle)
    inner = body[body.index('      logic [p_group_low_w:0] lane_last_low;', middle):end]
    terms = fields(body[start:middle] + inner).replace('group_lane_allowed[lane]', 'current_allowed')
    single = body[body.index('  if (LANES == 1) begin : g_single_group_lane'):]
    single = single[:single.index('  end else if (LANES == 2)')]
    if 'assign group_lane_allowed[0] = c.group_c != ch_q;' not in single:
        raise ValueError('Single-lane expression changed')
    dual = body[body.index('    logic group_has_channel;'):]
    dual = fields(dual[:dual.index('  end else if (LANES <= 32768)')])
    fallback = body[body.index('  end else begin : g_group_lane_range_wide'):]
    if "assign group_lane_allowed[lane] = 17'(lane) < group_remaining;" not in fallback:
        raise ValueError('Wide-lane fallback expression changed')
    coord = fields(assignment(current, 'ix_step_below_limit'))
    coord_max = re.search(r'localparam logic signed \[COORD_W-1:0\] p_coord_max = ([^;]+);', current).group(1)
    group_remaining = fields(assignment(current, 'group_remaining'))
    coordinate_reference = re.search(r"ix\+1<\$signed\(COORD_W'\(c\.input_w\)\)", reference).group(0)
    arithmetic = f'''module group_comparison #(parameter int LOW_W=1) (
  input logic [15:0] group_c, ch_q,
  input logic [LOW_W-1:0] lane,
  output logic equivalent
);
localparam int p_group_low_w=LOW_W, p_group_high_w=16-LOW_W;
logic [p_group_high_w-1:0] group_high_minus_one_q;
logic [16:0] group_remaining;
logic current_allowed;
assign group_high_minus_one_q = {fields(terminal['group_high_minus_one_q'][1]).replace('cfg_group_c', 'group_c')};
assign group_remaining = {group_remaining};
{terms}
assign equivalent = current_allowed == (17'(lane) < group_remaining);
endmodule

module stream_arithmetic_proof (
  input logic signed [34:0] ix,
  input logic [15:0] input_w, group_c, ch_q,
  input logic [14:0] lane,
  output logic equivalent
);
localparam int COORD_W=35;
localparam logic signed [COORD_W-1:0] p_coord_max = {coord_max};
logic [15:0] last_input_col_q, last_group_channel_q;
logic [16:0] group_remaining;
logic [1:0] group_lane_allowed;
logic current_coord, reference_coord;
logic [14:0] group_equivalent;
assign last_input_col_q = {fields(terminal['last_input_col_q'][1]).replace('cfg_input_w', 'input_w')};
assign last_group_channel_q = {fields(terminal['last_group_channel_q'][1]).replace('cfg_group_c', 'group_c')};
assign group_remaining = {group_remaining};
{dual}
assign current_coord = {coord};
assign reference_coord = {fields(coordinate_reference)};
for (genvar width=1; width<=15; width++) begin : g_width
  group_comparison #(.LOW_W(width)) u_group (
    .group_c(group_c), .ch_q(ch_q), .lane(lane[width-1:0]), .equivalent(group_equivalent[width-1])
  );
end
assign equivalent = (current_coord == reference_coord) && (&group_equivalent) &&
                    (group_lane_allowed[0] == (17'd0 < group_remaining)) &&
                    (group_lane_allowed[1] == (17'd1 < group_remaining));
endmodule
'''
    arithmetic_result = run_proof(out, arithmetic, 'stream_arithmetic_proof')
    state = f'''module stream_terminal_state #(parameter int LOW_W=1) (
  input logic clk, rst_n, cfg_fire,
  input logic [15:0] cfg_input_w, cfg_group_c, cfg_kernel_w,
  output logic equivalent
);
localparam int p_group_low_w=LOW_W, p_group_high_w=16-LOW_W;
logic [15:0] input_w, group_c, kernel_w, last_input_col_q, last_group_channel_q;
logic kernel_width_valid_q;
logic [p_group_high_w-1:0] group_high_minus_one_q;
always_ff @(posedge clk or negedge rst_n) begin
  if (!rst_n) begin
    input_w <= 16'd0;
    group_c <= 16'd0;
    kernel_w <= 16'd0;
    last_input_col_q <= {terminal['last_input_col_q'][0]};
    group_high_minus_one_q <= {terminal['group_high_minus_one_q'][0]};
    last_group_channel_q <= {terminal['last_group_channel_q'][0]};
    kernel_width_valid_q <= {terminal['kernel_width_valid_q'][0]};
  end else if (cfg_fire) begin
    input_w <= cfg_input_w;
    group_c <= cfg_group_c;
    kernel_w <= cfg_kernel_w;
    last_input_col_q <= {fields(terminal['last_input_col_q'][1])};
    group_high_minus_one_q <= {fields(terminal['group_high_minus_one_q'][1])};
    last_group_channel_q <= {fields(terminal['last_group_channel_q'][1])};
    kernel_width_valid_q <= {fields(terminal['kernel_width_valid_q'][1])};
  end
end
assign equivalent = last_input_col_q == input_w - 16'd1 &&
                    group_high_minus_one_q == group_c[15:p_group_low_w] - p_group_high_w'(1) &&
                    last_group_channel_q == group_c - 16'd1 &&
                    kernel_width_valid_q == (kernel_w != 16'd0);
endmodule

module stream_configuration_proof (
  input logic clk, rst_n, cfg_fire,
  input logic [15:0] cfg_input_w, cfg_group_c, cfg_kernel_w,
  output logic equivalent
);
logic [14:0] relations;
for (genvar width=1; width<=15; width++) begin : g_width
  stream_terminal_state #(.LOW_W(width)) u_state (
    .clk(clk), .rst_n(rst_n), .cfg_fire(cfg_fire),
    .cfg_input_w(cfg_input_w), .cfg_group_c(cfg_group_c), .cfg_kernel_w(cfg_kernel_w),
    .equivalent(relations[width-1])
  );
end
assign equivalent = &relations;
endmodule
'''
    state_result = run_proof(out, state, 'stream_configuration_proof', sequential=True)
    position_result = None
    if POSITION_NOTE in current:
        subprocess.run([sys.executable, str(ROOT / 'test/conv_frontend/tools/position_decode_equivalence.py'),
                        '--reference-ref', args.reference_ref, '--out', str(out / 'position')], check=True)
        position_result = json.loads((out / 'position/summary.json').read_text())
        if not position_result['passed'] or position_result['source_sha256'] != hashlib.sha256(current.encode()).hexdigest():
            raise RuntimeError('Position-decode proof is incomplete')
    result = {'passed': True, 'reference_ref': args.reference_ref,
              'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
              'remaining_module_body_identical': True, 'group_low_widths': list(range(1, 16)),
              'coordinate_input_bits': 51, 'arithmetic_input_constraints': [],
              'configuration_initial_reset': True,
              'arithmetic_proof': arithmetic_result, 'configuration_induction': state_result,
              'position_decode_proof': position_result}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print('FRONTEND_STREAM_BOUNDARY_EQUIVALENCE_PASS', out / 'summary.json')


if __name__ == '__main__':
    main()
