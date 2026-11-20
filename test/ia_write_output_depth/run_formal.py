#!/usr/bin/env python3
"""证明 IA 缓存的全部公开输出、状态及写入保持行为。"""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/loaders/ia_loader_cache_mgr.sv')
from primitives import prepare_models


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cases():
    result = {'production': dict(SIZE=16, BUS_WIDTH=64, DATA_WIDTH=16,
        CACHE_BLOCKS=32, EXTERNAL_RAM=1, COMPACT_S8=1, REG_WIDTH=32,
        p_compact_offset_width=9, defines=['SYNTHESIS', 'XILINX_FPGA'])}
    for size, bus, data, blocks, external in (
            (4, 32, 8, 2, 0), (8, 64, 16, 4, 0), (16, 8, 16, 32, 1),
            (16, 32, 16, 32, 1), (16, 64, 16, 32, 1),
            (16, 128, 16, 32, 1), (16, 256, 16, 32, 1)):
        name = f'generic_s{size}_b{bus}_d{data}_c{blocks}_e{external}'
        result[name] = dict(SIZE=size, BUS_WIDTH=bus, DATA_WIDTH=data,
                            CACHE_BLOCKS=blocks, EXTERNAL_RAM=external, defines=[])
    for flags in itertools.product((False, True), repeat=3):
        names = ('XILINX_FPGA', 'SYNTHESIS', 'ASIC_SYNTHESIS')
        defines = [name for name, enabled in zip(names, flags) if enabled]
        name = '_'.join(defines).lower() if defines else 'generic_macros'
        result[name] = dict(SIZE=16, BUS_WIDTH=64, DATA_WIDTH=16,
                            CACHE_BLOCKS=32, EXTERNAL_RAM=1, defines=defines)
    for bus in (8, 32, 128, 256):
        result[f'fpga_bus{bus}'] = dict(SIZE=16, BUS_WIDTH=bus, DATA_WIDTH=16,
            CACHE_BLOCKS=32, EXTERNAL_RAM=1, defines=['XILINX_FPGA'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='437a8d81')
    parser.add_argument('--cases', nargs='+', choices=tuple(cases()))
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT)
    reference = out / 'reference.sv'
    reference.write_bytes(original)
    current = ROOT / SOURCE
    model, model_info = prepare_models(out)
    memories = [ROOT / 'rtl/common/regfile.v', ROOT / 'rtl/common/pseudo_dual_port_ram.v',
                ROOT / 'rtl/npu/compute/select_add.sv']
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in [current, *memories]}
    report = dict(passed=False, reference_commit=subprocess.check_output(
        ['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip(),
        source_sha256=hashes, reference_source_sha256=digest(reference),
        primitive_models=model_info, inputs_constrained=False, runs=[])
    selected = args.cases or list(cases())
    for name in selected:
        case = cases()[name]
        folder = out / name
        folder.mkdir(exist_ok=True)
        options = ['--no-synthesis-define', '-DYOSYS=1', '-DVERIFIC=1',
                   '--top', 'ia_loader_cache_mgr']
        options += [f'-G{key}={value}' for key, value in case.items() if key != 'defines']
        options += ['-GRAM_WORD_ADDR_WIDTH=12']
        options += ['-D' + define + '=1' for define in case['defines']]
        commands = []
        for label, source in (('reference', reference), ('current', current)):
            command = ['read_slang', *options, str(source), *map(str, memories), str(model)]
            commands += [' '.join(map(shlex.quote, command)),
                'prep -top ia_loader_cache_mgr -flatten', 'memory_map', 'async2sync', 'opt_clean',
                'rename ia_loader_cache_mgr ' + label, 'design -stash ' + label]
        commands += ['design -copy-from reference -as reference reference',
            'design -copy-from current -as current current',
            'equiv_make reference current equivalent', 'hierarchy -top equivalent',
            'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert']
        script = folder / 'run.ys'
        script.write_text('\n'.join(commands) + '\n')
        log = folder / 'formal.log'
        with log.open('w') as stream:
            run = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                '--worker', str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                timeout=480)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        result = dict(name=name, parameters=case, passed=run.returncode == 0 and
            'Equivalence successfully proven' in text,
            equivalent_bits=int(match[1]) if match else None,
            script_sha256=digest(script), log_sha256=digest(log))
        report['runs'].append(result)
        report['passed'] = all(item['passed'] for item in report['runs'])
        (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(result), flush=True)
        if not result['passed']:
            raise RuntimeError('IA cache equivalence did not complete: ' + str(log))
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in [current, *memories]}:
        raise RuntimeError('Measured source changed during verification')


if __name__ == '__main__':
    main()
