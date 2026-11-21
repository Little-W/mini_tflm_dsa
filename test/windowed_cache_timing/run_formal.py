#!/usr/bin/env python3
"""逐周期证明窗口缓存的存储状态、控制状态和全部有效消费者输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
RTL = [Path(name) for name in (
    'rtl/npu/dma/cache/conv_read_cache.sv',
    'rtl/npu/dma/cache/conv_sdp_ram.sv',
    'rtl/npu/conv/conv_axi_span_reader.sv',
    'rtl/common/add3_equal.sv', 'rtl/common/add_equal.sv',
    'rtl/common/onehot_check.sv', 'rtl/common/parallel_prefix_add.sv',
    'rtl/common/pseudo_dual_port_ram.v', 'rtl/common/regfile.v',
    'rtl/common/single_port_ram.v', 'rtl/common/unsigned_compare.sv',
)]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--reference-ref', default='0097b66ed57e1b8ef00e402e89dc5b274f1626be')
    parser.add_argument('--profiles', nargs='+', default=[
        '2:2:16:2:32:32:0', '16:2:128:1:64:64:1',
        '16:2:128:2:64:64:1', '4:1:32:4:64:32:0',
    ], help='SETS:WAYS:LINE_BYTES:DEMAND_DEPTH:BUS_WIDTH:READ_WIDTH:p_defer_retire_shift')
    parser.add_argument('--seq', type=int, default=4)
    parser.add_argument('--out', type=Path, default=ROOT/'build/windowed_cache_timing/formal')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original_hashes, source_hashes, sources = {}, {}, {}
    for label in ('reference', 'current'):
        sources[label] = []
        for relative in RTL:
            if label == 'reference' and args.reference_root is None:
                data = subprocess.check_output(
                    ['git', 'show', f'{args.reference_ref}:{relative}'], cwd=ROOT)
            else:
                root = args.source_root if label == 'current' else args.reference_root
                original = root.resolve()/relative
                data = original.read_bytes()
                original_hashes[str(original)] = hashlib.sha256(data).hexdigest()
            copied = out/'inputs'/label/relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            copied.write_bytes(data)
            source_hashes[f'{label}/{relative}'] = digest(copied)
            sources[label].append(copied)
    records = []
    names = ['SETS', 'WAYS', 'LINE_BYTES', 'DEMAND_DEPTH', 'BUS_WIDTH',
             'READ_WIDTH', 'p_defer_retire_shift']
    for profile in args.profiles:
        values = list(map(int, profile.split(':')))
        if len(values) != len(names):
            raise ValueError(f'需要七个参数：{profile}')
        parameters = dict(zip(names, values))
        commands = []
        for label in ('reference', 'current'):
            flags = ' '.join(f'-G{name}={value}' for name, value in parameters.items())
            commands += [
                f'read_slang -D SYNTHESIS=1 -D XILINX_FPGA=1 --top conv_read_cache {flags} ' +
                shlex.join(map(str, sources[label])),
                'prep -top conv_read_cache -flatten', 'memory_map', 'async2sync', 'opt_clean',
                # 有效位原始读端口随同步边沿调整，检查捕获值和全部实际消费者。
                'rename -hide w:*.valid_o_rd_data w:*.u_valid.o_rd_data '
                'w:*.valid_i_rd_addr w:*.u_valid.i_rd_addr',
                f'rename conv_read_cache {label}', f'design -stash {label}',
            ]
        commands += [
            'design -copy-from reference -as reference reference',
            'design -copy-from current -as current current',
            'equiv_make reference current equivalent', 'hierarchy -top equivalent',
            'equiv_simple -seq 1', 'opt_clean', f'equiv_induct -seq {args.seq}',
            'equiv_status -assert',
        ]
        stem = profile.replace(':', '_')
        script, log = out/(stem+'.ys'), out/(stem+'.log')
        script.write_text('\n'.join(commands)+'\n')
        with log.open('w') as stream:
            result = subprocess.run([
                sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                '--worker', str(script)], cwd=ROOT, stdout=stream,
                stderr=subprocess.STDOUT, timeout=600)
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', log.read_text())
        if result.returncode or match is None or int(match[2]) != 0:
            raise RuntimeError(f'完整状态证明未通过：{log}')
        record = {'parameters': parameters, 'passed': True,
                  'equivalent_bits': int(match[1]), 'unproven_bits': int(match[2]),
                  'script_sha256': digest(script), 'log_sha256': digest(log)}
        records.append(record)
        print(json.dumps(record), flush=True)
    if original_hashes != {name: digest(Path(name)) for name in original_hashes}:
        raise RuntimeError('验证期间源文件发生变化')
    report = {'passed': True, 'reference_ref': args.reference_ref if args.reference_root is None else None,
              'inputs_constrained': False, 'state_and_consumers_every_cycle': True,
              'source_sha256': source_hashes, 'profiles': records,
              'equivalent_bits': sum(row['equivalent_bits'] for row in records)}
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
