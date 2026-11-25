#!/usr/bin/env python3
"""验证状态模块采用直接连接表示完成 FPGA 映射后的完整时序等价性。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from map_abc9_batches import LIBRARIES, discover_profile
from open_fpga_synth import run_stage


def digest(path):
    """记录本次检查使用的源码与映射文件摘要。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ports(module):
    """只比较模块接口的方向和完整位宽。"""
    return {name: (value['direction'], len(value['bits']))
            for name, value in module['ports'].items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/direct_connection_test')
    args = parser.parse_args()
    source_root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [source_root / 'rtl/npu/conv/vector_softmax_accumulator.sv',
               source_root / 'rtl/common/parallel_prefix_add.sv']
    files = sources + [Path(__file__).resolve(), ROOT / 'scripts/fpga/map_abc9_batches.py']
    hashes = {str(path): digest(path) for path in files}
    environment = dict(os.environ)
    import pyosys
    environment['PATH'] = str(Path(pyosys.__file__).parent) + os.pathsep + environment.get('PATH', '')
    (out / 'profile').mkdir(exist_ok=True)
    profile = discover_profile(out / 'profile', environment)
    top = 'vector_softmax_accumulator'
    read_source = 'read_slang --top ' + top + ' -DSYNTHESIS -DFPGA ' + ' '.join(map(str, sources))
    report = {'passed': False, 'source_sha256': hashes, 'top': top,
              'profile': profile, 'stages': []}

    def stage(name, commands):
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text('\n'.join(commands) + '\n')
        measurement = run_stage(script, log, environment)
        report['stages'].append({'name': name, 'passed': True, **measurement,
                                 'script_sha256': digest(script), 'log_sha256': digest(log)})
        print('DIRECT_CONNECTION_STAGE_PASS', name, flush=True)
        return log.read_text()

    stage('prepare', [read_source,
          f'synth_xilinx -top {top} -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts',
          'bufnorm -conn', 'check -assert', 'write_rtlil ' + str(out / 'pre_lut.il')])
    stage('map', ['read_rtlil ' + str(out / 'pre_lut.il'), *LIBRARIES,
          'bufnorm -conn', 'check -assert', *profile['prefix'],
          'bufnorm -conn', 'check -assert', profile['abc9'],
          'bufnorm -conn', 'check -assert', *profile['suffix'],
          'bufnorm -conn', 'check -assert', 'blackbox =A:whitebox',
          'write_json ' + str(out / 'mapped.json'),
          'write_rtlil ' + str(out / 'mapped.il')])
    mapped = json.loads((out / 'mapped.json').read_text())['modules'][top]
    remaining = sorted({cell['type'] for cell in mapped['cells'].values()
                        if cell['type'].startswith('$')})
    if remaining:
        raise RuntimeError('映射后仍存在通用逻辑单元：' + repr(remaining))
    # 原语模型完整展开后，比较全部输出，检查同步清零、复位、使能和保持行为。
    formal = stage('equivalence', [read_source,
          'setattr -mod -unset keep_hierarchy', f'prep -top {top} -flatten',
          'async2sync', 'opt -full', 'write_json ' + str(out / 'reference.json'),
          'rename -hide w:*', 'rename -top reference', 'design -stash reference',
          'read_rtlil ' + str(out / 'mapped.il'), 'delete =A:blackbox',
          'read_verilog -overwrite +/xilinx/cells_sim.v', f'rename {top} current',
          'setattr -mod -unset keep_hierarchy', 'hierarchy -top current',
          'flatten -wb', 'proc', 'memory_map', 'async2sync', 'opt -full',
          'rename -hide w:*', 'design -stash current',
          'design -copy-from reference -as reference reference',
          'design -copy-from current -as current current',
          'equiv_make reference current proof', 'hierarchy -top proof',
          'equiv_simple -seq 3', 'opt_clean', 'equiv_induct -seq 5', 'equiv_status -assert'])
    original = json.loads((out / 'reference.json').read_text())['modules'][top]
    if ports(original) != ports(mapped):
        raise RuntimeError('映射后的公开接口发生变化')
    proven = re.search(r'Of those cells (\d+) are proven and 0 are unproven', formal)
    output_bits = sum(len(port['bits']) for port in original['ports'].values()
                      if port['direction'] == 'output')
    if not proven or int(proven[1]) != output_bits:
        raise RuntimeError('未完成全部公开输出的时序等价检查')
    if hashes != {str(path): digest(path) for path in files}:
        raise RuntimeError('检查期间源码发生变化')
    report.update(passed=True, compared_output_bits=output_bits,
                  unmapped_internal_logic_cells=0,
                  mapped_sha256=digest(out / 'mapped.json'))
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'DIRECT_CONNECTION_TEST_PASS output_bits={output_bits}', flush=True)


if __name__ == '__main__':
    main()
