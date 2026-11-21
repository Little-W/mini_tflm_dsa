#!/usr/bin/env python3
"""保存 IA 完整模块输入，并构造采用相同外围逻辑的参考实现。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
LOADER = Path('rtl/npu/loaders/ia_loader.sv')
CACHE = Path('rtl/npu/loaders/ia_loader_cache_mgr.sv')
DEPENDENCIES = [Path('rtl/npu/loaders/ia_loader_ctrl.sv'),
                Path('rtl/npu/compute/select_add.sv')]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    sources = [LOADER, CACHE, *DEPENDENCIES] + [path.relative_to(root) for path in
        sorted((root / 'rtl/common').rglob('*')) if path.suffix in ('.sv', '.v')]
    for label in ('reference', 'current'):
        for name in sources:
            destination = out / label / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, destination)
    loader = (out / 'reference' / LOADER).read_text()
    for name in ('request_tag_match', 'request_p0_equal_o_equal', 'request_q0_equal_o_equal'):
        declaration = '(* keep = 1 *) logic ' + name + ';'
        if loader.count(declaration) != 1:
            raise RuntimeError('无法确定独立比较边界：' + name)
        loader = loader.replace(declaration, 'logic ' + name + ';')
    (out / 'reference' / LOADER).write_text(loader)
    cache = (out / 'reference' / CACHE).read_text()
    start = cache.index('    if (p_shared_write_stage && SIZE == 16 && DATA_WIDTH == 16) begin : g_shared_write_stage')
    end = cache.index('    end else begin : g_general_write_stage', start)
    cache = cache[:start] + (HERE / 'reference_shared_stage.sv').read_text() + cache[end:]
    (out / 'reference' / CACHE).write_text(cache)
    cases = {}
    for label in ('reference', 'current'):
        for top in ('ia_loader', 'ia_loader_cache_mgr'):
            parameters = dict(DATA_WIDTH=16, SIZE=16, BUS_WIDTH=64, REG_WIDTH=32,
                CACHE_BLOCKS=32, COMPACT_S8=1, EXTERNAL_RAM=1, RAM_WORD_ADDR_WIDTH=12,
                p_dma_source_layout=1, p_shared_write_stage=1)
            names = [CACHE, DEPENDENCIES[1]]
            if top == 'ia_loader':
                parameters.update(COUNT_WIDTH=29, ORDERED_JOB=1, PS_FRAME_COUNT=16)
                names += [LOADER, DEPENDENCIES[0]]
            else:
                parameters.update(p_compact_offset_width=9)
            cases[top + '_' + label] = dict(top=top,
                sources=[str(out / label / name) for name in names], parameters=parameters,
                options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] +
                    [f'-G{name}={value}' for name, value in parameters.items()],
                configuration='完整 IA 生产参数，保留公开寄存边界')
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    manifest = dict(source_sha256={label: {str(name): digest(out / label / name)
        for name in sources} for label in ('reference', 'current')},
        reference_fragment_sha256=digest(HERE / 'reference_shared_stage.sv'),
        runner_sha256=digest(Path(__file__).resolve()))
    (out / 'inputs.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({label: manifest['source_sha256'][label][str(LOADER)]
                      for label in ('reference', 'current')}))


if __name__ == '__main__':
    main()
