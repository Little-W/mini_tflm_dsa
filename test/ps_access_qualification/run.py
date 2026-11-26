#!/usr/bin/env python3
"""检查部分和存储访问资格的完整状态、二值组合关系和四态语义。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
RTL = Path('rtl/npu/ps_compact/ps_frame_store.sv')
FLAGS = ('capacity_fault', 'command_present', 'command_accepted', 'input_ended',
         'replay_armed', 'replay_active', 'replay_launch_q', 'encoder_done',
         'commit_next_complete_q', 'ram_read_valid', 'decoder_done', 'frame_final_q',
         'commit_complete_q', 'frame_init_q', 'replay_complete_q', 'frame_request',
         'configuration_ready', 'request_pending_q', 'request_fits_q',
         'frame_single_row_q', 'read_remaining_q', 'clear_metadata', 'cancel_prepared',
         'request_init', 'request_legal')
CASES = {
    'fixed': dict(MAX_FRAME_ROWS=512, FRAME_COUNT=16, POOL_BYTES=57344,
                  BANK_BYTES=8192, EXTERNAL_RAM=1, p_fixed_ps_channels=1),
    'rotating': dict(MAX_FRAME_ROWS=16, FRAME_COUNT=4, POOL_BYTES=14336,
                     BANK_BYTES=2048, EXTERNAL_RAM=1, p_fixed_ps_channels=0),
    'internal': dict(MAX_FRAME_ROWS=47, FRAME_COUNT=16, POOL_BYTES=4096,
                     BANK_BYTES=2048, EXTERNAL_RAM=0),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def section(text: str, first: str, last: str) -> str:
    start = text.index(first)
    return text[start:text.index(last, start)]


def qualifier_model(text: str, name: str) -> str:
    """直接提取生产 RTL 中的完成、准备和预取表达式。"""
    if 'assign prepare_eligible =' in text:
        prepare = ('logic complete_now, complete_eligible, prepare_eligible, prepare_start;\n' +
                   section(text, '    assign prepare_eligible =', '    assign frame_pressure'))
        complete = section(text, '    assign complete_eligible =', '    // 存储返回行直接写入队列')
        credit = section(text, '    logic prefetch_credit_available;', '    // 单行更新提交后才读取同一帧')
    else:
        prepare = 'wire complete_now;\n' + re.search(r'    wire prepare_start\s*=.*?;', text, re.S)[0]
        complete = re.search(r'    assign complete_now\s*=.*?;', text, re.S)[0]
        credit = ''
    prefetch = section(text, '    wire prepare_read_conflict =', '    wire [p_cursor_bits-1:0] read_issue_cursor')
    commit = re.search(r'    wire encode_commit_valid\s*=.*?;', text, re.S)[0] + '\n'
    commit += re.search(r'    wire last_commit_now\s*=.*?;', text, re.S)[0]
    return f'''// 比较真实 RTL 中的完成、准备和同步读取资格。
module {name} #(parameter int DEPTH=8, FIFO_PTR_BITS=$clog2(DEPTH),
    INPUT_BITS={len(FLAGS)}+4+2*(FIFO_PTR_BITS+1)) (
    input logic [INPUT_BITS-1:0] stimulus, // 任意控制状态、帧编号及队列计数
    output logic [3:0] result // 完成、准备、首行读取和物理读取资格
);
    localparam int DECODE_FIFO_ROWS=DEPTH, PREFETCH_CREDITS=DEPTH-1;
    logic {', '.join(FLAGS)};
    logic [1:0] request_id, frame_id_q;
    logic [FIFO_PTR_BITS:0] decoded_count, decoder_inflight;
    typedef struct packed {{ logic [1:0] id; logic init; logic legal; }} request_t;
    request_t request_q;
    assign {{{', '.join(FLAGS)}, request_id, frame_id_q, decoded_count, decoder_inflight}} = stimulus;
    assign request_q.id=request_id;
    assign request_q.init=request_init;
    assign request_q.legal=request_legal;
{prepare}
{commit}
{credit}
{prefetch}
{complete}
    assign result={{complete_now, prepare_start, prefetch_prepare, prefetch_fire}};
endmodule
'''


def worker(root: Path, script: Path, log: Path) -> str:
    with log.open('w') as stream:
        result = subprocess.run([sys.executable, str(root / 'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(script)], cwd=root,
                                stdout=stream, stderr=subprocess.STDOUT, timeout=900)
    text = log.read_text()
    if result.returncode:
        raise RuntimeError(f'形式检查未完成：{log}')
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='8b3728c0')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--skip-state', action='store_true')
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(['git', 'show', f'{args.reference}:{RTL}'], cwd=root, text=True)
    reference = out / 'reference.sv'
    reference.write_text(original)
    current = root / RTL
    resolver = runpy.run_path(str(root / 'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolver([current], root)
    hashes = {str(path.relative_to(root)): digest(path) for path in sources}
    report = {'passed': False, 'reference': args.reference, 'source_sha256': hashes,
              'reference_sha256': digest(reference), 'input_constraints': None,
              'complete_state': [], 'qualifier_checks': []}
    if not args.skip_state:
        for name, parameters in CASES.items():
            folder = out / name
            folder.mkdir(exist_ok=True)
            commands = []
            for label, path in [('reference', reference), ('current', current)]:
                inputs = resolver([path], root)
                commands += [
                    'read_slang --top ps_frame_store ' +
                    ' '.join(f'-G{key}={value}' for key, value in parameters.items()) + ' ' +
                    shlex.join(map(str, inputs)),
                    'prep -top ps_frame_store -flatten', 'memory_map', 'async2sync', 'opt_clean -purge',
                    f'rename ps_frame_store {label}', f'design -stash {label}',
                ]
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current',
                         'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                         'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert']
            script, log = folder / 'proof.ys', folder / 'proof.log'
            script.write_text('\n'.join(commands) + '\n')
            text = worker(root, script, log)
            match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
            if not match or int(match[2]) or 'Equivalence successfully proven' not in text:
                raise RuntimeError(f'完整状态等价检查未完成：{log}')
            row = {'case': name, 'parameters': parameters, 'passed': True,
                   'equivalent_bits': int(match[1]), 'log_sha256': digest(log)}
            report['complete_state'].append(row)
            print(json.dumps(row), flush=True)
    model = out / 'qualification.sv'
    model.write_text(qualifier_model(original, 'reference_qualifier') +
                     qualifier_model(current.read_text(), 'current_qualifier') + '''
module qualifier_proof #(parameter int DEPTH=8, W=25+4+2*($clog2(DEPTH)+1)) (
    input logic [W-1:0] stimulus, // 相同的任意控制输入
    output logic equivalent // 所有资格的四态值逐位相同
);
    logic [3:0] reference_result, current_result;
    reference_qualifier #(.DEPTH(DEPTH)) u_reference(.stimulus(stimulus),.result(reference_result));
    current_qualifier #(.DEPTH(DEPTH)) u_current(.stimulus(stimulus),.result(current_result));
    assign equivalent=(reference_result===current_result);
endmodule
''')
    for depth in (4, 6, 8, 16):
        folder = out / f'credit{depth}'
        folder.mkdir(exist_ok=True)
        width = len(FLAGS) + 4 + 2 * ((depth-1).bit_length()+1)
        script, log = folder / 'proof.ys', folder / 'proof.log'
        script.write_text(f'read_slang --top qualifier_proof -GDEPTH={depth} {shlex.quote(str(model))}\n'
                          'prep -top qualifier_proof -flatten\n'
                          'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        if 'SUCCESS!' not in worker(root, script, log):
            raise RuntimeError(f'组合资格证明未完成：{log}')
        bench = folder / 'four_state.sv'
        bench.write_text(f'''// 检查完成交接、队列边界、未知值和高阻值。
module tb;
    logic [{width-1}:0] stimulus;
    logic equivalent;
    integer checks=0;
    qualifier_proof #(.DEPTH({depth})) u_proof(.stimulus(stimulus),.equivalent(equivalent));
    task automatic check;
        #1;
        if (equivalent!==1'b1) $fatal(1,"PS qualifier differs: %b",stimulus);
        checks++;
    endtask
    initial begin
        stimulus='0;check();stimulus='1;check();stimulus='x;check();stimulus='z;check();
        for (int sample=0;sample<20000;sample++) begin
            for (int bit_index=0;bit_index<{width};bit_index++) stimulus[bit_index]=1'($urandom);
            check();
            stimulus[sample%{width}]=1'bx;check();
            stimulus[sample%{width}]=1'bz;check();
        end
        $display("PS_QUALIFIER_FOUR_STATE_PASS checks=%0d",checks);
        $finish;
    end
endmodule
''')
        binary = folder / 'four_state.vvp'
        with (folder / 'compile.log').open('w') as stream:
            subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(binary), str(model), str(bench)],
                           stdout=stream, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run(['vvp', str(binary)], capture_output=True, text=True, check=True, timeout=180)
        (folder / 'run.log').write_text(result.stdout + result.stderr)
        match = re.search(r'PS_QUALIFIER_FOUR_STATE_PASS checks=(\d+)', result.stdout)
        if match is None or int(match[1]) != 60004:
            raise RuntimeError('四态资格比较未完成')
        row = {'fifo_depth': depth, 'passed': True, 'four_state_checks': int(match[1]),
               'formal_log_sha256': digest(log), 'simulation_log_sha256': digest(folder / 'run.log')}
        report['qualifier_checks'].append(row)
        print(json.dumps(row), flush=True)
    if hashes != {str(path.relative_to(root)): digest(path) for path in sources}:
        raise RuntimeError('验证期间 RTL 源码发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
