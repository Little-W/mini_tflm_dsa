#!/usr/bin/env python3
"""保存预取模块与完整生产前端的两侧RTL及显式综合参数。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PREFETCH = 'rtl/npu/conv/conv_im2col_prefetch.sv'
FRONTEND = 'rtl/npu/conv/conv_im2col_frontend.sv'
FRONTEND_SEEDS = ['rtl/npu/conv/conv_im2col_pkg.sv', 'rtl/npu/dma/cache/conv_sdp_ram.sv',
                  'rtl/npu/dma/cache/conv_next_use_predictor.sv', 'rtl/npu/conv/conv_axi_span_reader.sv',
                  'rtl/npu/dma/cache/conv_read_cache.sv', FRONTEND]
PREFETCH_PARAMETERS = dict(p_size=16, p_line_bytes=128, p_register_cache_request=1, p_rw=5)
FRONTEND_PARAMETERS = dict(SIZE=16, SLOT_W=5, LANES=8, CACHE_SETS=16, CACHE_WAYS=2,
                          LINE_BYTES=128, BUS_WIDTH=64, DMA_MAX_BYTES=2048, CACHE_POLICY=3,
                          REGISTER_DESCRIPTOR=0, REGISTER_ROW_ADDRESS=0,
                          REGISTER_CACHE_REQUEST=1, CACHE_RESPONSE_DEPTH=1)
FRONTEND_OPTIONS = ['-D', 'GEMMORA_PS_POOL_BYTES=49152', '-D', 'GEMPACT_PS_COMPRESS=1',
                    '-D', 'GEMMORA_PS_FORCE_RAW=1', '-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1']


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--frontend-reference', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', args.reference+'^{commit}'],
                                      cwd=ROOT, text=True).strip()
    api = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
    common = sorted(path for path in (source/'rtl/common').rglob('*') if path.suffix in ('.v', '.sv'))
    sources = api['with_dependencies']([source/name for name in FRONTEND_SEEDS]+common, source)
    prefetch_sources = api['with_dependencies']([source/'rtl/npu/conv/conv_im2col_pkg.sv', source/PREFETCH], source)
    dependencies = api['input_files'](sources, source)
    hashes = {label: {} for label in ('reference', 'current')}
    for path in dependencies:
        relative = str(path.relative_to(source))
        data = dict(reference=subprocess.check_output(['git', 'show', revision+':'+relative], cwd=ROOT),
                    current=path.read_bytes())
        for label, content in data.items():
            target = out/'sources'/label/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if target.read_bytes() != content:
                    raise RuntimeError('已保存的测量源码内容不同：'+str(target))
            else:
                target.write_bytes(content)
            hashes[label][relative] = digest(content)
    cases = dict(
        prefetch=dict(top='conv_im2col_prefetch', parameters=PREFETCH_PARAMETERS,
                      options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1']+
                          [f'-G{name}={value}' for name, value in PREFETCH_PARAMETERS.items()],
                      sources=[str(path.relative_to(source)) for path in prefetch_sources],
                      configuration='完整生产预取模块，公开输入与输出全部保留'),
        frontend=dict(top='conv_im2col_frontend', parameters=FRONTEND_PARAMETERS,
                      options=FRONTEND_OPTIONS+
                          [f'-G{name}={value}' for name, value in FRONTEND_PARAMETERS.items()],
                      sources=FRONTEND_SEEDS,
                      configuration='完整生产卷积前端，CACHE_SETS16、LINE_BYTES128、LANES8'))
    comparison = None
    if args.frontend_reference:
        manifest = json.loads((args.frontend_reference/'manifest.json').read_text())
        if manifest['sources_sha256'] != hashes['reference']:
            raise RuntimeError('完整前端参考测量的RTL与当前参考提交不同')
        if manifest['options'] != cases['frontend']['options']:
            raise RuntimeError('完整前端参考测量的显式参数不同')
        differences = [name for name in hashes['reference']
                       if hashes['reference'][name] != hashes['current'][name]]
        if differences != [PREFETCH]:
            raise RuntimeError('完整前端包含预取模块以外的源码变化：'+str(differences))
        comparison = dict(passed=True, reference=str(args.frontend_reference.resolve()),
                          dependency_count=len(hashes['reference']), changed_files=differences)
    report = dict(reference_commit=revision, source_sha256=hashes,
                  frontend_reference_comparison=comparison)
    (out/'all_cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    (out/'inputs.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(dependency_count=len(hashes['reference']),
                         frontend_reference_comparison=comparison), ensure_ascii=False))


if __name__ == '__main__':
    main()
