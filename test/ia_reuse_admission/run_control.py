#!/usr/bin/env python3
"""提取实际控制组合逻辑，证明计数宽度边界与任意请求条件下的等价关系。"""
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
sys.path.insert(0, str(ROOT / 'test/ia_write_output_depth'))
from primitives import prepare_models


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def between(text, first, last):
    start = text.index(first)
    return text[start:text.index(last, start)]


def assignment(text, name):
    match = re.search(r'\bassign\s+' + re.escape(name) + r'\s*=.*?;', text, re.S)
    if match is None:
        raise RuntimeError('Missing assignment: ' + name)
    return match[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='3c8cafeb')
    parser.add_argument('--current-root', type=Path, default=ROOT)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    ia_path = args.current_root / 'rtl/npu/loaders/ia_loader.sv'
    ctrl_path = args.current_root / 'rtl/npu/loaders/ia_loader_ctrl.sv'
    ia, ctrl = ia_path.read_text(), ctrl_path.read_text()
    reference_ia = read_rtl_source(args.reference + ':rtl/npu/loaders/ia_loader.sv', cwd=ROOT, text=True)
    reference_ctrl = read_rtl_source(args.reference + ':rtl/npu/loaders/ia_loader_ctrl.sv', cwd=ROOT, text=True)
    model, model_info = prepare_models(out, ('LUT3', 'LUT6', 'LUT6_2'))
    summary = {'reference_revision': args.reference, 'input_constraints': False,
               'source_sha256': {'rtl/npu/loaders/ia_loader.sv': digest(ia_path),
                                 'rtl/npu/loaders/ia_loader_ctrl.sv': digest(ctrl_path)},
               'primitive_models': model_info, 'runs': []}
    load_logic = between(ctrl, '  // 三种加载上界独立比较', '  logic load_is_last_col_tile;')
    pending_logic = between(ctrl, '  logic load_regular_pending,', '  logic can_start_load;')
    expected_last = assignment(reference_ctrl, 'load_is_last_row_tile').replace('load_is_last_row_tile', 'expected_last')
    count_source = '''module count_control #(parameter int REG_WIDTH=32, COUNT_WIDTH=29,
        LOAD_CNT_W=7, parameter bit p_control_use_lut=1'b1)(
        input logic [REG_WIDTH-1:0] cfg_ia_reuse_num, ia_reuse_num_act,
        input logic [LOAD_CNT_W-1:0] load_ia_cursor_cnt, load_tiles_done_cnt, pf_r_target,
        input logic load_l2_is_last, prefetch_active, is_last_l2_group,
        output logic o_equivalent);
        localparam int CNT_W = (COUNT_WIDTH < 1) ? 1 : COUNT_WIDTH;
        typedef logic [CNT_W-1:0] count_t;
        count_t r_cur;
        logic [LOAD_CNT_W-1:0] load_r_target, load_r_target_cnt;
        logic load_is_last_row_tile, expected_last, expected_pending;
    ''' + '\n'.join(assignment(reference_ctrl, name) for name in ('r_cur', 'load_r_target', 'load_r_target_cnt')) + '\n' + load_logic + pending_logic + expected_last + '''
        assign expected_pending = (load_ia_cursor_cnt < load_r_target_cnt) &&
                                  (load_tiles_done_cnt != load_r_target_cnt);
        assign o_equivalent = (load_is_last_row_tile == expected_last) &&
                              (load_target_pending == expected_pending);
    endmodule
'''
    count_miter = out / 'count_control.sv'
    count_miter.write_text(count_source)
    request_logic = between(ia, '    localparam bit p_request_use_lut', '    assign prefetch_idle')
    request_logic = re.sub(r'localparam bit p_request_use_lut\s*=.*?`endif',
                           "localparam bit p_request_use_lut = p_use_lut;", request_logic, flags=re.S)
    cached = re.search(r'\bwire request_cached\s*=.*?;', reference_ia, re.S)[0]
    demand = re.search(r'\bwire demand_request\s*=.*?;', reference_ia, re.S)[0]
    request_logic = assignment(ia, 'request_cache_eligible') + '\n' + request_logic
    request_source = '''module request_control #(parameter bit p_use_lut=1'b1)(
        input logic prefetch_enable_q, ctrl_load_req, ctrl_request_valid, prefetch_start,
        prefetch_request, ext_dma_start, dma_available, init_cfg, cache_flush, tl_busy,
        load_ia_granted, request_lookup_ready, preserve_cache_q, cache_valid, request_tag_match,
        output logic o_equivalent);
        logic request_cache_eligible, load_ia_req, ctrl_load_granted;
        logic expected_req, expected_granted;
    ''' + cached + '\n' + demand + '\n' + request_logic + '\n' + \
        assignment(reference_ia, 'load_ia_req').replace('load_ia_req', 'expected_req') + '\n' + \
        assignment(reference_ia, 'ctrl_load_granted').replace('ctrl_load_granted', 'expected_granted') + '''
        assign o_equivalent = (load_ia_req == expected_req) && (ctrl_load_granted == expected_granted);
    endmodule
'''
    request_source = request_source.replace('cache_tags_valid[request_descriptor.slot]', 'cache_valid')
    request_miter = out / 'request_control.sv'
    request_miter.write_text(request_source)
    profiles = [('count', width, count, use_lut) for width, count in
                ((1, 1), (2, 1), (3, 2), (4, 8), (7, 29), (8, 29), (12, 32))
                for use_lut in (0, 1)] + [('request', 0, 0, use_lut) for use_lut in (0, 1)]
    for kind, width, count, use_lut in profiles:
        name = f'{kind}_{width}_{count}_{use_lut}'
        top = kind + '_control'
        parameters = ([f'-GLOAD_CNT_W={width}', f'-GCOUNT_WIDTH={count}', f'-Gp_control_use_lut={use_lut}']
                      if kind == 'count' else [f'-Gp_use_lut={use_lut}'])
        source = count_miter if kind == 'count' else request_miter
        commands = ['read_slang --top ' + top + ' ' + ' '.join(parameters) + ' ' +
                    ' '.join(map(shlex.quote, map(str, (source, model, ROOT / 'rtl/common/add_equal.sv')))),
                    'prep -top ' + top + ' -flatten',
                    'sat -verify -prove o_equivalent 1 -show-inputs -show-outputs']
        script = out / (name + '.ys')
        script.write_text('\n'.join(commands) + '\n')
        log = out / (name + '.log')
        with log.open('w') as stream:
            run = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                  '--worker', str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                 timeout=120)
        row = {'name': name, 'count_width': count, 'load_count_width': width, 'use_lut': bool(use_lut),
               'passed': run.returncode == 0 and 'no model found: SUCCESS!' in log.read_text(),
               'script_sha256': digest(script), 'log_sha256': digest(log)}
        summary['runs'].append(row)
        summary['passed'] = len(summary['runs']) == len(profiles) and all(item['passed'] for item in summary['runs'])
        summary['miter_sha256'] = {path.name: digest(path) for path in (count_miter, request_miter)}
        (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps(row), flush=True)
        if not row['passed']:
            raise RuntimeError('Control proof did not complete: ' + name)
    if summary['source_sha256'] != {'rtl/npu/loaders/ia_loader.sv': digest(ia_path),
                                   'rtl/npu/loaders/ia_loader_ctrl.sv': digest(ctrl_path)}:
        raise RuntimeError('Control sources changed during verification')


if __name__ == '__main__':
    main()
