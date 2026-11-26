#!/usr/bin/env python3
"""保存共享存储布局选择的完整参考与当前综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/buffers/ia_ps_channel_ram.sv')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='324eba48')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    texts = {'reference': subprocess.check_output(['git', 'show', args.reference+':'+str(SOURCE)], cwd=ROOT),
             'current': (ROOT/SOURCE).read_bytes()}
    parameters = dict(p_bank_bytes=8192, p_total_bytes=57344, p_shared_write_stage=1,
                      p_ia_nonempty_writes=1, p_paired_ia_ports=1)
    cases, hashes = {}, {}
    for label, data in texts.items():
        path = out/(label+'.sv'); path.write_bytes(data)
        sources = resolve([path], ROOT)
        for source in sources:
            hashes[str(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
        cases[label] = dict(top='ia_ps_channel_ram', sources=list(map(str, sources)),
            options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] +
                    [f'-G{key}={value}' for key, value in parameters.items()],
            parameters=parameters, configuration='完整共享存储与全部 IA/PS 独立端口')
    (out/'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    (out/'manifest.json').write_text(json.dumps({'reference_revision': args.reference,
        'source_sha256': hashes}, indent=2)+'\n')


if __name__ == '__main__':
    main()
