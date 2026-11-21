#!/usr/bin/env python3
"""从实际 RTL 提取请求选择逻辑，证明缓存行首标志在有效请求中的一致性。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = 'rtl/npu/conv/conv_im2col_frontend.sv'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def without_comments(source: str) -> str:
    return re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)


def assignment(source: str, name: str) -> str:
    matches = re.findall(r'\bassign\s+' + re.escape(name) + r'\s*=\s*(.*?);',
                         source, flags=re.S)
    if len(matches) != 1:
        raise ValueError(f'{name} 必须具有唯一连续赋值')
    return f'assign {name} = {matches[0]};'


def connection(source: str, name: str) -> str:
    starts = list(re.finditer(r'\.' + re.escape(name) + r'\s*\(', source))
    if len(starts) != 1:
        raise ValueError(f'{name} 必须具有唯一端口连接')
    start = starts[0].end()
    depth = 1
    for offset in range(start, len(source)):
        if source[offset] == '(':
            depth += 1
        elif source[offset] == ')':
            depth -= 1
            if depth == 0:
                return source[start:offset]
    raise ValueError(f'{name} 的端口连接不完整')


def comparison(current: str, reference: str) -> tuple[str, list[str]]:
    current = without_comments(current)
    reference = without_comments(reference)
    enum = re.search(r'typedef\s+enum\s+logic\s*\[\s*(\d+)\s*:\s*0\s*\]'
                     r'\s*\{(.*?)\}\s*st_t\s*;', current, flags=re.S)
    if enum is None:
        raise ValueError('未找到前端状态类型 st_t')
    states = [entry.split('=')[0].strip() for entry in enum.group(2).split(',')]
    if not states or any(not re.fullmatch(r'[A-Za-z_]\w*', name) for name in states):
        raise ValueError('无法识别前端合法状态集合')
    body = '\n'.join(assignment(current, name) for name in (
        'wr_valid', 'stream_context', 'stream_next_request', 'next_row_request',
        'incoming_request', 'cache_req_valid', 'incoming_context', 'cache_req_addr',
        'request_bypass', 'cache_port_valid', 'cache_req_ready'))
    legal = ' || '.join(f'state == {name}' for name in states)
    rtl = f'''module event_first_comparison #(
  parameter int SIZE = 16,
  parameter int LANES = 4,
  parameter bit REGISTER_CACHE_REQUEST = 1'b1,
  parameter int RW = $clog2(SIZE + 1),
  parameter int TILE_COUNT_W = $clog2(SIZE + 1),
  parameter int CHUNK_COUNT_W = $clog2(LANES + 1)
) (
  input logic [{enum.group(1)}:0] state_bits,
  input logic wr_ready, cache_rsp_valid, cache_rsp_error,
  input logic request_pending, request_event_first_q, geometry_tile,
  input logic current_word_hit, group_after_chunk, word_boundary,
  input logic chunk_reaches_end, row_last_q, row_base_valid,
  input logic next_row_padding, next_row_word_hit,
  input logic tile_valid, tile_ready, incoming_fast, incoming_padding,
  input logic incoming_word_hit, tile_q_before_end, tile_rows_in_range,
  input logic wr_last, cache_port_ready,
  input logic [31:0] addr, request_addr_q, incoming_addr, next_row_addr, next_byte_addr,
  input logic [RW-1:0] tile_rows, tile_cols,
  input logic [TILE_COUNT_W-1:0] col_remaining, active_remaining,
  input logic [CHUNK_COUNT_W-1:0] chunk_count,
  output logic equivalent, legal_state, cache_port_valid,
  output logic bypass_equivalent, unused_metadata_independent
);
  {enum.group(0)}
  st_t state;
  logic wr_valid, stream_context, stream_next_request, next_row_request;
  logic incoming_request, cache_req_valid, incoming_context, request_bypass;
  logic cache_req_ready, current_event, reference_event;
  logic [31:0] cache_req_addr, port_addr;
  assign state = st_t'(state_bits);
  {body}
  assign legal_state = {legal};
  assign current_event = {connection(current, 'req_event_first')};
  assign reference_event = {connection(reference, 'req_event_first')};
  assign port_addr = {connection(current, 'req_addr')};
  assign equivalent = current_event == reference_event;
  assign bypass_equivalent = state == FETCH && !wr_valid && !stream_context &&
      !stream_next_request && !next_row_request && !incoming_request &&
      cache_req_addr == addr && port_addr == addr &&
      current_event == (geometry_tile && addr[3:0] == 4'd0);
  assign unused_metadata_independent = request_pending || request_bypass ||
      (!cache_port_valid && cache_req_ready);
endmodule
'''
    return rtl, states


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--baseline-ref', default='dde5e7c9')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (source_root / FRONTEND).read_bytes()
    revision = subprocess.check_output(['git', 'rev-parse', args.baseline_ref],
                                       cwd=ROOT, text=True).strip()
    reference = subprocess.check_output(['git', 'show', f'{revision}:{FRONTEND}'], cwd=ROOT)
    rtl, states = comparison(current.decode(), reference.decode())
    target = out / 'event_first_comparison.sv'
    target.write_text(rtl)
    for label, data in (('current', current), ('reference', reference)):
        snapshot = out / 'inputs' / label / FRONTEND
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes(data)

    # 合法状态前提仅用于有效的寄存请求；直接模式和已保存请求逐输入检查。
    profiles = (
        ('direct', 0, 'equivalent', {}),
        ('registered_valid', 1, 'equivalent', {'legal_state': 1, 'cache_port_valid': 1}),
        ('registered_pending', 1, 'equivalent', {'request_pending': 1}),
        ('registered_bypass', 1, 'bypass_equivalent',
         {'legal_state': 1, 'cache_port_valid': 1, 'request_pending': 0}),
        ('registered_unused', 1, 'unused_metadata_independent', {}),
    )
    results = []
    for size, lanes in ((2, 1), (16, 4), (64, 16)):
        for name, registered, signal, constraints in profiles:
            label = f'{name}_s{size}_l{lanes}'
            script = out / f'{label}.ys'
            log = out / f'{label}.log'
            options = f'-GSIZE={size} -GLANES={lanes} -GREGISTER_CACHE_REQUEST={registered}'
            condition = ' '.join(f'-set {key} {value}' for key, value in constraints.items())
            script.write_text(
                f'read_slang --top event_first_comparison {options} {shlex.quote(str(target))}\n'
                'prep -top event_first_comparison -flatten\n'
                f'sat {condition} -show-inputs -show-outputs\n'
                f'sat {condition} -verify -prove {signal} 1 -show-inputs -show-outputs\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                '--worker', str(script)], cwd=ROOT, stdout=stream,
                               stderr=subprocess.STDOUT, check=True)
            transcript = log.read_text()
            if ('SAT solving finished - model found:' not in transcript or
                    'SAT proof finished - no model found: SUCCESS!' not in transcript):
                raise RuntimeError(f'{label} 未完成非空前提与属性证明')
            results.append({'case': label, 'passed': True, 'property': signal,
                            'constraints': constraints,
                            'premises_satisfiable': True,
                            'log_sha256': digest(log.read_bytes())})
            print('FRONTEND_EVENT_FIRST_PROOF_PASS', label, flush=True)
    if current != (source_root / FRONTEND).read_bytes():
        raise RuntimeError('证明期间前端源码发生变化')
    report = {
        'passed': True,
        'scope': '实际源码请求选择逻辑的二态组合 SAT；有效旁路采用声明中的合法状态集合',
        'reference_revision': revision,
        'legal_states': states,
        'source_sha256': {FRONTEND: digest(current)},
        'reference_source_sha256': {FRONTEND: digest(reference)},
        'runner_sha256': digest(Path(__file__).read_bytes()),
        'extracted_rtl_sha256': digest(target.read_bytes()),
        'cases': results,
    }
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
