#!/usr/bin/env python3
"""验证线性 DMA 行末状态、全部公开输出和完整内部状态。"""
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
SOURCE = Path('rtl/npu/dma/axi_linear_block_dma.sv')
PROFILES = (
    dict(SIZE=16, BUS_WIDTH=32, READ_OUTSTANDING=4, WRITE_OUTSTANDING=4),
    dict(SIZE=16, BUS_WIDTH=64, READ_OUTSTANDING=4, WRITE_OUTSTANDING=4),
    dict(SIZE=16, BUS_WIDTH=128, READ_OUTSTANDING=1, WRITE_OUTSTANDING=1),
    dict(SIZE=64, BUS_WIDTH=64, CACHE_BLOCKS=64, RD_CONTEXT_DEPTH=3),
    dict(SIZE=2, BUS_WIDTH=32, RD_CONTEXT_DEPTH=1, READ_OUTSTANDING=1, WRITE_OUTSTANDING=1),
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prove(root, reference, current, out, resolver):
    out.mkdir(parents=True, exist_ok=True)
    # 保存拍计数与行末比较之间的关系，归纳检查覆盖新增状态。
    observed = reference.replace('endmodule',
        '    (* keep = 1 *) wire wr_cross_row_end_q = wr_cross_row_end;\nendmodule', 1)
    (out / 'reference.sv').write_text(observed)
    # 组合分解节点在状态前推后具有不同定义；以原寄存器及公开输出比较完整行为。
    for name in ('wr_cross_equal_group', 'wr_cross_row_end', 'wr_plain_row_end',
                 'wr_cfg_cross_last', 'wr_cfg_burst_len_ext', 'wr_tail_beat', 'wr_row_end'):
        current = re.sub(r'\b' + name + r'\b', 'candidate_' + name, current)
    (out / 'current.sv').write_text(current)
    records = []
    for mode, flags in (('generic', ''), ('fpga_synthesis', '-DSYNTHESIS=1 -DXILINX_FPGA=1')):
        for index, parameters in enumerate(PROFILES):
            options = ' '.join(f'-G{key}={value}' for key, value in parameters.items())
            commands = []
            for label in ('reference', 'current'):
                paths = resolver([out / (label + '.sv')], root)
                commands += [
                    f'read_slang {flags} --top axi_linear_block_dma {options} ' +
                    shlex.join(map(str, paths)),
                    'prep -top axi_linear_block_dma -flatten', 'memory_map', 'async2sync',
                    'opt_clean', f'rename axi_linear_block_dma {label}', f'design -stash {label}',
                ]
            commands += [
                'design -copy-from reference -as reference reference',
                'design -copy-from current -as current current',
                'equiv_make reference current comparison', 'hierarchy -top comparison',
                'equiv_simple -short -seq 1', 'opt_clean', 'equiv_induct -seq 3',
                'equiv_status -assert',
            ]
            script, log = out / f'{mode}_{index}.ys', out / f'{mode}_{index}.log'
            script.write_text('\n'.join(commands) + '\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                               check=True, timeout=240)
            text = log.read_text()
            counts = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
            if not counts or int(counts[2]) or 'Equivalence successfully proven' not in text:
                raise RuntimeError('完整状态等价性检查未完成')
            records.append(dict(mode=mode, parameters=parameters, equivalent_bits=int(counts[1]),
                                passed=True, log_sha256=digest(log)))
            print(mode, index, counts[1], 'PASS', flush=True)
    return records


def simulate(root, reference, current, current_path, out, resolver, cycles):
    out.mkdir(parents=True, exist_ok=True)
    for label, text in (('reference', reference), ('current', current)):
        (out / (label + '.sv')).write_text(
            text.replace('module axi_linear_block_dma', 'module ' + label, 1))
    header = reference.split('\n);', 1)[0]
    header = re.sub(r'/\*[\s\S]*?\*/|//[^\n]*', '', header)
    ports = re.findall(
        r'^\s*(input|output)\s+(?:(?:wire|logic|reg|signed)\s+)*'
        r'(\[[^\]]+\]\s*)?(\w+)\s*(\[[^\]]+\])?\s*(?:=[^,\n]*)?[,\n]',
        header + '\n', re.M)
    if len(ports) <= 65 or len({port[2] for port in ports}) != len(ports):
        raise RuntimeError('DMA 公开端口解析不完整')
    inputs = [name for direction, width, name, array in ports
              if direction == 'input' and name not in ('clk', 'rst_n')]
    outputs = [(name, array) for direction, width, name, array in ports if direction == 'output']
    declarations, instances = [], []
    for direction, width, name, array in ports:
        if name in ('clk', 'rst_n'):
            continue
        for prefix in ([''] if direction == 'input' else ['old_', 'new_']):
            kind = 'logic' if direction == 'input' else 'wire'
            signed = 'signed ' if name == 'wr_data' else ''
            declarations.append(f'    {kind} {signed}{width}{prefix}{name} {array};')
    for label, prefix in (('reference', 'old_'), ('current', 'new_')):
        connections = ', '.join(f'.{name}({name if direction == "input" else prefix + name})'
                                for direction, width, name, array in ports)
        instances.append(f'{label} #(.BUS_WIDTH(BUS_WIDTH),.SIZE(SIZE),.DATA_WIDTH(DATA_WIDTH),'
                         f'.READ_OUTSTANDING(4),.WRITE_OUTSTANDING(4)) u_{label}({connections});')
    checks = '\n'.join(
        (f'for(integer lane=0;lane<BUS_WIDTH/8;lane++) '
         f'if(old_{name}[lane] !== new_{name}[lane]) '
         f'$fatal(1,"array {name} mismatch cycle=%0d",count);') if array else
        (f'if(old_{name} !== new_{name}) $fatal(1,"{name} mismatch cycle=%0d",count);')
        for name, array in outputs)
    bench = '''module tb;
localparam BUS_WIDTH=64,SIZE=16,DATA_WIDTH=16,REG_WIDTH=32,CACHE_BLOCKS=4,RD_TAG_WIDTH=3;
logic clk=0,rst_n=0;
''' + '\n'.join(declarations + instances) + f'''
localparam INPUT_BITS=$bits({{{','.join(inputs)}}});
logic [INPUT_BITS-1:0] stimulus;
integer seed=32'h279361ab,count=0;
always_comb {{{','.join(inputs)}}}=stimulus;
task compare;
begin
 #1;
 {checks}
 if(u_current.wr_cross_row_end_q !== u_reference.wr_cross_row_end)
  $fatal(1,"row flag mismatch cycle=%0d",count);
end
endtask
task tick;
begin clk=0;compare();clk=1;compare();clk=0;count++;end
endtask
initial begin
 stimulus='0;tick();rst_n=1;
 for(integer sample=0;sample<{cycles};sample++)begin
  rst_n=sample%127!=0;
  for(integer bit_index=0;bit_index<INPUT_BITS;bit_index++)begin
   case($random(seed)&31)
    0:stimulus[bit_index]=1'bx;
    1:stimulus[bit_index]=1'bz;
    default:stimulus[bit_index]=$random(seed);
   endcase
  end
  if(sample%16==0)stimulus='0;
  if(sample%16==1)stimulus='1;
  if(sample%43==0 && sample!=0)rst_n=1'bx;
  if(sample%47==0 && sample!=0)rst_n=1'bz;
  tick();
 end
 $display("DMA_ROW_FOUR_STATE_PASS cycles=%0d outputs={len(outputs)}",count);$finish;
end
endmodule
'''
    (out / 'tb.sv').write_text(bench)
    dependencies = resolver([current_path], root)[1:]
    records = []
    for mode, flags in (('generic', []), ('fpga_synthesis', ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'])):
        binary, compile_log = out / (mode + '.vvp'), out / (mode + '_compile.log')
        with compile_log.open('w') as stream:
            subprocess.run(['iverilog', '-g2012', *flags, '-s', 'tb', '-o', str(binary),
                            str(out / 'reference.sv'), str(out / 'current.sv'),
                            *map(str, dependencies), str(out / 'tb.sv')], stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=60)
        result = subprocess.run(['vvp', str(binary)], capture_output=True, text=True, timeout=180)
        log = out / (mode + '.log')
        log.write_text(result.stdout + result.stderr)
        if result.returncode or 'DMA_ROW_FOUR_STATE_PASS' not in result.stdout:
            raise RuntimeError(result.stdout + result.stderr)
        records.append(dict(mode=mode, cycles=cycles + 1, public_outputs=len(outputs),
                            comparisons=2 * (cycles + 1) * (len(outputs) + 1),
                            unknown_controls=True, unknown_payload=True, unknown_reset=True,
                            passed=True, log_sha256=digest(log)))
        print(mode, result.stdout.strip(), flush=True)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='73b91678')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cycles', type=int, default=30000)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current_path = root / SOURCE
    current = current_path.read_text()
    reference = subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'],
                                        cwd=ROOT, text=True)
    resolver = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    paths = [*resolver([current_path], root), Path(__file__).resolve()]
    hashes = {str(path): digest(path) for path in paths}
    report = dict(reference=args.reference, source_sha256=hashes,
                  reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  functional_inputs_constrained=False, all_public_outputs_compared=True,
                  all_matching_state_compared=True, row_flag_relation_proved=True)
    report['formal'] = prove(root, reference, current, out / 'formal', resolver)
    report['four_state'] = simulate(root, reference, current, current_path, out / 'four_state',
                                    resolver, args.cycles)
    if hashes != {str(path): digest(path) for path in paths}:
        raise RuntimeError('验证期间源码发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
