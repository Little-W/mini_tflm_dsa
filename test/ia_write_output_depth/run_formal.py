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
from rtl_reference import read_rtl_source, shared_ia_options

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/loaders/ia_loader_cache_mgr.sv')
from primitives import prepare_models


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observe_write_masks(source, label):
    """写使能为一时比较字节掩码，所有控制和其他公开输出保持直接比较。"""
    split = source.index('\n);') + len('\n);')
    header, body = source[:split], source[split:]
    internal = label + '_write_mask'
    body = re.sub(r'\bram_port_wr_mask\b', internal, body)
    declaration = '\n  logic [15:0] ' + internal + ' [0:1];\n'
    observation = f'''
  for (genvar formal_port = 0; formal_port < 2; formal_port++) begin : g_formal_write_mask
    assign ram_port_wr_mask[formal_port] = ram_port_wr_en[formal_port] ?
        {internal}[formal_port] : 16'd0;
  end
'''
    return header + declaration + body.replace('endmodule', observation + '\nendmodule', 1)


def cases():
    result = {'production': dict(SIZE=16, BUS_WIDTH=64, DATA_WIDTH=16,
        CACHE_BLOCKS=32, COMPACT_S8=1, REG_WIDTH=32,
        p_compact_offset_width=9, defines=['SYNTHESIS', 'XILINX_FPGA'])}
    for layout in (0, 1):
        result[f'shared_layout{layout}'] = dict(result['production'],
            p_dma_source_layout=layout, p_shared_write_stage=1)
    for bus, blocks in ((32, 2), (64, 4), (8, 32), (32, 32), (64, 32), (128, 32), (256, 32)):
        name = f'generic_s16_b{bus}_d16_c{blocks}'
        result[name] = dict(SIZE=16, BUS_WIDTH=bus, DATA_WIDTH=16,
                            CACHE_BLOCKS=blocks, defines=[])
    for flags in itertools.product((False, True), repeat=3):
        names = ('XILINX_FPGA', 'SYNTHESIS', 'ASIC_SYNTHESIS')
        defines = [name for name, enabled in zip(names, flags) if enabled]
        name = '_'.join(defines).lower() if defines else 'generic_macros'
        result[name] = dict(SIZE=16, BUS_WIDTH=64, DATA_WIDTH=16,
                            CACHE_BLOCKS=32, defines=defines)
    for bus in (8, 32, 128, 256):
        result[f'fpga_bus{bus}'] = dict(SIZE=16, BUS_WIDTH=bus, DATA_WIDTH=16,
            CACHE_BLOCKS=32, defines=['XILINX_FPGA'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='7ff66a59')
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--valid-write-masks', action='store_true',
                        help='Compare external RAM byte masks only while the corresponding write enable is asserted')
    parser.add_argument('--cases', nargs='+', choices=tuple(cases()))
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_root = args.source_root.resolve()
    original = ((args.reference_root / SOURCE).read_bytes() if args.reference_root else
                read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT))
    reference = out / 'reference.sv'
    current = out / 'current.sv'
    current_source = (source_root / SOURCE).read_bytes()
    if args.valid_write_masks:
        reference.write_text(observe_write_masks(original.decode(), 'reference'))
        current.write_text(observe_write_masks(current_source.decode(), 'current'))
    else:
        reference.write_bytes(original)
        current.write_bytes(current_source)
    model, model_info = prepare_models(out)
    memories = sorted(path for path in (source_root / 'rtl/common').iterdir()
                      if path.suffix in ('.v', '.sv'))
    memories.append(source_root / 'rtl/npu/compute/select_add.sv')
    hashes = {str(SOURCE): hashlib.sha256(current_source).hexdigest(),
              **{str(path.relative_to(source_root)): digest(path) for path in memories}}
    report = dict(passed=False, reference_commit=(str(args.reference_root.resolve()) if args.reference_root else
        subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip()),
        source_sha256=hashes, reference_source_sha256=hashlib.sha256(original).hexdigest(),
        primitive_models=model_info, inputs_constrained=False,
        write_mask_validity_qualified=args.valid_write_masks, runs=[])
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
            selected_options = shared_ia_options(options, source.read_text())
            command = ['read_slang', *selected_options, str(source), *map(str, memories), str(model)]
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
    if hashes != {str(SOURCE): digest(source_root / SOURCE),
                  **{str(path.relative_to(source_root)): digest(path) for path in memories}}:
        raise RuntimeError('Measured source changed during verification')


if __name__ == '__main__':
    main()
