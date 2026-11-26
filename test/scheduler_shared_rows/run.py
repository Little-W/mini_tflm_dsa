#!/usr/bin/env python3
"""证明完整帧调度器的状态与输出等价，并执行逐周期四态比较。"""
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
SOURCE = Path('rtl/npu/control/ps_window_scheduler.sv')
PROFILES = ('1:1:1', '4:3:4', '16:16:16', '16:16:32', '16:16:0', '16:17:64')
COMBINATIONAL_NAMES = (
    'candidate_row', 'row_advance_o_sum', 'initial_row_o_sum', 'stored_row_o_sum',
    'incoming_slice_invalid', 'incoming_reuse_invalid', 'incoming_slice_oversized',
    'incoming_reuse_oversized', 'unused_slice_equal', 'unused_reuse_equal',
    'u_slice_bound', 'u_reuse_bound', 'slice_shape_o_valid', 'u_slice_shape',
)
OUTPUTS = {
    'ready': '1', 'done_valid': '1', 'err_code': '2', 'command_valid': '1',
    'frame_id': 'ID_W', 'p0': '32', 'q0': '32', 'column0': '32', 'rows': '32',
    'cols': '32', 'count_k': '32', 'reserve_rows': '32', 'frame_init': '1',
    'frame_final': '1', 'command_active': '1', 'lookahead_valid': '1',
    'lookahead_q0': '32', 'lookahead_column': '32', 'lookahead_cols': '32',
    'lookahead_count_k': '32',
}
INPUTS = ('clk', 'rst_n', 'start', 'stream_rows', 'stationary_rows', 'reduction',
          'reuse_rows', 'window_frames', 'slice_tiles', 'config_error',
          'done_ready', 'command_ready', 'command_pressure', 'command_complete')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, check=True, timeout=360,
                       stdout=stream, stderr=subprocess.STDOUT)
    return log.read_text()


def instrument(source, label):
    if label == 'reference':
        marker = '    assign prepare_part_quotient = prepare_rows_last >> slice_shift;'
        if source.count(marker) != 1:
            raise RuntimeError('未找到参考调度器的切片取整表达式')
        source = source.replace(marker,
            '    // 准备行数的减一结果与新增保存状态构成归纳关系。\n'
            '    (* keep = 1 *) wire [PART_MATH_W-1:0] prepare_rows_last_q = prepare_rows_last;\n' + marker)
    # 组合候选值在实际寄存器使能处比较；全部状态、公开输出及存储内容逐周期比较。
    for name in COMBINATIONAL_NAMES:
        source = re.sub(r'\b' + name + r'\b', label + '_' + name, source)
    return source


