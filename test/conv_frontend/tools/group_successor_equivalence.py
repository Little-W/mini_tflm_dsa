#!/usr/bin/env python3
"""证明组末偏移寄存器的更新关系及其快速请求比较结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from stream_boundary_equivalence import normalize_stream_source, START as STREAM_START

ROOT = Path(__file__).resolve().parents[3]
SOURCE = 'rtl/npu/conv/conv_im2col_frontend.sv'


def digest(value):
    return hashlib.sha256(value).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default='975ce61')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(['git', 'show', f'{args.reference_ref}:{SOURCE}'],
                                        cwd=ROOT, text=True)
    updates = re.findall(r'next_group_q\s*<=\s*([^;]+);', current)
    if len(updates) != 3:
        raise ValueError('The reset, configuration and descriptor assignments are required')
    reset, config, tile = updates
    current_predicate = re.search(r'incoming_q_fast\s*=\s*([^;]+);', current).group(1)
    reference_predicate = re.search(r'incoming_q_fast\s*=\s*([^;]+);', reference).group(1)
    # 逐字核对其余实际模块内容，确保证明覆盖全部改动。
    stream_changes = STREAM_START in current
    normalized = normalize_stream_source(current).replace('  logic [32:0] next_group_q;\n', '')
    normalized = normalized.replace('    // 组末偏移与描述符一起保存，快速接收路径只比较已有寄存结果。\n', '')
    normalized = re.sub(r'^\s*next_group_q\s*<=\s*[^;]+;\n', '', normalized, flags=re.M)
    normalized = normalized.replace(current_predicate, reference_predicate)
    coordinate_changes = False
    for signal in ('row_wrap', 'incoming_padding'):
        current_value = re.search(r'\b' + signal + r'\s*=\s*([^;]+);', current).group(1)
        reference_value = re.search(r'\b' + signal + r'\s*=\s*([^;]+);', reference).group(1)
        if current_value != reference_value:
            coordinate_changes = True
            normalized = normalized.replace(current_value, reference_value)
    if '  logic incoming_tap_wrap;\n' in normalized:
        coordinate_changes = True
        normalized = normalized.replace('  logic incoming_tap_wrap;\n', '')
        normalized = re.sub(r'^\s*incoming_tap_wrap\s*=\s*[^;]+;\n', '', normalized, flags=re.M)
        normalized = normalized.replace('if (incoming_tap_wrap) begin', "if (kx0+1==32'(c.kernel_w)) begin")
    normalized = normalized.replace('    // 高位非零即越界，低十六位与图像尺寸直接比较。\n', '')
    if 'if (row_wrap) begin ox_q' in normalized:
        coordinate_changes = True
        normalized = normalized.replace('if (row_wrap) begin ox_q', "if (ox+1==32'(c.output_w)) begin ox_q")
    if normalized != reference:
        raise ValueError('Uncovered changes remain in the actual frontend source')
    for source in (reference, current):
        q_updates = re.findall(r'(?<![A-Za-z0-9_])q0\s*<=\s*([^;]+);', source)
        c_updates = re.findall(r'(?<![A-Za-z0-9_])c\s*<=\s*([^;]+);', source)
        if q_updates != ['0', 'tile_q0'] or c_updates != ["'0", 'cfg']:
            raise ValueError('The source state-update ownership changed')
    # 原模块中 cfg_valid && cfg_ready 优先于有效描述符接收；条件保持完整。
    original_cfg = 'if (cfg_valid && cfg_ready) begin\n        c<=cfg;'
    original_tile = 'end else if (tile_valid && tile_ready) begin\n          if (tile_rows==0'
    if original_cfg not in current or original_tile not in current:
        raise ValueError('The configuration/descriptor update priority changed')

    def cfg_fields(text):
        return text.replace('cfg.group_c', 'cfg_group_c').replace('c.group_c', 'group_c_q')

    proof = out / 'group_successor.sv'
    proof.write_text(f'''module group_successor_proof (
  input logic clk, rst_n, cfg_fire, tile_fire, tile_legal,
  input logic [15:0] cfg_group_c,
  input logic [31:0] tile_q0,
  output logic equivalent
);
logic [31:0] q0;
logic [15:0] group_c_q;
logic [32:0] next_group_q;
logic current_fast, reference_fast;
always_ff @(posedge clk or negedge rst_n) begin
  if (!rst_n) begin
    q0 <= 32'd0;
    group_c_q <= 16'd0;
    next_group_q <= {cfg_fields(reset)};
  end else if (cfg_fire) begin
    group_c_q <= cfg_group_c;
    next_group_q <= {cfg_fields(config)};
  end else if (tile_fire && tile_legal) begin
    q0 <= tile_q0;
    next_group_q <= {cfg_fields(tile)};
  end
end
assign current_fast = {cfg_fields(current_predicate)};
assign reference_fast = {cfg_fields(reference_predicate)};
assign equivalent = next_group_q == ({{1'b0, q0}} + 33'(group_c_q)) &&
                    current_fast == reference_fast;
endmodule
''')
    script = out / 'proof.ys'
    script.write_text('read_slang --top group_successor_proof ' + shlex.quote(str(proof)) + '\n' +
        'prep -top group_successor_proof -flatten\nasync2sync\nopt\n' +
        'sat -verify -seq 2 -tempinduct -set-init-zero -prove equivalent 1 -show-inputs -show-outputs\n')
    log = out / 'proof.log'
    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True)
    if 'Induction step proven: SUCCESS!' not in log.read_text():
        raise RuntimeError('Temporal induction did not complete')
    coordinates = None
    if coordinate_changes:
        subprocess.run([sys.executable, str(ROOT / 'test/conv_frontend/tools/coordinate_boundary_equivalence.py'),
                        '--reference-ref', args.reference_ref, '--out', str(out / 'coordinates')], check=True)
        coordinates = json.loads((out / 'coordinates/summary.json').read_text())
        if not coordinates['passed'] or coordinates['source_sha256'] != digest(current.encode()):
            raise RuntimeError('Coordinate predicate equivalence is incomplete')
    stream = None
    if stream_changes:
        subprocess.run([sys.executable, str(ROOT / 'test/conv_frontend/tools/stream_boundary_equivalence.py'),
                        '--out', str(out / 'stream')], check=True)
        stream = json.loads((out / 'stream/summary.json').read_text())
        if not stream['passed'] or stream['source_sha256'] != digest(current.encode()):
            raise RuntimeError('Stream predicate equivalence is incomplete')
    result = {'passed': True, 'reference_ref': args.reference_ref,
              'source_sha256': digest(current.encode()), 'reference_sha256': digest(reference.encode()),
              'generated_proof_sha256': digest(proof.read_bytes()), 'proof_log_sha256': digest(log.read_bytes()),
              'method': 'SAT temporal induction of source-derived reset/configuration/descriptor updates and both comparison expressions',
              'input_constraints': [], 'state_relation_bits': 33,
              'remaining_module_body_identical': True, 'coordinate_predicate_proof': coordinates,
              'stream_predicate_proof': stream,
              'configuration_priority': 'reset, configuration acceptance, legal descriptor acceptance, hold'}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print('FRONTEND_GROUP_SUCCESSOR_EQUIVALENCE_PASS', out / 'summary.json')


if __name__ == '__main__':
    main()
