#!/usr/bin/env python3
"""比较缓存存储推断与数据保存结构的完整模块状态和公开输出。"""
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
SOURCES = ('rtl/npu/dma/cache/conv_read_cache.sv',
           'rtl/npu/dma/cache/conv_sdp_ram.sv',
           'rtl/npu/conv/conv_axi_span_reader.sv')
CASES = {
    'production': {'SETS': 16, 'WAYS': 2, 'LINE_BYTES': 128, 'BUS_WIDTH': 64,
                   'READ_WIDTH': 64, 'DEMAND_DEPTH': 2, 'p_defer_retire_shift': 1},
    'production_asic': {'SETS': 16, 'WAYS': 2, 'LINE_BYTES': 128, 'BUS_WIDTH': 64,
                        'READ_WIDTH': 128, 'DEMAND_DEPTH': 2, 'p_defer_retire_shift': 1},
    'direct': {'SETS': 8, 'WAYS': 2, 'LINE_BYTES': 16, 'BUS_WIDTH': 32,
               'READ_WIDTH': 32, 'DEMAND_DEPTH': 1},
    'single_way': {'SETS': 8, 'WAYS': 1, 'LINE_BYTES': 16, 'BUS_WIDTH': 64,
                   'READ_WIDTH': 32, 'DEMAND_DEPTH': 4},
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', choices=tuple(CASES), default=['production'])
    parser.add_argument('--asic', action='store_true')
    parser.add_argument('--observe-prefetch-keys', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    snapshots, hashes = {}, {}
    with_dependencies = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    for label, root in (('reference', args.reference_root.resolve()),
                        ('current', args.source_root.resolve())):
        files = [root / relative for relative in SOURCES]
        files += sorted(path for path in (root / 'rtl/common').iterdir()
                        if path.suffix in ('.v', '.sv'))
        files = with_dependencies(files, root)
        snapshots[label], hashes[label] = [], {}
        for source in files:
            relative = source.relative_to(root)
            target = out / label / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            if args.observe_prefetch_keys and re.search(r'\bmodule\s+conv_windowed_cache\b', source.read_text()):
                text = source.read_text()
                shared = 'logic [63:0] prefetch_key_entries [PF_DEPTH];' in text
                keys_memory = 'prefetch_key_entries' if shared else 'u_prefetch_keys.mem'
                selected_memory = 'prefetch_key_entries' if shared else 'u_prefetch_selected.mem'
                observation = f'''
  // 全部物理槽位与活动项副本同时参与状态比较。
  (* keep *) wire [PF_DEPTH-1:0][63:0] observed_prefetch_key_state;
  (* keep *) wire [PF_DEPTH-1:0][63:0] observed_prefetch_selected_state;
  for(genvar observed_slot=0;observed_slot<PF_DEPTH;observed_slot++) begin:g_prefetch_state
    assign observed_prefetch_key_state[observed_slot]={keys_memory}[observed_slot];
    assign observed_prefetch_selected_state[observed_slot]={selected_memory}[observed_slot];
  end
'''
                end = text.index('endmodule', text.index('module conv_windowed_cache'))
                target.write_text(text[:end] + observation + text[end:])
            snapshots[label].append(target)
            hashes[label][str(relative)] = digest(source)
    result = {'passed': True, 'external_inputs_constrained': False,
              'compared': 'all public outputs and common internal state',
              'source_sha256': hashes, 'asic': args.asic,
              'complete_prefetch_storage_observed': args.observe_prefetch_keys, 'profiles': []}
    for name in args.cases:
        options = ['-DSYNTHESIS=1', '-DASIC_SYNTHESIS=1' if args.asic else '-DXILINX_FPGA=1'] + [
            f'-G{key}={value}' for key, value in CASES[name].items()]
        commands = []
        for label in ('reference', 'current'):
            source_text = '\n'.join(path.read_text() for path in snapshots[label])
            synchronous_tags = ('.p_sync_read(DEMAND_DEPTH > 1)' in source_text and
                                CASES[name]['DEMAND_DEPTH'] > 1)
            commands += [
                'read_slang --top conv_windowed_cache ' +
                shlex.join(options + [str(path) for path in snapshots[label]]),
                'prep -top conv_windowed_cache -flatten',
                'memory_map', 'async2sync',
                ('submod -hidden -name prefetch_storage c:*prefetch_keys* '
                 'c:*prefetch_selected* c:*prefetch_key_entries*\n'
                 'opt -full *prefetch_storage\nflatten\nopt_clean')
                if args.observe_prefetch_keys else 'opt_clean',
            ]
            # 同步端口名称标明其寄存语义；标签存储内容和缓存侧同步输出保持同名比较。
            if synchronous_tags:
                commands.append('cd conv_windowed_cache')
                for way in range(CASES[name]['WAYS']):
                    port = f'g_metadata_way[{way}].u_tags.o_rd_data'
                    commands.append('rename \\' + port + ' \\' + port + '_registered')
                commands.append('cd ..')
            commands += ['rename conv_windowed_cache ' + label, 'design -stash ' + label]
        commands += [
            'design -copy-from reference -as reference reference',
            'design -copy-from current -as current current',
            'equiv_make reference current comparison', 'hierarchy -top comparison',
            'equiv_simple -short -seq 1',
        ]
        if args.observe_prefetch_keys:
            # 已证明的公共状态使两侧写入逻辑相同，归并后继续证明动态读取端口。
            commands += ['opt -full', 'equiv_simple -short -seq 1']
        commands += ['opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert']
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            completed = subprocess.run([
                sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                '--worker', str(script)], cwd=ROOT, stdout=stream,
                stderr=subprocess.STDOUT, timeout=600)
        text = log.read_text()
        passed = completed.returncode == 0 and 'Equivalence successfully proven' in text
        count = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        row = {'name': name, 'passed': passed, 'parameters': CASES[name],
               'equivalent_bits': int(count[1]) if count else None,
               'log_sha256': digest(log)}
        result['profiles'].append(row)
        result['passed'] &= passed
        (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(row), flush=True)
        if not passed:
            raise RuntimeError('完整缓存等价证明未完成: ' + str(log))


if __name__ == '__main__':
    main()
