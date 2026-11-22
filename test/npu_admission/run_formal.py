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
from rtl_reference import read_current_source

ROOT = Path(__file__).resolve().parents[2]
TOP = Path('rtl/npu/top/npu_top.sv')
ADDRESS = Path('rtl/npu/top/frame_address_prepare.sv')
SCHEDULER = Path('rtl/npu/control/ps_window_scheduler.sv')
HELPER = Path('rtl/common/onehot_check.sv')
ADDER = Path('rtl/common/parallel_prefix_add.sv')
MEMORY = Path('rtl/common/regfile.v')
COMPARATOR = Path('rtl/common/unsigned_compare.sv')
SCHEDULER_PARTS = tuple(SCHEDULER.with_name(name) for name in
                        ('ps_scheduler_any.sv', 'ps_scheduler_priority.sv'))
FLAGS = ('run_vector', 'vector_rejected', 'vector_engine_ready', 'ctrl_sa_ready',
         'frame_scheduler_ready', 'cfg_stage0_valid', 'cfg_stage1_valid',
         'cfg_stage2_valid', 'operand_cache_idle', 'ia_prefetch_idle',
         'kernel_prefetch_idle', 'calc_start', 'cfg_vector_enable')
CURRENT_FLAGS = FLAGS + ('task_fault', 'kernel_loader_o_quiescent',
                         'kernel_loader_o_admission_request',
                         'block_dma_arbiter_o_kernel_eligible', 'conv_task_idle')


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


def current_admission(source, name):
    """提取组合资格；兼容接口 sa_ready 表示 task_accept_conditions。"""
    if 'assign task_accept_conditions =' in source:
        condition = re.search(r'assign task_accept_conditions = (.*?);', source, re.S)[1]
        start = re.search(r'assign cfg_start_event = (.*?);', source, re.S)[1]
        header = f'module {name}(input logic ' + ', '.join(CURRENT_FLAGS) + """,
    input logic [1:0] abort_state,
    output logic sa_ready, cfg_start_event);
    localparam logic [1:0] AB_IDLE=2'd0;
    wire frame_prefetch_idle=ia_prefetch_idle && kernel_prefetch_idle;
"""
        return header + f'assign sa_ready = {condition};\nassign cfg_start_event = {start};\nendmodule\n'
    body = admission(source, name)
    abort_pending = re.search(r'wire abort_pending = (.*?);', source)[1]
    arbiter_abort = re.search(r'assign block_dma_arbiter_i_abort = (.*?);', source)[1]
    declaration = '    output logic sa_ready, cfg_start_event);'
    extra_inputs = ', '.join(CURRENT_FLAGS[len(FLAGS):])
    body = body.replace(declaration, f'    input logic {extra_inputs},\n' + declaration)
    return body.replace('    wire frame_prefetch_idle=',
        f'    wire abort_pending = {abort_pending};\n'
        f'    wire block_dma_arbiter_i_abort = {arbiter_abort};\n'
        '    wire frame_prefetch_idle=', 1)


def admission_specification(name):
    return f'module {name}(input logic ' + ', '.join(CURRENT_FLAGS) + ''',
    input logic [1:0] abort_state,
    output logic sa_ready, cfg_start_event);
    logic kernel_idle;
    assign kernel_idle = kernel_prefetch_idle;
    assign sa_ready = !task_fault && abort_state == 2'd0 &&
        !run_vector && !vector_rejected && vector_engine_ready && ctrl_sa_ready &&
        frame_scheduler_ready && !cfg_stage0_valid && !cfg_stage1_valid &&
        !cfg_stage2_valid && operand_cache_idle && ia_prefetch_idle && kernel_idle && conv_task_idle;
    assign cfg_start_event = calc_start && sa_ready && !cfg_vector_enable;
endmodule
'''


