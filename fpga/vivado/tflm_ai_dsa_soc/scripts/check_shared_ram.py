#!/usr/bin/env python3
"""Verify the physical Xilinx 7 series mapping of the production shared RAM."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time


ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / 'rtl/npu/buffers/ia_ps_shared_ram.sv'
BANK_BYTES = 8192


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(parameters: dict, name: str) -> int:
    value = parameters[name]
    return int(value, 2) if isinstance(value, str) else int(value)


def examine(directory: Path, banks: int) -> dict:
    inferred = json.loads((directory / 'inferred.json').read_text())
    memories = []
    fields = ('WIDTH', 'SIZE', 'RD_PORTS', 'WR_PORTS', 'RD_CLK_ENABLE', 'WR_CLK_ENABLE')
    for name, cell in inferred['modules']['ia_ps_shared_ram']['cells'].items():
        if cell['type'] != '$mem_v2':
            continue
        values = [number(cell['parameters'], field) for field in fields]
        if values != [128, 512, 1, 1, 1, 1]:
            raise ValueError(f'Unexpected shared-bank geometry: {name}: {values}')
        memories.append(dict(name=name, **dict(zip((field.lower() for field in fields), values))))
    if len(memories) != banks:
        raise ValueError(f'Expected {banks} inferred banks, found {len(memories)}')

    mapped = json.loads((directory / 'mapped.json').read_text())
    cells = mapped['modules']['ia_ps_shared_ram']['cells']
    counts = Counter(cell['type'] for cell in cells.values())
    lutram = sum(count for kind, count in counts.items()
                 if kind.startswith('RAM') and not kind.startswith('RAMB'))
    if counts['RAMB36E1'] != 2 * banks or counts['RAMB18E1'] != 0 or lutram != 0:
        raise ValueError(f'Unexpected physical memory mapping: {dict(counts)}')
    details = []
    for name, cell in cells.items():
        if cell['type'] != 'RAMB36E1':
            continue
        parameters, ports = cell['parameters'], cell['connections']
        mode = parameters['RAM_MODE']
        read_width, write_width = number(parameters, 'READ_WIDTH_A'), number(parameters, 'WRITE_WIDTH_B')
        if mode != 'SDP' or read_width != 72 or write_width != 72:
            raise ValueError(f'Unexpected RAMB36E1 port mode: {name}')
        if set(ports['DIPADIP'] + ports['DIPBDIP']) != {'0'}:
            raise ValueError(f'Parity write inputs must be zero: {name}')
        details.append(dict(name=name, mode=mode, read_width=read_width,
                            write_width=write_width, parity_write_inputs_zero=True))

    data_bits = counts['RAMB36E1'] * 32768
    parity_bits = counts['RAMB36E1'] * 4096
    logical_bits = banks * BANK_BYTES * 8
    if data_bits != logical_bits:
        raise ValueError('Shared data capacity must equal mapped block RAM data capacity')
    logic_luts = sum(count for kind, count in counts.items()
                     if re.fullmatch(r'LUT[1-6](?:_2)?', kind))
    flip_flops = sum(counts[kind] for kind in ('FDRE', 'FDSE', 'FDCE', 'FDPE', 'FD', 'FDE'))
    return dict(passed=True, bank_bytes=BANK_BYTES, bank_count=banks,
                logical_bytes=logical_bits // 8, inferred_banks=memories,
                mapped_primitives=dict(sorted(counts.items())),
                ramb36_count=counts['RAMB36E1'], ramb18_count=counts['RAMB18E1'],
                lutram_count=lutram, logic_luts=logic_luts, external_flip_flops=flip_flops,
                physical_data_bits=data_bits, physical_parity_bits=parity_bits,
                physical_total_bits=data_bits + parity_bits,
                unused_data_bits=0, unused_parity_bits=parity_bits,
                data_utilization=1.0, total_bit_utilization=logical_bits / (data_bits + parity_bits),
                block_ram_details=details, mapped_sha256=sha256(directory / 'mapped.json'))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--yosys', default='yosys', help='Yosys with read_slang and synth_xilinx')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--banks', nargs='+', type=int, choices=(6, 7, 8, 9), default=[6, 7, 8, 9])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = (SOURCE, Path(__file__).resolve())
    before = {str(path.relative_to(ROOT)): sha256(path) for path in sources}
    version = subprocess.run([args.yosys, '-V'], check=True, text=True,
                             capture_output=True).stdout.strip()
    summary = dict(passed=False, complete=False, tool='Yosys synth_xilinx -family xc7',
                   tool_version=version, vivado_executed=False, source_sha256=before,
                   profiles=[], requested_bank_counts=args.banks)
    try:
        for banks in args.banks:
            directory = out / f'banks_{banks}'
            directory.mkdir(parents=True, exist_ok=True)
            script = directory / 'map.ys'
            script.write_text(
                f'read_slang --top ia_ps_shared_ram -D SYNTHESIS -GBANK_BYTES={BANK_BYTES} '
                f'-GTOTAL_BYTES={banks * BANK_BYTES} rtl/npu/buffers/ia_ps_shared_ram.sv\n'
                'opt\nmemory_dff\nmemory_share\nopt_clean\nmemory_collect\ncheck -assert\n'
                f'write_json {json.dumps(str(directory / "inferred.json"))}\n'
                'synth_xilinx -top ia_ps_shared_ram -family xc7 -noiopad -noclkbuf\n'
                'check -assert\nstat -tech xilinx\n'
                f'write_json {json.dumps(str(directory / "mapped.json"))}\n')
            command = [args.yosys, '-Q', '-T', '-s', str(script)]
            started = time.monotonic()
            with (directory / 'mapping.log').open('w') as log:
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                               check=True, timeout=600)
            result = examine(directory, banks)
            result.update(command=command, directory=str(directory),
                          elapsed_seconds=time.monotonic() - started)
            (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
            summary['profiles'].append(result)
            print(json.dumps({key: result[key] for key in
                              ('passed', 'bank_count', 'ramb36_count', 'logic_luts',
                               'external_flip_flops', 'data_utilization')}), flush=True)
        summary['complete'] = True
        summary['sources_unchanged'] = before == {
            str(path.relative_to(ROOT)): sha256(path) for path in sources}
        summary['passed'] = summary['sources_unchanged']
    except (ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        summary['failure'] = str(error)
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
