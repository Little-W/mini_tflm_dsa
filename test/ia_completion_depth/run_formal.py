#!/usr/bin/env python3
"""证明装载完成事件选择结构保持完整 IA 控制状态、存储内容及公开输出。"""
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
CTRL = Path('rtl/npu/loaders/ia_loader_ctrl.sv')
LOADER = Path('rtl/npu/loaders/ia_loader.sv')
PROFILES = {
    'ctrl3': ('ia_loader_ctrl', dict(SIZE=3, BUS_WIDTH=32, CACHE_BLOCKS=4)),
    'ctrl16': ('ia_loader_ctrl', dict(SIZE=16, BUS_WIDTH=64, CACHE_BLOCKS=32)),
    'ctrl32': ('ia_loader_ctrl', dict(SIZE=32, BUS_WIDTH=64, CACHE_BLOCKS=32)),
    'production': ('ia_loader', dict(SIZE=16, BUS_WIDTH=64, CACHE_BLOCKS=32,
        COUNT_WIDTH=29, COMPACT_S8=0, ORDERED_JOB=1, RAM_WORD_ADDR_WIDTH=12,
        p_dma_source_layout=1, p_shared_write_stage=1, p_register_dma_request=1)),
    'compact': ('ia_loader', dict(SIZE=16, BUS_WIDTH=64, CACHE_BLOCKS=32,
        COUNT_WIDTH=29, COMPACT_S8=1, ORDERED_JOB=1, RAM_WORD_ADDR_WIDTH=12,
        p_dma_source_layout=1, p_shared_write_stage=1, p_register_dma_request=1)),
    'generic': ('ia_loader', dict(SIZE=16, BUS_WIDTH=32, CACHE_BLOCKS=4,
        COUNT_WIDTH=8, ORDERED_JOB=0)),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='324eba48')
    parser.add_argument('--profiles', nargs='+', choices=tuple(PROFILES), default=list(PROFILES))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(['git', 'show', args.reference+':'+str(CTRL)], cwd=ROOT, text=True)
    current = (ROOT/CTRL).read_text()
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    dependencies = resolve([ROOT/LOADER], ROOT)
    variants = {}
    for label, source in [('reference', original), ('current', current)]:
        # 阻塞赋值临时变量在实际接收的状态寄存器处比较。
        for name in ('send_group_ready_nxt', 'in_l1_output_nxt'):
            source = re.sub(r'\b'+name+r'\b', label+'_'+name, source)
        snapshot = out/(label+'.sv'); snapshot.write_text(source)
        variants[label] = [snapshot if path == ROOT/CTRL else path for path in dependencies]
    records = []
    for name in args.profiles:
        top, parameters = PROFILES[name]
        options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] + [f'-G{key}={value}' for key, value in parameters.items()]
        commands = []
        for label in ('reference', 'current'):
            commands += ['read_slang --top '+top+' '+shlex.join(options+list(map(str, variants[label]))),
                'prep -top '+top+' -flatten', 'memory_map', 'async2sync', 'opt_clean',
                'rename '+top+' '+label, 'design -stash '+label]
        commands += ['design -copy-from reference -as reference reference',
            'design -copy-from current -as current current', 'equiv_make reference current equivalent',
            'hierarchy -top equivalent', 'equiv_simple -seq 1', 'opt_clean',
            'equiv_induct -seq 3', 'equiv_status -assert']
        script, log = out/(name+'.ys'), out/(name+'.log')
        script.write_text('\n'.join(commands)+'\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script],
                cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=300)
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', log.read_text())
        assert match and int(match[2]) == 0
        records.append({'profile': name, 'top': top, 'parameters': parameters, 'passed': True,
            'equivalent_bits': int(match[1]), 'log_sha256': digest(log)})
        print('IA_COMPLETION_FORMAL_PASS', name, flush=True)
    assert current == (ROOT/CTRL).read_text()
    report = {'passed': True, 'reference_revision': args.reference, 'inputs_constrained': False,
        'source_sha256': {str(path.relative_to(ROOT)): digest(path) for path in dependencies},
        'profiles': records}
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