def condition_module(body):
    """为组合检查使用明确的输出名称，保留版本比较调用的原接口。"""
    body = re.sub(r'\bsa_ready\b', 'accept_conditions', body)
    return re.sub(r'\bcfg_start_event\b', 'matrix_start_candidate', body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--admission-only', action='store_true',
                        help='仅检查寄存前的实际组合资格表达式')
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = (TOP,) if args.admission_only else (
        TOP, ADDRESS, SCHEDULER, *SCHEDULER_PARTS, HELPER, ADDER, MEMORY, COMPARATOR)
    hashes = {str(p): digest(source_root / p) for p in sources}
    report = {'passed': False, 'source_sha256': hashes,
              'script_sha256': digest(Path(__file__)),
              'scope': 'admission_only' if args.admission_only else 'complete_local_checks',
              'admission': [],
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

    def finish():
        if hashes != {str(p): digest(source_root / p) for p in sources}:
            raise RuntimeError('Sources changed during verification')
        report['passed'] = True
        (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print('requested proofs PASS', flush=True)

    # 组合资格是接收寄存器的输入；测试候选开始事件由同一资格直接计算。
    admission_file = out / 'admission.sv'
    admission_file.write_text(condition_module(admission_specification('admission_reference')) +
        condition_module(current_admission((source_root / TOP).read_text(), 'admission_current')))
    connections = ','.join('.'+name+'('+name+')' for name in CURRENT_FLAGS + ('abort_state',))
    header = 'module admission_proof(input logic ' + ','.join(CURRENT_FLAGS) + ''',
    input logic [1:0] abort_state, output logic equivalent);
    logic expected_conditions, expected_candidate, actual_conditions, actual_candidate;
'''
    proof = out / 'admission_proof.sv'
    proof.write_text(header + f'''
    admission_reference u_ref({connections},.accept_conditions(expected_conditions),
        .matrix_start_candidate(expected_candidate));
    admission_current u_dut({connections},.accept_conditions(actual_conditions),
        .matrix_start_candidate(actual_candidate));
    assign equivalent={{expected_conditions,expected_candidate}}=={{actual_conditions,actual_candidate}};
endmodule
''')
    _, log_hash = run('admission', [
        f'read_slang --top admission_proof {shlex.quote(str(admission_file))} {shlex.quote(str(proof))}',
        'prep -top admission_proof -flatten', 'check -assert',
        'sat -verify -prove equivalent 1 -show-inputs -show-outputs'],
        'SAT proof finished - no model found: SUCCESS!')
    report['admission'].append({'implementation': 'ordinary_rtl',
        'input_bits': len(CURRENT_FLAGS) + 2, 'output_bits': 2,
        'inputs_constrained': False, 'passed': True, 'log_sha256': log_hash,
        'outputs': {'accept_conditions': 'actual task_accept_conditions expression',
                    'matrix_start_candidate': 'calc_start && accept_conditions && !cfg_vector_enable'},
        'top_level_ready_register_included': False,
        'extracted_rtl_sha256': digest(admission_file), 'proof_rtl_sha256': digest(proof)})
    print('admission PASS', flush=True)
    if args.admission_only:
        finish()
        return

    # 在实际调度器中增加一个只读观察输出；所有原有状态和输入保持完整。
    scheduler = out / 'scheduler_observed.sv'
    text = read_current_source(source_root / SCHEDULER)
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
    import pyosys
    abc = Path(pyosys.__file__).parent / 'yosys-abc'
    report['abc_sha256'] = digest(abc)
    for size, frames, reuse in ((1,1,1), (4,3,4), (16,16,32), (16,16,0)):
        name = f'scheduler_s{size}_f{frames}_r{reuse}'
        aig = out / (name + '.aig')
        text, build_hash = run(name, [
            f'read_slang -D ASIC_SYNTHESIS=1 --top ps_window_scheduler -GSIZE={size} '
            f'-GFRAME_COUNT={frames} -GMAX_REUSE_TILES={reuse} {scheduler} '
            f'{source_root/HELPER} {source_root/ADDER} {source_root/MEMORY} {source_root/COMPARATOR}',
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
        f'-GFRAME_COUNT=16 -GMAX_REUSE_TILES=32 {scheduler} '
        f'{source_root/HELPER} {source_root/ADDER} {source_root/MEMORY} {source_root/COMPARATOR}',
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

    # 就绪参数只改变公开输出的中止屏蔽；内部接受事件始终检查中止。
    reference_source = out / 'address_reference.sv'
    reference_source.write_text((source_root/ADDRESS).read_text())
    current_source = out / 'address_current.sv'
    current_source.write_text((source_root/ADDRESS).read_text().replace('o_start_rdy', 'raw_start_rdy'))
    ports = re.search(r'\) \(\n(.*?)\n\);', (source_root/ADDRESS).read_text(), re.S)[1]
    port_names = re.findall(r'(?:input|output)\s+(?:wire\s+)?logic\s*(?:\[[^]]+\]\s*)?(\w+)', ports)
    if len(port_names) != len(re.findall(r'\b(?:input|output)\b', ports)):
        raise RuntimeError('Every frame address port must be included in the comparison')
    assert {'clk', 'rst_n', 'i_start', 'i_abort', 'o_start_rdy', 'o_result_vld'} <= set(port_names)
    for size, pipeline, mask in ((1,1,0), (16,1,0), (32,1,0), (16,0,0), (16,1,1), (16,0,1)):
        commands = []
        for label, path in (('reference',reference_source), ('current',current_source)):
            wrapper = out / f'address_{label}_s{size}_p{pipeline}_m{mask}.sv'
            params = f'.p_size({size}),.p_pipeline_products({pipeline})'
            params += f",.p_ready_mask_abort(1'b{mask if label == 'current' else 1})"
            conns = []
            for name in port_names:
                conns.append('.raw_start_rdy(raw_ready)' if label == 'current' and name == 'o_start_rdy'
                             else '.'+name+'('+name+')')
            footer = 'assign o_start_rdy=raw_ready && !i_abort;' if label == 'current' else ''
            raw_declaration = 'logic raw_ready;\n' if label == 'current' else ''
            wrapper.write_text(f'module address_compare({ports});\n' + raw_declaration +
                f'frame_address_prepare #({params}) u_impl('+','.join(conns)+');\n'+footer+'\nendmodule\n')
            commands += [f'read_slang --top address_compare {path} {wrapper} {source_root/ADDER}',
                'prep -top address_compare -flatten', 'memory_map', 'wreduce', 'async2sync', 'opt -full',
                f'rename address_compare {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
            'design -copy-from current -as current current', 'equiv_make reference current equivalent',
            'hierarchy -top equivalent', 'equiv_simple -seq 1', 'opt_clean',
            'equiv_induct -seq 2', 'equiv_status -assert']
        text, log_hash = run(f'address_s{size}_p{pipeline}_m{mask}', commands, 'Equivalence successfully proven')
        report['frame_address'].append({'size':size,'pipeline_products':pipeline,'ready_mask_abort':mask,
            'input_constraints':False, 'ready_observation':'raw_start_rdy and not i_abort',
            'reference':'current complete module with p_ready_mask_abort=1',
            'ports':port_names,
            'equivalent_bits':int(re.search(r'Of those cells (\d+) are proven', text)[1]),
            'passed':True,'log_sha256':log_hash})
        print('address', size, pipeline, mask, 'PASS', flush=True)
    finish()


if __name__ == '__main__':
    main()
