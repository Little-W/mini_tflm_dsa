#!/usr/bin/env python3
"""验证完整 SoC 互连的写接收条件、四态行为与并发写事务。"""
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
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_current_source, read_rtl_source_group

SOURCE = Path('rtl/soc/soc_axi_interconnect.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log):
    with log.open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=900)


def bind_predecoded_snapshot(source):
    """组合证明的输入关系：缓存目的标志等于当前缓存地址的译码。"""
    port = "    input wire [4:0] i_cpu_aw_dest_flags = 5'b0 /* 已与第零个写地址同步保存的目的端口标志。 */,\n"
    if source.count(port) != 1:
        raise ValueError('写地址目的标志端口缺失')
    marker = '    assign cpu_aw_dest_flags = '
    if source.count(marker) != 1:
        raise ValueError('写地址目的标志选择缺失')
    return source.replace(port, '').replace(marker,
        '    wire [4:0] i_cpu_aw_dest_flags = decode_cpu_flags(s0_axi_awaddr);\n' + marker)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='8b3728c008e6093095c8ade34aa4516145bc6005')
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--predecoded', action='store_true',
                        help='验证目的标志已经与缓存地址对应时的完整互连')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', args.reference+'^{commit}'],
                                       cwd=ROOT, text=True).strip()
    snapshots = {'reference': out/'reference.sv', 'current': out/'current.sv'}
    snapshots['reference'].write_bytes(read_rtl_source_group(f'{revision}:{SOURCE}', cwd=ROOT))
    current_text = read_current_source(ROOT/SOURCE)
    snapshots['current'].write_text(bind_predecoded_snapshot(current_text) if args.predecoded else current_text)
    hashes = {name: digest(path) for name, path in snapshots.items()}
    source_hash = digest(ROOT/SOURCE)
    configurations = runpy.run_path(str(ROOT/'test/soc_interconnect_depth/run_formal.py'))['profiles']()
    report = {'reference_commit': revision, 'source_sha256': source_hash,
              'snapshot_sha256': hashes, 'functional_inputs_constrained': False,
              'all_public_outputs_compared': True, 'all_registers_compared': True,
              'predecoded': args.predecoded,
              'derived_input_relation': 'saved destination equals buffered address decode' if args.predecoded else None,
              'formal': [], 'four_state': [], 'passed': False}
    for index, parameters in enumerate(dict(profile, p_cpu_ram_write_overlap=overlap)
            for profile in configurations for overlap in (0, 1)):
        folder = out/f'formal_{index}'
        folder.mkdir(exist_ok=True)
        options = ' '.join(f'-G{key}={value}' for key, value in parameters.items())
        commands = []
        for name, path in snapshots.items():
            selected_options = options + (' -Gp_cpu_aw_predecoded=1' if name == 'current' and args.predecoded else '')
            commands += [
                f'read_slang --top soc_axi_interconnect -D SYNTHESIS=1 -D XILINX_FPGA=1 {selected_options} {shlex.quote(str(path))}',
                'setattr -set keep 1 w:cpu_w_dest_flags',
                'prep -top soc_axi_interconnect -flatten', 'memory_map', 'async2sync', 'opt_clean',
                f'rename soc_axi_interconnect {name}', f'design -stash {name}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                     'opt_merge', 'equiv_simple -short -seq 1', 'opt_clean',
                     'equiv_induct -seq 2', 'equiv_status -assert']
        script, log = folder/'formal.ys', folder/'formal.log'
        script.write_text('\n'.join(commands)+'\n')
        execute([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)], log)
        contents = log.read_text()
        counts = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', contents)
        if not counts or int(counts[2]) or 'Equivalence successfully proven' not in contents:
            raise RuntimeError('互连完整状态证明未完成')
        report['formal'].append({'parameters': parameters, 'passed': True,
                                'equivalent_bits': int(counts[1]), 'log_sha256': digest(log)})
        print(f'formal {index} PASS', flush=True)
    for overlap in (0, 1):
        for synthesis in (False, True):
            name = f'four_state_o{overlap}_s{int(synthesis)}'
            command = [sys.executable, str(ROOT/'test/soc_interconnect_depth/check_four_state.py'),
                       '--reference-ref', revision, '--write-overlap', str(overlap), '--out', str(out/name)]
            if synthesis:
                command.append('--synthesis')
            if args.predecoded:
                command.append('--predecoded')
            execute(command, out/(name+'.log'))
            report['four_state'].append(json.loads((out/name/'summary.json').read_text()))
            print(name+' PASS', flush=True)
    execute([sys.executable, str(ROOT/'test/soc_interconnect_writes/run.py'),
             '--out', str(out/'transactions'), '--verilator', args.verilator], out/'transactions.log')
    report['transactions'] = json.loads((out/'transactions/summary.json').read_text())
    if digest(ROOT/SOURCE) != source_hash or hashes != {name: digest(path) for name, path in snapshots.items()}:
        raise RuntimeError('验证期间源文件发生变化')
    report['passed'] = True
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'passed': True, 'formal_profiles': len(report['formal']),
                      'four_state_cycles': sum(item['cycles'] for item in report['four_state']),
                      'transaction_profiles': len(report['transactions']['profiles'])}), flush=True)


if __name__ == '__main__':
    main()
