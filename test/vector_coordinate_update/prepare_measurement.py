#!/usr/bin/env python3
"""固定完整向量引擎及依赖，以当前 SoC 参数生成前后综合配置。"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PARAMETERS = dict(TILE=16, BUS_WIDTH=64, DMA_SIZE=64, PE_COUNT=8, WINDOW_LANES=8,
                  SHARED_STORAGE_ENABLE=1, SHARED_STORAGE_ADDR_WIDTH=12,
                  SHARED_QUANT_ENABLE=0, MAX_TAPS=49, POOL_MAX_TAPS=256)
DEFINES = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', '-DGEMPACT_PS_COMPRESS=1',
           '-DGEMMORA_PS_POOL_BYTES=49152', '-DGEMMORA_PS_FORCE_RAW=1']


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='35408bcf')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', args.reference + '^{commit}'],
                                       cwd=ROOT, text=True).strip()
    archive = subprocess.check_output(['git', 'archive', revision, 'rtl'], cwd=ROOT)
    resolve = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    cases, hashes = {}, {}
    with tempfile.TemporaryDirectory() as temporary:
        original = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:') as source:
            source.extractall(original, filter='data')
        for label, root in (('reference', original), ('current', ROOT)):
            initial = [root / 'rtl/npu/conv' / name for name in
                       ('conv_im2col_pkg.sv', 'vector_engine_pkg.sv',
                        'vector_engine_control_pkg.sv', 'vector_engine.sv')]
            initial += sorted((root / 'rtl/common').rglob('*.sv'))
            initial += sorted((root / 'rtl/common').rglob('*.v'))
            files, hashes[label] = [], {}
            for path in resolve(initial, root):
                relative = path.relative_to(root)
                target = out / label / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                data = path.read_bytes()
                target.write_bytes(data)
                files.append(str(relative))
                hashes[label][str(relative)] = hashlib.sha256(data).hexdigest()
            cases['vector_' + label] = dict(
                top='vector_engine', sources=files, parameters=PARAMETERS,
                options=DEFINES + [f'-G{name}={value}' for name, value in PARAMETERS.items()],
                configuration='Production vector parameters; full public interface active',
            )
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    (out / 'source_sha256.json').write_text(json.dumps(
        dict(reference_commit=revision, sources=hashes), indent=2) + '\n')


if __name__ == '__main__':
    main()
