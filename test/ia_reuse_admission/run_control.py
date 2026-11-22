#!/usr/bin/env python3
"""证明 IA 加载边界、剩余请求以及直接和寄存请求接口的完整输入关系。"""
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


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def between(text: str, first: str, last: str) -> str:
    start = text.index(first)
    return text[start:text.index(last, start)]


def assignment(text: str, name: str) -> str:
    match = re.search(r'\bassign\s+' + re.escape(name) + r'\s*=.*?;', text, re.S)
    if match is None:
        raise RuntimeError('赋值未找到: ' + name)
    return match[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--current-root', type=Path, default=ROOT)
    args = parser.parse_args()
    root, out = args.current_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths = [root / 'rtl/npu/loaders' / name for name in ('ia_loader.sv', 'ia_loader_ctrl.sv')]
    ia, control = (path.read_text() for path in paths)
    hashes = {str(path): digest(path) for path in paths}
    report = {'passed': False, 'source_sha256': hashes, 'external_inputs_constrained': False,
              'state_relations': {}, 'runs': []}

    # 已保存的下一游标先单独证明，再验证边界选择与实际行数比较。
    for name, relative in (('cursor_and_rows', 'test/ia_slot_stage/check_load_boundary.py'),
                           ('boundary_selection', 'test/ia_request_stage/check_boundary.py')):
        command = [sys.executable, str(ROOT / relative), '--source-root', str(root),
                   '--out', str(out / name)]
        with (out / (name + '.log')).open('w') as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
        summary = out / name / 'summary.json'
        result = json.loads(summary.read_text())
        if not result['passed']:
            raise RuntimeError('加载边界检查未完成: ' + name)
        report['state_relations'][name] = {'result': result, 'summary_sha256': digest(summary)}

    limits = ('load_last_equal_i_regular', 'load_last_equal_i_tail', 'load_last_equal_i_prefetch')
    declarations = '\n'.join('logic [LOAD_CNT_W-1:0] ' + name + ';' for name in limits)
    limit_assignments = '\n'.join(assignment(control, name) for name in limits)
    pending = between(control, '  logic load_regular_pending,', '  logic can_start_load;')
    count_model = out / 'count_control.sv'
    count_model.write_text('''`default_nettype none
module count_control #(parameter int REG_WIDTH=32,COUNT_WIDTH=29,LOAD_CNT_W=7)(
 input logic [REG_WIDTH-1:0] cfg_ia_reuse_num,ia_reuse_num_act,
 input logic [LOAD_CNT_W-1:0] load_ia_cursor_cnt,load_tiles_done_cnt,pf_r_target,
 input logic prefetch_active,is_last_l2_group,output logic equivalent);
 localparam int CNT_W=COUNT_WIDTH<1?1:COUNT_WIDTH;
 typedef logic [CNT_W-1:0] count_t;
 logic [LOAD_CNT_W-1:0] reference_target;
''' + declarations + '\n' + limit_assignments + '\n' + pending + '''
 assign reference_target=prefetch_active?pf_r_target:
   LOAD_CNT_W'(is_last_l2_group?count_t'(ia_reuse_num_act):count_t'(cfg_ia_reuse_num));
 assign equivalent=load_target_pending==
   ((load_ia_cursor_cnt<reference_target)&&(load_tiles_done_cnt!=reference_target));
endmodule
`default_nettype wire
''')

    request = between(ia, '    logic request_without_lookup,', '    assign prefetch_idle')
    eligibility = assignment(ia, 'request_cache_eligible').replace(
        'cache_tags_valid[request_descriptor.slot]', 'cache_valid')
    request_model = out / 'request_control.sv'
    request_model.write_text('''`default_nettype none
module request_control #(parameter bit p_register_dma_request=0)(
 input logic clk,rst_n,prefetch_enable_q,ctrl_load_req,ctrl_request_valid,
 input logic prefetch_start,prefetch_request,ext_dma_start,dma_available,
 input logic init_cfg,cache_flush,tl_busy,load_ia_granted,request_lookup_ready,
 input logic preserve_cache_q,cache_valid,request_tag_match,output logic equivalent);
 logic request_offer,request_permission,request_cache_eligible;
 logic load_ia_req,ctrl_load_granted;
 logic reference_request,reference_permission,reference_offer,reference_grant;
 logic reference_cached,reference_demand;
''' + eligibility + '\n' + request + '''
 assign reference_cached=request_lookup_ready&&preserve_cache_q&&cache_valid&&request_tag_match;
 assign reference_demand=ctrl_request_valid&&request_lookup_ready&&!reference_cached&&
   dma_available&&!init_cfg&&!cache_flush;
 assign reference_offer=prefetch_enable_q?
   (reference_demand||prefetch_request||ext_dma_start):
   ((ctrl_load_req&&(request_lookup_ready||!ctrl_request_valid))||prefetch_start);
 if(p_register_dma_request)begin:g_registered_reference
   always_ff @(posedge clk or negedge rst_n)begin
     if(!rst_n)reference_request<=1'b0;
     else if(init_cfg||cache_flush)reference_request<=1'b0;
     else reference_request<=reference_offer;
   end
   assign reference_permission=load_ia_granted&&reference_request;
 end else begin:g_direct_reference
   assign reference_request=reference_offer;
   assign reference_permission=load_ia_granted;
 end
 assign reference_grant=prefetch_enable_q?
   (ctrl_load_req&&!tl_busy&&!init_cfg&&!cache_flush&&
    (!ctrl_request_valid||(request_lookup_ready&&
      (reference_cached||(dma_available&&reference_permission))))):
   (reference_permission&&(!ctrl_request_valid||request_lookup_ready));
 assign equivalent={request_offer,load_ia_req,ctrl_load_granted}==
                   {reference_offer,reference_request,reference_grant};
endmodule
`default_nettype wire
''')

    profiles = [('count', width, count, 0) for width, count in
                ((1, 1), (2, 1), (3, 2), (4, 8), (7, 29), (8, 29), (12, 32))]
    profiles += [('request', 0, 0, registered) for registered in (0, 1)]
    for kind, width, count, registered in profiles:
        for configuration in ('ASIC_SYNTHESIS', 'XILINX_FPGA'):
            name = f'{kind}_w{width}_c{count}_registered{registered}_{configuration}'
            top = kind + '_control'
            parameters = ([f'-GLOAD_CNT_W={width}', f'-GCOUNT_WIDTH={count}']
                          if kind == 'count' else [f'-Gp_register_dma_request={registered}'])
            source = count_model if kind == 'count' else request_model
            commands = [f'read_slang -D{configuration}=1 -DSYNTHESIS=1 --top {top} ' +
                        ' '.join(parameters) + ' ' + shlex.quote(str(source)),
                        'prep -top ' + top + ' -flatten', 'check -assert']
            if kind == 'request' and registered:
                commands += ['async2sync', 'opt',
                    'sat -seq 2 -set-at 1 rst_n 0 -prove-skip 1 -prove equivalent 1 -verify',
                    'sat -seq 1 -tempinduct-inductonly -maxsteps 1 -prove equivalent 1 -verify']
            else:
                commands += ['sat -verify -prove equivalent 1 -show-inputs -show-outputs']
            script, log = out / (name + '.ys'), out / (name + '.log')
            script.write_text('\n'.join(commands) + '\n')
            with log.open('w') as stream:
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                    '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT, timeout=120)
            passed = result.returncode == 0 and 'SUCCESS!' in log.read_text()
            record = {'name': name, 'passed': passed, 'count_width': count,
                      'load_count_width': width, 'registered_request': bool(registered),
                      'configuration': configuration, 'log_sha256': digest(log)}
            report['runs'].append(record)
            print(json.dumps(record), flush=True)
            if not passed:
                raise RuntimeError('控制条件证明未完成: ' + str(log))
    if hashes != {str(path): digest(path) for path in paths}:
        raise RuntimeError('验证期间源文件发生变化')
    report['passed'] = True
    report['request_state_initialization'] = 'one reset edge; subsequent inputs unrestricted'
    report['request_unbounded_induction_steps'] = 1
    report['model_sha256'] = {path.name: digest(path) for path in (count_model, request_model)}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
