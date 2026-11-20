#!/usr/bin/env python3
"""证明缓存使用已保存的读取组号及并行标签比较时的完整状态与输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/cache/conv_read_cache.sv')
COMMON = ('rtl/npu/dma/cache/conv_sdp_ram.sv', 'rtl/npu/conv/conv_axi_span_reader.sv',
          'rtl/common/regfile.v')
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source

OLD_COMPARE = 'lookup_ready && valid_lookup[w] && lookup_tag[w]==lookup_addr[31:LB]'
NEW_COMPARE = '''lookup_ready && valid_lookup[w] &&
          (fg_state==FG_MISS ? lookup_tag[w]==demand_addr[31:LB] :
                               lookup_tag[w]==work_request.address[31:LB])'''
OLD_ADDRESS = '    assign valid_i_rd_addr[0] = lookup_set;'
NEW_ADDRESS = '''    // 有效命中已要求请求组号与读取快照一致，存储选择使用已保存的组号。
    assign valid_i_rd_addr[0] = lookup_snapshot_set;'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default='9a6437f48722b3f53d4084b48c72cfb1d4b1fa5a')
    parser.add_argument('--cases', nargs='*')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(f'{args.reference_ref}:{SOURCE}', cwd=ROOT, text=True)
    if current.count(NEW_COMPARE) != 1 or current.count(NEW_ADDRESS) != 1:
        raise RuntimeError('Lookup implementation differs from the verified expressions')
    if current.replace(NEW_COMPARE, OLD_COMPARE).replace(NEW_ADDRESS, OLD_ADDRESS) != reference:
        raise RuntimeError('Changes outside the lookup selection require separate verification')
    snapshots = {}
    for label, text in [('reference', reference), ('current', current)]:
        snapshots[label] = out / (label + '.sv')
        snapshots[label].write_text(text)
    profiles = [
        ('sets2_way1_line8_bus32_demand1', 2, 1, 8, 32, 1, False),
        ('sets2_way2_line8_bus64_demand2', 2, 2, 8, 64, 2, False),
        ('sets8_way1_line16_bus32_demand4', 8, 1, 16, 32, 4, False),
        ('sets8_way2_line16_bus64_demand4', 8, 2, 16, 64, 4, False),
        ('sets2_way2_line32_bus32_demand4', 2, 2, 32, 32, 4, False),
        ('sets2_way2_line64_bus64_demand4', 2, 2, 64, 64, 4, False),
        ('sets2_way2_line128_bus32_demand4', 2, 2, 128, 32, 4, False),
        ('sets2_way2_line256_bus64_demand4', 2, 2, 256, 64, 4, False),
        ('sets128_way2_line16_bus64_demand4_fpga', 128, 2, 16, 64, 4, True),
        ('sets256_way1_line8_bus32_demand1_fpga', 256, 1, 8, 32, 1, True),
    ]
    hashes = {str(p): digest(ROOT / p) for p in (SOURCE, *map(Path, COMMON))}
    report = {'reference_ref': args.reference_ref, 'source_sha256': hashes,
              'reference_cache_sha256': hashlib.sha256(reference.encode()).hexdigest(),
              'unchanged_outside_lookup_selection': True, 'inputs_constrained': False,
              'scope': 'Every state element and public output; only changed internal read-port views are excluded from name matching',
              'runs': [], 'passed': False}
    for name, sets, ways, line, bus, demand, fpga in profiles:
        if args.cases and name not in args.cases:
            continue
        parameters = dict(SETS=sets, WAYS=ways, LINE_BYTES=line, BUS_WIDTH=bus, DEMAND_DEPTH=demand)
        options = ' '.join(f'-G{k}={v}' for k, v in parameters.items())
        if fpga:
            options += ' -DXILINX_FPGA=1'
        commands = []
        for label, source in snapshots.items():
            commands += [
                'read_slang --top conv_windowed_cache ' + options + ' ' +
                ' '.join(shlex.quote(str(p)) for p in [source, *(ROOT / p for p in COMMON)]),
                'prep -top conv_windowed_cache -flatten', 'memory_map', 'async2sync', 'opt_clean',
                # 存储内容仍按名称逐位比较，只排除两个读取地址不同的内部观察信号。
                'select -set valid_read_views w:g_metadata_way*.u_valid* w:g_metadata_way*.u_valid.mem* %d',
                'rename -hide @valid_read_views',
                'rename -hide w:valid_lookup w:g_metadata_way*.valid_i_rd_addr '
                'w:g_metadata_way*.valid_o_rd_data w:g_metadata_way*.valid_active',
                f'rename conv_windowed_cache {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                     'opt_merge', 'equiv_simple -short -seq 1', 'opt_clean',
                     'equiv_induct -seq 2', 'equiv_status -assert']
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=240)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        if not match or int(match[2]) or 'Equivalence successfully proven' not in text:
            raise RuntimeError('Complete cache equivalence not established')
        row = dict(case=name, parameters=parameters, xilinx=fpga, passed=True,
                   equivalent_bits=int(match[1]), log_sha256=digest(log))
        report['runs'].append(row)
        print(json.dumps(row), flush=True)
    if not report['runs'] or hashes != {str(p): digest(ROOT / p) for p in (SOURCE, *map(Path, COMMON))}:
        raise RuntimeError('Verification cases missing or sources changed')
    report['passed'] = True
    report['equivalent_bits'] = sum(row['equivalent_bits'] for row in report['runs'])
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
