#!/usr/bin/env python3
"""从实际地址 RTL 提取坐标更新，验证四态、完整位值及推断 DSP 的功能。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ADDRESS = Path('rtl/npu/conv/vector_engine_address.sv')
PACKAGE = Path('rtl/npu/conv/vector_engine_pkg.sv')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def proof(out: Path, name: str, commands: list[str]) -> int:
    script, log = out / (name + '.ys'), out / (name + '.log')
    script.write_text('\n'.join(commands) + '\n')
    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=300)
    match = re.search(r'Of those cells (\d+) are proven and 0 are unproven', log.read_text())
    assert match
    return int(match[1])


def comparison() -> list[str]:
    return ['design -copy-from reference -as reference reference',
            'design -copy-from current -as current current', 'equiv_make reference current proof',
            'hierarchy -top proof', 'equiv_simple', 'equiv_status -assert']


def extract(address: str, package: str, label: str) -> str:
    start = address.index('  for (genvar coordinate = 0; coordinate < 8; coordinate++)')
    finish = address.index('\n  end', start) + len('\n  end')
    block = address[start:finish].replace('vector_engine_pkg::advance_coordinate', 'advance_coordinate')
    function = re.search(r'  function automatic logic signed \[17:0\] advance_coordinate\(.*?  endfunction',
                         package, re.S)[0]
    return (f'module coordinate_step_{label}(\n'
            ' input wire logic [33:0] coordinate_step_i_value [8],\n'
            ' input wire logic [33:0] coordinate_step_i_delta [8],\n'
            ' output wire logic [33:0] coordinate_step_o_value [8]\n);\n'
            + function + '\n' + block + '\nendmodule\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='35408bcf')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes, cases, sources = {}, {}, {}
    revision = subprocess.check_output(['git', 'rev-parse', args.reference + '^{commit}'],
                                       cwd=ROOT, text=True).strip()
    for label in ('reference', 'current'):
        text = {}
        hashes[label] = {}
        for relative in (ADDRESS, PACKAGE):
            data = (subprocess.check_output(['git', 'show', revision + ':' + str(relative)], cwd=ROOT)
                    if label == 'reference' else (ROOT / relative).read_bytes())
            text[relative] = data.decode()
            hashes[label][str(relative)] = hashlib.sha256(data).hexdigest()
        sources[label] = out / (label + '.sv')
        sources[label].write_text(extract(text[ADDRESS], text[PACKAGE], label))
        cases[label] = dict(top='coordinate_step_' + label, sources=[str(sources[label])],
                            options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1'], parameters={},
                            configuration='Eight exact coordinate update expressions')
    commands = []
    for label in ('reference', 'current'):
        commands += [f'read_slang --top coordinate_step_{label} {sources[label]}',
                     f'prep -top coordinate_step_{label} -flatten',
                     f'rename -top {label}', f'design -stash {label}']
    equivalent_bits = proof(out, 'rtl_proof', commands + comparison())
    command = ['iverilog', '-g2012', '-s', 'tb', '-o', str(out / 'sim.vvp'),
               str(sources['reference']), str(sources['current']), str(HERE / 'coordinate_four_state.sv')]
    with (out / 'compile.log').open('w') as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
    run = subprocess.run(['vvp', str(out / 'sim.vvp')], capture_output=True, text=True, timeout=180)
    (out / 'run.log').write_text(run.stdout + run.stderr)
    print(run.stdout, end='', flush=True)
    run.check_returncode()
    assert 'COORDINATE_FOUR_STATE_PASS comparisons=160000' in run.stdout
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    command = [sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--source-root', str(ROOT),
               '--case-config', str(out / 'cases.json'), '--cases', 'reference', 'current',
               '--out', str(out / 'synthesis')]
    with (out / 'synthesis.log').open('w') as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
    resources = {label: json.loads((out / 'synthesis' / label / 'metrics.json').read_text())['resources']
                 for label in ('reference', 'current')}
    assert resources['current']['dsp48e1'] == 4
    mapped_bits = proof(out, 'mapped_proof', [
        f'read_slang --top coordinate_step_current -DSYNTHESIS=1 {sources["current"]}',
        'prep -top coordinate_step_current -flatten', 'opt -full', 'rename -hide w:*',
        'rename -top reference', 'design -stash reference',
        'read_verilog ' + str(out / 'synthesis/current/mapped.v'),
        'read_verilog -overwrite +/xilinx/cells_sim.v', 'rename coordinate_step_current current',
        'hierarchy -top current', 'flatten -wb', 'proc', 'memory_map', 'opt -full',
        'rename -hide w:*', 'design -stash current',
    ] + comparison())
    assert mapped_bits == 272
    assert hashes['current'] == {str(relative): digest(ROOT / relative) for relative in (ADDRESS, PACKAGE)}
    summary = dict(passed=True, reference_revision=revision, source_sha256=hashes,
                   rtl_equivalent_bits=equivalent_bits, four_state_comparisons=160000,
                   mapped_output_bits=mapped_bits, mapped_device_model='xilinx/cells_sim.v',
                   resources=resources,
                   generated_sha256={label: digest(path) for label, path in sources.items()})
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
