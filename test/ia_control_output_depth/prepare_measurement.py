#!/usr/bin/env python3
"""保存 IA 历史参考与当前实现，使用相同共享存储参数进行模块比较。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source_group, read_current_source, shared_ia_parameters
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
    parser.add_argument('--reference', default='7ff66a59')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    sources = [LOADER, CACHE, *DEPENDENCIES] + [path.relative_to(root) for path in
        sorted((root / 'rtl/common').rglob('*')) if path.suffix in ('.sv', '.v')]
    for label in ('reference', 'current'):
        for name in sources:
            destination = out / label / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if label == 'reference' and name in (LOADER, CACHE, *DEPENDENCIES):
                destination.write_bytes(read_rtl_source_group(f'{args.reference}:{name}', cwd=ROOT))
            else:
                destination.write_text(read_current_source(root / name))
    cases = {}
    for label in ('reference', 'current'):
        for top in ('ia_loader', 'ia_loader_cache_mgr'):
            parameters = dict(DATA_WIDTH=16, SIZE=16, BUS_WIDTH=64, REG_WIDTH=32,
                CACHE_BLOCKS=32, COMPACT_S8=1, RAM_WORD_ADDR_WIDTH=12,
                p_dma_source_layout=1, p_shared_write_stage=1)
            names = [CACHE, DEPENDENCIES[1]]
            if top == 'ia_loader':
                parameters.update(COUNT_WIDTH=29, ORDERED_JOB=1, PS_FRAME_COUNT=16)
                names += [LOADER, DEPENDENCIES[0]]
            else:
                parameters.update(p_compact_offset_width=9)
            module_source = LOADER if top == 'ia_loader' else CACHE
            parameters = shared_ia_parameters(parameters, (out / label / module_source).read_text())
            cases[top + '_' + label] = dict(top=top,
                sources=[str(out / label / name) for name in names], parameters=parameters,
                options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] +
                    [f'-G{name}={value}' for name, value in parameters.items()],
                configuration='完整共享 IA 模块，历史与当前版本使用相同公开参数')
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    manifest = dict(source_sha256={label: {str(name): digest(out / label / name)
        for name in sources} for label in ('reference', 'current')},
        reference=args.reference,
        runner_sha256=digest(Path(__file__).resolve()))
    (out / 'inputs.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({label: manifest['source_sha256'][label][str(LOADER)]
                      for label in ('reference', 'current')}))


if __name__ == '__main__':
    main()
