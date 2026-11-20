#!/usr/bin/env python3
"""核对实际 RAMB18 ROM 的每个数据位、地址连接、时钟及只读配置。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def integer(value):
    return int(value, 2) if isinstance(value, str) else value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped-case', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--capacity-reference', type=Path)
    args = parser.parse_args()
    mapped = args.mapped_case.resolve()/'mapped.json'
    module = json.loads(mapped.read_text())['modules']['reciprocal_unit']
    cells = list(module['cells'].values())
    assert len(cells) == 1 and cells[0]['type'] == 'RAMB18E1'
    cell = cells[0]
    parameters, ports = cell['parameters'], cell['connections']
    assert parameters['RAM_MODE'] == 'TDP'
    assert integer(parameters['READ_WIDTH_A']) == 18
    assert integer(parameters['READ_WIDTH_B']) == 0
    assert integer(parameters['WRITE_WIDTH_A']) == integer(parameters['WRITE_WIDTH_B']) == 0
    assert integer(parameters['DOA_REG']) == integer(parameters['DOB_REG']) == 0
    assert ports['WEA'] == ['0']*2 and ports['WEBWE'] == ['0']*4
    assert ports['ENARDEN'] == ['1'] and ports['ENBWREN'] == ['0']
    assert ports['CLKARDCLK'] == module['ports']['clk']['bits']
    assert ports['RSTRAMARSTRAM'] == ['0']
    assert ports['ADDRARDADDR'] == ['0']*4+module['ports']['i_taps']['bits']+['0']
    data = ''.join(parameters[f'INIT_{index:02X}'][::-1] for index in range(64))
    parity = ''.join(parameters[f'INITP_{index:02X}'][::-1] for index in range(8))
    expected_outputs = module['ports']['o_reciprocal']['bits']
    physical_outputs = ports['DOADO'][:8]+ports['DOPADOP'][:1]+ports['DOADO'][8:]+ports['DOPADOP'][1:]
    assert physical_outputs == expected_outputs
    for denominator in range(512):
        physical_data = data[16*denominator:16*(denominator+1)]
        physical_parity = parity[2*denominator:2*(denominator+1)]
        logical = physical_data[:8]+physical_parity[:1]+physical_data[8:]+physical_parity[1:]
        if denominator <= 256:
            expected = 0 if denominator == 0 else ((1 << 17)+denominator-1)//denominator
            assert logical == format(expected, '018b')[::-1], denominator
        else:
            assert logical == 'x'*18, denominator
    summary = {'passed': True, 'ramb18_cells': 1, 'logic_lut_cells': 0,
               'defined_words': 257, 'word_bits': 18, 'checked_defined_bits': 257*18,
               'logical_rom_bits': 257*18, 'physical_rom_bits': 18432,
               'registered_read_data_bits': 18, 'read_latency_cycles': 1,
               'out_of_range_words': 255, 'out_of_range_bits_unknown': True,
               'address_clock_output_connections_checked': True,
               'mapped_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest()}
    if args.capacity_reference:
        capacity = json.loads(args.capacity_reference.read_text())
        arrays = capacity['elaborated_state']['buffer_arrays_bits']
        original_bits = sum(arrays.values())
        summary['capacity'] = {'existing_buffer_bits': original_bits,
                               'buffer_and_rom_bits': original_bits+257*18,
                               'buffer_rom_and_read_register_bits': original_bits+257*18+18,
                               'budget_bits': 131072*8,
                               'within_budget': original_bits+257*18+18 <= 131072*8,
                               'reference_sha256': hashlib.sha256(args.capacity_reference.read_bytes()).hexdigest()}
        assert summary['capacity']['within_budget']
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