def bench(cycles):
    text = '''// 同拍驱动两个完整调度器，并严格比较所有公开输出。
module tb;
 parameter SIZE=16, FRAME_COUNT=16, MAX_REUSE_TILES=16;
 localparam ID_W=FRAME_COUNT>1?$clog2(FRAME_COUNT):1;
 reg clk=0,rst_n=0,start=0,done_ready=1,command_ready=0,command_pressure=0,command_complete=0;
 reg [31:0] stream_rows=0,stationary_rows=0,reduction=0,reuse_rows=0,window_frames=0,slice_tiles=0;
 reg [1:0] config_error=0;
 reg [31:0] rng=32'h718cad09;
 integer checks=0,unknown_checks=0,commands=0;
 function automatic [31:0] random_word;
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
 endfunction
'''
    for label in ('reference', 'current'):
        text += '\n'.join(f' wire [{width}-1:0] {label}_{name};' for name, width in OUTPUTS.items()) + '\n'
        text += f' wire [511:0] {label}_result = {{' + ','.join(label + '_' + name for name in OUTPUTS) + '};\n'
        text += f' scheduler_{label} #(.SIZE(SIZE),.FRAME_COUNT(FRAME_COUNT),.MAX_REUSE_TILES(MAX_REUSE_TILES)) u_{label}(\n'
        connections = [f'.{name}({name})' for name in INPUTS]
        connections += [f'.{name}({label}_{name})' for name in OUTPUTS]
        text += '  ' + ',\n  '.join(connections) + '\n );\n'
    text += f''' initial begin
  for(integer cycle=0;cycle<{cycles};cycle++)begin
   clk=0;
   rst_n=(cycle%256)>1;
   start=(cycle%256)==2;
   done_ready=random_word()[0];
   command_ready=random_word()[0];
   command_pressure=((cycle%37)==17);
   command_complete=(reference_command_active===1'b1)&&random_word()[0];
   if(cycle%256==0)begin
    stream_rows=SIZE*(1+(random_word()%4));
    stationary_rows=SIZE*(1+(random_word()%4));
    reduction=SIZE*(1+(random_word()%4));
    reuse_rows=(MAX_REUSE_TILES==1)?1:2;
    window_frames=1+(random_word()%FRAME_COUNT);
    slice_tiles=((cycle/256)%3==0)?0:1;
    config_error=0;
    case((cycle/256)%16)
     5:reuse_rows='1;
     6:slice_tiles=32'h80000000;
     7:config_error=2'b01;
     8:slice_tiles=32'd3;
     9:stream_rows=0;
     default:;
    endcase
   end
   if(cycle%256>32 && cycle%13==0)begin
    case(random_word()%10)
     0:command_ready=1'bx;
     1:command_complete=1'bz;
     2:command_pressure=1'bx;
     3:start=1'bz;
     4:done_ready=1'bx;
     5:stream_rows[random_word()%32]=1'bx;
     6:reuse_rows[random_word()%32]=1'bz;
     7:slice_tiles[random_word()%32]=1'bx;
     8:stationary_rows[random_word()%32]=1'bz;
     9:reduction[random_word()%32]=1'bx;
    endcase
   end
   #4;clk=1;#2;
   if(reference_result!==current_result)
    $fatal(1,"Scheduler output differs cycle=%0d reference=%h current=%h",cycle,reference_result,current_result);
   checks++;
   if((^reference_result)===1'bx)unknown_checks++;
   if(reference_command_valid===1'b1 && command_ready===1'b1)commands++;
   #4;
  end
  if(commands==0 || unknown_checks==0)$fatal(1,"Scheduler stimulus coverage incomplete");
  $display("SCHEDULER_SHARED_ROWS_FOUR_STATE_PASS checks=%0d unknown_checks=%0d commands=%0d",checks,unknown_checks,commands);
  $finish;
 end
endmodule
'''
    # 返回值直接截断到控制位，兼容支持 SystemVerilog 的不同仿真器。
    return text.replace('random_word()[0]', "1'(random_word())")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='f45a6c21')
    parser.add_argument('--candidate-source', type=Path, default=ROOT / SOURCE)
    parser.add_argument('--dependency-root', type=Path, default=ROOT)
    parser.add_argument('--profiles', nargs='+', default=list(PROFILES))
    parser.add_argument('--modes', nargs='+', choices=('generic', 'fpga'), default=['generic', 'fpga'])
    parser.add_argument('--cycles', type=int, default=8192)
    parser.add_argument('--skip-four-state', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    source = args.candidate_source.resolve()
    texts = {'reference': subprocess.check_output(['git', 'show', args.reference + ':' + str(SOURCE)], cwd=ROOT, text=True),
             'current': source.read_text()}
    resolve = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    source_sets = {}
    for label, text in texts.items():
        saved = out / (label + '.sv'); saved.write_text(instrument(text, label))
        source_sets[label] = resolve([saved], args.dependency_root.resolve())
        (out / (label + '_simulation.sv')).write_text(text.replace('module ps_window_scheduler #', 'module scheduler_' + label + ' #'))
    helpers = sorted(set(source_sets['current'][1:] + source_sets['reference'][1:]))
    helper_hashes = {str(path): digest(path) for path in helpers}
    bench_path = out / 'tb.sv'; bench_path.write_text(bench(args.cycles))
    profiles, four_state = [], []
    for mode in args.modes:
        defines = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if mode == 'fpga' else []
        for profile in args.profiles:
            size, frames, reuse = map(int, profile.split(':'))
            parameters = dict(SIZE=size, FRAME_COUNT=frames, MAX_REUSE_TILES=reuse)
            name = mode + '_' + profile.replace(':', '_')
            commands = []
            for label in ('reference', 'current'):
                flags = defines + [f'-G{key}={value}' for key, value in parameters.items()]
                commands += ['read_slang --top ps_window_scheduler ' + shlex.join(flags + list(map(str, source_sets[label]))),
                    'prep -top ps_window_scheduler -flatten', 'memory_map', 'async2sync', 'opt_clean',
                    'rename ps_window_scheduler ' + label, 'design -stash ' + label]
            commands += ['design -copy-from reference -as reference reference',
                'design -copy-from current -as current current', 'equiv_make reference current equivalent',
                'hierarchy -top equivalent', 'equiv_simple -seq 1', 'opt_clean',
                'equiv_induct -seq 4', 'equiv_status -assert']
            script, log = out / (name + '.ys'), out / (name + '.log')
            script.write_text('\n'.join(commands) + '\n')
            result = execute([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
            match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', result)
            if not match or int(match[2]):
                raise RuntimeError('完整状态证明未完成：' + str(log))
            profiles.append({'mode': mode, 'parameters': parameters, 'passed': True,
                'equivalent_bits': int(match[1]), 'log_sha256': digest(log)})
            print('SCHEDULER_SHARED_ROWS_FORMAL_PASS', name, flush=True)
            if not args.skip_four_state:
                binary, run_log = out / (name + '.vvp'), out / (name + '_four.log')
                execute(['iverilog', '-g2012', '-s', 'tb', *defines,
                    *[f'-Ptb.{key}={value}' for key, value in parameters.items()], '-o', binary,
                    out / 'reference_simulation.sv', out / 'current_simulation.sv', bench_path, *helpers],
                    out / (name + '_compile.log'))
                result = execute(['vvp', binary], run_log)
                match = re.search(r'SCHEDULER_SHARED_ROWS_FOUR_STATE_PASS checks=(\d+) unknown_checks=(\d+) commands=(\d+)', result)
                if not match:
                    raise RuntimeError('完整调度器四态比较未完成：' + str(run_log))
                four_state.append({'mode': mode, 'parameters': parameters, 'passed': True,
                    **dict(zip(('cycles', 'unknown_output_cycles', 'commands'), map(int, match.groups()))),
                    'log_sha256': digest(run_log)})
    if source.read_text() != texts['current'] or helper_hashes != {str(path): digest(path) for path in helpers}:
        raise RuntimeError('验证期间源文件发生变化')
    summary = {'passed': True, 'reference_revision': args.reference, 'inputs_constrained': False,
        'all_public_outputs_and_state_compared': True, 'all_memory_contents_compared': True,
        'source_sha256': digest(source), 'reference_sha256': hashlib.sha256(texts['reference'].encode()).hexdigest(),
        'dependency_sha256': helper_hashes, 'formal_profiles': profiles, 'four_state_profiles': four_state,
        'formal_equivalent_bits': sum(row['equivalent_bits'] for row in profiles),
        'four_state_cycles': sum(row['cycles'] for row in four_state), 'test_sha256': digest(Path(__file__))}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
