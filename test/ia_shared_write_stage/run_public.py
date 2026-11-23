#!/usr/bin/env python3
"""比较启用共享写数据寄存后的完整 IA 原有公开接口和状态。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from helpers import ROOT
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_current_source, read_rtl_source_group as read_rtl_source, shared_ia_options
sys.path.insert(0, str(ROOT / 'test/ia_write_output_depth'))
from primitives import prepare_models


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='7ff66a59')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relatives = ['rtl/npu/loaders/' + name + '.sv' for name in
                 ('ia_loader', 'ia_loader_ctrl', 'ia_loader_cache_mgr')]
    relatives.append('rtl/npu/compute/select_add.sv')
    common = sorted(path for path in (ROOT / 'rtl/common').glob('*') if path.suffix in ('.sv', '.v'))
    hashes = {relative: digest(ROOT / relative) for relative in relatives}
    model, model_info = prepare_models(out, names=('DSP48E1',))
    commands = []
    for label in ('reference', 'current'):
        folder = out / label
        folder.mkdir(exist_ok=True)
        sources = []
        for relative in relatives:
            data = (read_rtl_source(args.reference + ':' + relative, cwd=ROOT)
                    if label == 'reference' else read_current_source(ROOT / relative).encode())
            path = folder / Path(relative).name
            path.write_bytes(data)
            sources.append(path)
        options = ('-DYOSYS=1 -DVERIFIC=1 -DXILINX_FPGA=1 -GSIZE=16 -GBUS_WIDTH=64 '
                   '-GCOUNT_WIDTH=29 -GCACHE_BLOCKS=32 -GORDERED_JOB=1 '
                   '-GRAM_WORD_ADDR_WIDTH=12 -GPS_FRAME_COUNT=16')
        if label == 'current':
            options += ' -Gp_shared_write_stage=1'
        options = shlex.join(shared_ia_options(shlex.split(options), sources[0].read_text()))
        commands += ['read_slang --top ia_loader ' + options + ' ' +
                     ' '.join(shlex.quote(str(p)) for p in sources + common + [model]),
                     'prep -top ia_loader -flatten',
                     'delete -output ia_loader/ram_shared_wr_data', 'opt_clean -purge',
                     'memory_map', 'async2sync', 'opt_clean -purge',
                     'rename ia_loader ' + label, 'design -stash ' + label]
    commands += ['design -copy-from reference -as reference reference',
                 'design -copy-from current -as current current',
                 'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                 'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert']
    script, log = out / 'public.ys', out / 'public.log'
    script.write_text('\n'.join(commands) + '\n')
    with log.open('w') as stream:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(script)], cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=600)
    text = log.read_text()
    count = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
    if result.returncode or 'Equivalence successfully proven' not in text:
        raise RuntimeError('Public interface proof did not complete: ' + str(log))
    if hashes != {relative: digest(ROOT / relative) for relative in relatives}:
        raise RuntimeError('Sources changed during verification')
    report = dict(passed=True, reference=args.reference, input_constraints=False,
                  current_shared_write_stage=True, equivalent_bits=int(count[1]),
                  source_sha256=hashes, primitive_models=model_info, log_sha256=digest(log),
                  comparison_scope='Existing public outputs and state; shared write output has independent induction proof')
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
