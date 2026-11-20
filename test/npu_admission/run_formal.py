#!/usr/bin/env python3
"""验证实际配置接收表达式、帧地址接收状态及调度器的空闲条件。"""
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
TOP = Path('rtl/npu/top/npu_top.sv')
ADDRESS = Path('rtl/npu/top/frame_address_prepare.sv')
SCHEDULER = Path('rtl/npu/control/ps_window_scheduler.sv')
HELPER = Path('rtl/common/onehot_check.sv')
FLAGS = ('run_vector', 'vector_rejected', 'vector_engine_ready', 'ctrl_sa_ready',
         'frame_scheduler_ready', 'cfg_stage0_valid', 'cfg_stage1_valid',
         'cfg_stage2_valid', 'operand_cache_idle', 'ia_prefetch_idle',
         'kernel_prefetch_idle', 'calc_start', 'cfg_vector_enable')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def admission(source, name):
    header = f'module {name}(input logic ' + ', '.join(FLAGS) + ''',
    input logic [1:0] abort_state,
    output logic sa_ready, cfg_start_event);
    localparam logic [1:0] AB_IDLE=2'd0;
    wire frame_prefetch_idle=ia_prefetch_idle && kernel_prefetch_idle;
'''
    begin = '        localparam bit p_admission_use_lut ='
    if begin in source:
        body = begin + source.split(begin, 1)[1].split('\n\n        // ABI 2:', 1)[0]
    else:
        body = re.search(r'assign sa_ready =.*?;', source, re.S)[0] + '\n'
        body += 'assign cfg_start_event = ' + re.search(r'wire cfg_start_event = (.*?);', source)[1] + ';'
    return header + body + '\nendmodule\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='eaba7635')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = (TOP, ADDRESS, SCHEDULER, HELPER)
    hashes = {str(p): digest(ROOT / p) for p in sources}
    old = {p: read_rtl_source(f'{args.reference_rev}:{p}', cwd=ROOT, text=True) for p in (TOP, ADDRESS)}
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = out / 'models.sv'
    bodies = []
    for primitive in ('LUT6', 'LUT6_2', 'DSP48E1'):
        body = re.search(r'^module '+primitive+r'\b.*?^endmodule', library.read_text(), re.M | re.S)[0]
        bodies.append(re.sub(r'\bspecify\b.*?\bendspecify\b', '', body, flags=re.S))
    model.write_text('\n\n'.join(bodies) + '\n')
    report = {'passed': False, 'reference_rev': args.reference_rev, 'source_sha256': hashes,
              'official_library_sha256': digest(library), 'admission': [],
              'scheduler_invariant': [], 'frame_address': []}

    def run(name, commands, expected, timeout=300):
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=timeout)
        text = log.read_text()
        if result.returncode or expected not in text:
            raise RuntimeError(f'Proof did not complete: {log}\n{text[-4000:]}')
        return text, digest(log)

    # 每次运行重新提取实际源码，参考与当前版本分别使用原有表达式。
    admission_file = out / 'admission.sv'
    admission_file.write_text(admission(old[TOP], 'admission_reference') +
                              admission((ROOT/TOP).read_text(), 'admission_current'))
    connections = ','.join('.'+name+'('+name+')' for name in FLAGS + ('abort_state',))
    header = 'module admission_proof(input logic ' + ','.join(FLAGS) + ''',
    input logic [1:0] abort_state, output logic equivalent);
    logic old_ready, old_start, new_ready, new_start;
'''
    proof = out / 'admission_proof.sv'
    proof.write_text(header + f'''
    admission_reference u_ref({connections},.sa_ready(old_ready),.cfg_start_event(old_start));
    admission_current u_dut({connections},.sa_ready(new_ready),.cfg_start_event(new_start));
    assign equivalent={{old_ready,old_start}}=={{new_ready,new_start}};
endmodule
''')
    for fpga in (0, 1):
        define = 'XILINX_FPGA=1' if fpga else 'ASIC_SYNTHESIS=1'
        _, log_hash = run(f'admission_fpga{fpga}', [
            f'read_slang -D {define} --top admission_proof {admission_file} {proof} {model}',
            'prep -top admission_proof -flatten',
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs'],
            'SAT proof finished - no model found: SUCCESS!')
        report['admission'].append({'fpga': fpga, 'input_bits': 15, 'output_bits': 2,
                                    'passed': True, 'log_sha256': log_hash})
        print('admission', fpga, 'PASS', flush=True)

    # 在实际调度器中增加一个只读观察输出；所有原有状态和输入保持完整。
    scheduler = out / 'scheduler_observed.sv'
    text = (ROOT/SCHEDULER).read_text()
    marker = 'lookahead_q0, lookahead_column, lookahead_cols, lookahead_count_k);'
    assert text.count(marker) == 1
    text = text.replace(marker, marker[:-2] + ',\n    output logic formal_bad, formal_ready_seen);')
    text = text.replace('endmodule', '''
    logic formal_started=1'b0;
    always_ff @(posedge clk) if (!rst_n) formal_started<=1'b1;
    assign formal_bad=formal_started && ready && command_valid;
    assign formal_ready_seen=formal_started && ready;
endmodule''', 1)
    scheduler.write_text(text)
    abc = Path(pyosys.__file__).parent / 'yosys-abc'
    report['abc_sha256'] = digest(abc)
    for size, frames, reuse in ((1,1,1), (4,3,4), (16,16,32), (16,16,0)):
        name = f'scheduler_s{size}_f{frames}_r{reuse}'
        aig = out / (name + '.aig')
        text, build_hash = run(name, [
            f'read_slang -D ASIC_SYNTHESIS=1 --top ps_window_scheduler -GSIZE={size} '
            f'-GFRAME_COUNT={frames} -GMAX_REUSE_TILES={reuse} {scheduler} {ROOT/HELPER}',
            'prep -top ps_window_scheduler -flatten', 'memory_map', 'async2sync',
            'delete -output */o:*', 'expose ps_window_scheduler/formal_bad', 'opt -full',
            'techmap', 'opt -full', 'dffunmap', 'techmap', 'opt_clean', 'aigmap',
            f'write_aiger -zinit -miter -symbols {aig}'], 'Executing AIGER backend.', timeout=300)
        log = out / (name + '_pdr.log')
        with log.open('w') as stream:
            result = subprocess.run([str(abc), '-c', f'read_aiger {aig}; pdr'],
                stdout=stream, stderr=subprocess.STDOUT, timeout=300)
        if result.returncode or 'Property proved.' not in log.read_text():
            raise RuntimeError(f'Unbounded scheduler proof did not complete: {log}')
        report['scheduler_invariant'].append({'size':size, 'frames':frames, 'max_reuse_tiles':reuse,
            'property':'ready implies not command_valid', 'inputs_constrained':False,
            'initialization':'all original state is unconstrained until reset is observed',
            'method':'ABC PDR with zero-initialization conversion and free initial-state inputs',
            'passed':True, 'log_sha256':digest(log), 'aiger_sha256':digest(aig),
            'build_log_sha256':build_hash})
        print('scheduler', size, frames, reuse, 'PASS', flush=True)

    # 检查实际复位后能够进入所观察的空闲状态。
    cover_aig = out / 'scheduler_ready_cover.aig'
    _, cover_build_hash = run('scheduler_ready_cover', [
        f'read_slang -D ASIC_SYNTHESIS=1 --top ps_window_scheduler -GSIZE=16 '
        f'-GFRAME_COUNT=16 -GMAX_REUSE_TILES=32 {scheduler} {ROOT/HELPER}',
        'prep -top ps_window_scheduler -flatten', 'memory_map', 'async2sync',
        'delete -output */o:*', 'expose ps_window_scheduler/formal_ready_seen', 'opt -full',
        'techmap', 'opt -full', 'dffunmap', 'techmap', 'opt_clean', 'aigmap',
        f'write_aiger -zinit -miter -symbols {cover_aig}'], 'Executing AIGER backend.')
    cover_log = out / 'scheduler_ready_cover_pdr.log'
    with cover_log.open('w') as stream:
        result = subprocess.run([str(abc), '-c', f'read_aiger {cover_aig}; pdr'],
            stdout=stream, stderr=subprocess.STDOUT, timeout=300)
    if result.returncode or not re.search(r'Output \d+ of miter .*asserted in frame', cover_log.read_text()):
        raise RuntimeError(f'Scheduler ready state was not reached: {cover_log}')
    report['scheduler_ready_coverage']={'passed':True,'log_sha256':digest(cover_log),
        'build_log_sha256':cover_build_hash,'aiger_sha256':digest(cover_aig)}

    # 映射参数只改变就绪信号是否包含中止条件；内部状态和接受事件逐周期相同。
    reference_source = out / 'address_reference.sv'
    reference_source.write_text(old[ADDRESS])
    current_source = out / 'address_current.sv'
    current_source.write_text((ROOT/ADDRESS).read_text().replace('o_start_rdy', 'raw_start_rdy'))
    ports = re.search(r'\) \(\n(.*?)\n\);', old[ADDRESS], re.S)[1]
    port_names = re.findall(r'(?:input|output)\s+logic\s*(?:\[[^]]+\]\s*)?(\w+)', ports)
    for size, dsp, mask in ((1,0,0), (16,0,0), (32,0,0), (16,1,0), (16,0,1), (16,1,1)):
        commands = []
        for label, path in (('reference',reference_source), ('current',current_source)):
            wrapper = out / f'address_{label}_s{size}_d{dsp}_m{mask}.sv'
            params = f'.p_size({size}),.p_use_dsp({dsp})'
            if label == 'current': params += f",.p_ready_mask_abort(1'b{mask})"
            conns = []
            for name in port_names:
                conns.append('.raw_start_rdy(raw_ready)' if label == 'current' and name == 'o_start_rdy'
                             else '.'+name+'('+name+')')
            footer = 'assign o_start_rdy=raw_ready && !i_abort;' if label == 'current' else ''
            raw_declaration = 'logic raw_ready;\n' if label == 'current' else ''
            wrapper.write_text(f'module address_compare({ports});\n' + raw_declaration +
                f'frame_address_prepare #({params}) u_impl('+','.join(conns)+');\n'+footer+'\nendmodule\n')
            commands += [f'read_slang -D VERIFIC --top address_compare --blackboxed-module DSP48E1 '
                f'-v {model} {path} {wrapper}', f'read_verilog -formal -sv -D VERIFIC -overwrite {model}',
                'prep -top address_compare -flatten', 'memory_map', 'wreduce', 'async2sync', 'opt -full',
                f'rename address_compare {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
            'design -copy-from current -as current current', 'equiv_make reference current equivalent',
            'hierarchy -top equivalent', 'equiv_simple -seq 1', 'opt_clean',
            'equiv_induct -seq 2', 'equiv_status -assert']
        text, log_hash = run(f'address_s{size}_d{dsp}_m{mask}', commands, 'Equivalence successfully proven')
        report['frame_address'].append({'size':size,'dsp':dsp,'ready_mask_abort':mask,
            'input_constraints':False, 'ready_observation':'raw_start_rdy and not i_abort',
            'equivalent_bits':int(re.search(r'Of those cells (\d+) are proven', text)[1]),
            'passed':True,'log_sha256':log_hash})
        print('address', size, dsp, mask, 'PASS', flush=True)

    # 组合证明使用上面的实际调度器不变量及实际上层的两个接收表达式。
    top_text = (ROOT/TOP).read_text()
    ready_expr = re.search(r'assign frame_command_ready = (.*?);', top_text)[1]
    abort_expr = re.search(r'assign frame_address_i_abort = (.*?);', top_text)[1]
    assert ready_expr == re.search(r'assign frame_command_ready = (.*?);', old[TOP])[1]
    composition = out / 'composition.sv'
    composition.write_text('module admission_composition(input logic '+','.join(FLAGS)+''',
    input logic [1:0] abort_state,
    input logic frame_command_valid,frame_mode_q,address_idle,ps_frame_ready,
    inner_done_valid,abort_pending,task_fault,output logic equivalent);
    logic sa_ready,cfg_start_event,frame_address_i_abort;
    logic old_ready,new_ready,old_start,new_start;
''' + f'admission_current u_admission({connections},.sa_ready(sa_ready),.cfg_start_event(cfg_start_event));\n'
        + 'assign frame_address_i_abort='+abort_expr+';\n'
        + 'assign old_ready='+ready_expr.replace('frame_address_o_start_rdy', '(address_idle && !frame_address_i_abort)')+';\n'
        + 'assign new_ready='+ready_expr.replace('frame_address_o_start_rdy', 'address_idle')+';\n'
        + '''assign old_start=frame_command_valid && old_ready;
    assign new_start=frame_command_valid && new_ready;
    assign equivalent=(frame_scheduler_ready && frame_command_valid) || (old_start==new_start);
endmodule
''')
    _, log_hash = run('composition', [f'read_slang -D XILINX_FPGA=1 --top admission_composition '
        f'{admission_file} {composition} {model}', 'prep -top admission_composition -flatten',
        'sat -verify -prove equivalent 1 -show-inputs -show-outputs'],
        'SAT proof finished - no model found: SUCCESS!')
    report['composition']={'passed':True,'scheduler_invariant_proven':True,'log_sha256':log_hash}
    assert hashes == {str(p):digest(ROOT/p) for p in sources}
    report['passed']=True
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('all proofs PASS',flush=True)


if __name__ == '__main__':
    main()
