#!/usr/bin/env python3
"""检查 IA 槽位有效列数的存储属性、实际 BRAM 端口与局部资源。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source
sys.path.insert(0, str(ROOT / 'test/cache_prefetch_payload'))
from measure import compress_completed, run_limited

SOURCE = 'rtl/npu/loaders/ia_loader_cache_mgr.sv'
MARKER = '  logic [ROW_CNT_W-1:0] slot_written_cols [SLOT_BLOCKS];'
CURRENT = MARKER.replace('logic', '(* ram_style = "block" *) logic', 1)
PARAMETERS = dict(DATA_WIDTH=16, SIZE=16, BUS_WIDTH=64, REG_WIDTH=32,
    CACHE_BLOCKS=32, COMPACT_S8=1, EXTERNAL_RAM=1, RAM_WORD_ADDR_WIDTH=12,
    p_compact_offset_width=9, p_dma_source_layout=1, p_shared_write_stage=1)


def check_memory(design):
    cells, names = design['cells'], design['netnames']
    selected = [(name, cell) for name, cell in cells.items() if 'slot_written_cols.' in name]
    assert len(selected) == 1
    name, cell = selected[0]
    assert cell['type'] == 'RAMB18E1'
    parameters, ports = cell['parameters'], cell['connections']
    assert parameters['RAM_MODE'] == 'TDP'
    assert parameters['WRITE_MODE_A'] == parameters['WRITE_MODE_B'] == 'READ_FIRST'
    assert int(parameters['WRITE_WIDTH_A'], 2) == int(parameters['READ_WIDTH_B'], 2) == 9
    assert int(parameters['DOA_REG'], 2) == int(parameters['DOB_REG'], 2) == 0
    assert parameters['SRVAL_B'].endswith('00000')
    assert ports['CLKARDCLK'] == ports['CLKBWRCLK'] == names['clk']['bits']
    assert ports['ADDRARDADDR'] == ['0']*3 + names['wr_slot']['bits'] + ['0']*5
    assert ports['ADDRBWRADDR'] == ['0']*3 + names['ram_rd_addr']['bits'][-6:] + ['0']*5
    outputs = {bit for port, bits in ports.items()
               if cell['port_directions'][port] == 'output' for bit in bits}
    assert set(names['read_extent_q']['bits']) <= outputs
    drivers = {bit: other for other in cells.values() for port, bits in other['connections'].items()
               if other['port_directions'][port] == 'output' for bit in bits if isinstance(bit, int)}

    def evaluate(bit, inputs):
        if bit in inputs:
            return inputs[bit]
        if bit in ('0', '1'):
            return int(bit)
        gate = drivers[bit]
        if gate['type'] == 'INV':
            return 1 - evaluate(gate['connections']['I'][0], inputs)
        assert re.fullmatch(r'LUT[1-6]', gate['type'])
        address = sum(evaluate(gate['connections'][f'I{index}'][0], inputs) << index
                      for index in range(int(gate['type'][-1])))
        return (int(gate['parameters']['INIT'], 2) >> address) & 1

    for reset_released in (0, 1):
        for read_enable in (0, 1):
            inputs = {names['rst_n']['bits'][0]: reset_released,
                      names['ram_rd_en']['bits'][0]: read_enable}
            assert evaluate(ports['RSTRAMB'][0], inputs) == 1 - reset_released
            assert evaluate(ports['ENBWREN'][0], inputs) == (read_enable | (1 - reset_released))
    return {'passed': True, 'cell': name, 'type': cell['type'], 'logical_rows': 64,
            'logical_width': 5, 'logical_bits': 320, 'read_mode': 'READ_FIRST',
            'clock_shared': True, 'read_address_bits_preserved': 6,
            'write_address_bits_preserved': 6, 'extra_output_registers': 0,
            'read_enable_and_reset_combinations_checked': 4,
            'reset_clears_output_only': True, 'output_hold_when_read_disabled': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='c96e9378')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    assert reference.count(MARKER) == current.count(CURRENT) == 1
    assert current.replace(CURRENT, MARKER, 1) == reference
    hashes, cases = {}, {}
    for label, content in (('reference', reference), ('current', current)):
        folder = out / 'sources' / label
        folder.mkdir(parents=True, exist_ok=True)
        source = folder / 'ia_loader_cache_mgr.sv'
        source.write_text(content)
        hashes[label] = hashlib.sha256(content.encode()).hexdigest()
        cases[label] = {'top': 'ia_loader_cache_mgr',
            'sources': [str(source), 'rtl/npu/compute/select_add.sv'], 'parameters': PARAMETERS,
            'options': ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1'] +
                       [f'-G{key}={value}' for key, value in PARAMETERS.items()],
            'configuration': '生产 IA 缓存，64 个逻辑槽位的同步列数存储'}
    config = out / 'cases.json'
    config.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    report = {'passed': False, 'reference_ref': args.reference, 'source_sha256': hashes,
        'parameters': PARAMETERS, 'rtl_identical_after_removing_ram_attribute': True,
        'mapping': {'mode': 'physical-cost', 'small_lut_area_cost': 1, 'max_lut_inputs': 6,
                    'wire_delay_ps': 500, 'delay_target_ps': 6667},
        'results': {}, 'physical_placement_performed': False}
    for label in cases:
        native, mapped = out / 'native' / label, out / 'mapped' / label
        run_limited([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
            '--case-config', str(config), '--cases', label, '--through', 'pre_lut',
            '--out', str(out / 'native')], 500000000)
        run_limited([sys.executable, str(ROOT / 'scripts/fpga/remap_fpga_luts.py'),
            '--source', str(native), '--out', str(mapped), '--mode', 'physical-cost',
            '--small-lut-area-cost', '1', '--max-lut-inputs', '6',
            '--wire-delay-ps', '500', '--delay-target-ps', '6667'], 500000000)
        summary = json.loads((mapped / 'summary.json').read_text())
        stages = json.loads((native / 'stages.json').read_text())
        report['results'][label] = {'resources': summary['resources'],
            'longest_register_path_cells': summary['longest_register_path_cells'],
            'abc_functional_verification': summary['functional_verification'],
            'peak_process_tree_rss_bytes': max(summary['mapping_stage']['peak_process_tree_rss_bytes'],
                *(stage['peak_process_tree_rss_bytes'] for stage in stages.values()))}
        if label == 'current':
            design = json.loads((mapped / 'mapped.json').read_text())['modules']['ia_loader_cache_mgr']
            report['bram_port_check'] = check_memory(design)
            del design
        report['results'][label]['compressed_files'] = compress_completed(native) + compress_completed(mapped)
        (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    report['net_change'] = {key: report['results']['current']['resources'][key] -
                               report['results']['reference']['resources'][key]
                           for key in ('logic_lut_cells', 'distributed_ram_lut_sites_nominal',
                                       'lut_sites_nominal_before_packing', 'flip_flops', 'ramb18e1')}
    assert hashlib.sha256((ROOT / SOURCE).read_bytes()).hexdigest() == hashes['current']
    report['passed'] = True
    report['test_script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report['net_change']))


if __name__ == '__main__':
    main()
