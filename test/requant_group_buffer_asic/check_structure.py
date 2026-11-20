#!/usr/bin/env python3
"""展开量化行缓冲，逐位检查 ASIC 宏连接、容量与 FPGA 同步存储。"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TOP = 'requant_group_buffer'
SOURCE_NAMES = ('rtl/npu/writeback/requant_group_buffer.sv', 'rtl/common/regfile.v',
                'asic/rtl/smic40_sram_1r1w.sv')
MACRO_PORTS = {'QA': 16, 'CLKA': 1, 'CENA': 1, 'AA': 7, 'CLKB': 1, 'CENB': 1,
               'WENB': 16, 'AB': 7, 'DB': 16, 'EMAA': 3, 'EMAB': 3,
               'RET1N': 1, 'COLLDISN': 1}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def integer(value):
    return int(value, 2) if isinstance(value, str) else value


def bits(value, width):
    return [(value >> index) & 1 for index in range(width)]


class CombinationalValues:
    """在给定地址与使能下，传播常量或独立数据位的符号标识。"""
    def __init__(self, module, overrides):
        self.cells = module['cells']
        self.values = dict(overrides)
        self.drivers = {}
        self.completed = set()
        for name, cell in self.cells.items():
            for port, direction in cell['port_directions'].items():
                if direction == 'output':
                    for bit in cell['connections'][port]:
                        if isinstance(bit, int):
                            self.drivers[bit] = name

    def bit(self, bit):
        if isinstance(bit, str):
            return int(bit) if bit in ('0', '1') else ('constant', bit)
        if bit not in self.values:
            name = self.drivers[bit]
            if name in self.completed:
                raise AssertionError(('missing output', name, bit))
            self.evaluate(name)
        return self.values[bit]

    def vector(self, vector):
        return [self.bit(bit) for bit in vector]

    @staticmethod
    def number(vector):
        assert all(value in (0, 1) for value in vector), vector
        return sum(value << index for index, value in enumerate(vector))

    def evaluate(self, name):
        cell = self.cells[name]
        kind, ports = cell['type'], cell['connections']
        self.completed.add(name)
        value = lambda port: self.vector(ports[port])
        number = lambda port: self.number(value(port))
        width = len(ports.get('Y', []))
        if kind == '$mux':
            result = value('B') if number('S') else value('A')
        elif kind == '$bmux':
            index = number('S')
            result = value('A')[index*width:(index+1)*width]
        elif kind == '$pmux':
            select = value('S')
            assert sum(select) <= 1
            index = select.index(1) if 1 in select else None
            result = value('A') if index is None else value('B')[index*width:(index+1)*width]
        elif kind in ('$shiftx', '$shr', '$sshr'):
            source, shift = value('A'), number('B')
            fill = ('constant', 'x') if kind == '$shiftx' else 0
            result = [source[index+shift] if index+shift < len(source) else fill
                      for index in range(width)]
        elif kind in ('$shl', '$sshl'):
            result = bits(number('A') << number('B'), width)
        elif kind in ('$add', '$sub', '$mul'):
            a, b = number('A'), number('B')
            result = bits(a+b if kind == '$add' else a-b if kind == '$sub' else a*b, width)
        elif kind in ('$and', '$or', '$xor', '$xnor'):
            a, b = number('A'), number('B')
            result = bits(a & b if kind == '$and' else a | b if kind == '$or'
                          else a ^ b if kind == '$xor' else ~(a ^ b), width)
        elif kind == '$not':
            result = bits(~number('A'), width)
        elif kind in ('$logic_not', '$reduce_or', '$reduce_bool', '$reduce_and'):
            a = value('A')
            assert all(bit in (0, 1) for bit in a)
            result = [int(not any(a)) if kind == '$logic_not' else
                      int(all(a)) if kind == '$reduce_and' else int(any(a))]
        elif kind in ('$logic_and', '$logic_or'):
            a, b = bool(number('A')), bool(number('B'))
            result = [int(a and b if kind == '$logic_and' else a or b)]
        elif kind in ('$eq', '$ne', '$lt', '$le', '$gt', '$ge'):
            a, b = number('A'), number('B')
            result = [int({'$eq': a == b, '$ne': a != b, '$lt': a < b,
                           '$le': a <= b, '$gt': a > b, '$ge': a >= b}[kind])]
        else:
            raise AssertionError(('unsupported combinational cell', name, kind))
        assert len(result) == width, (name, kind, len(result), width)
        for bit, result_bit in zip(ports['Y'], result):
            if isinstance(bit, int):
                self.values.setdefault(bit, result_bit)


def set_value(overrides, vector, value):
    for bit, value_bit in zip(vector, bits(value, len(vector))):
        if isinstance(bit, int):
            overrides[bit] = value_bit
        else:
            assert bit == str(value_bit), (vector, value)


def check_asic(module, lanes, rows):
    cells = module['cells']
    row_width, banks = 32*lanes+1, (rows+127)//128
    macro_lanes = (row_width+15)//16
    macros = [(name, cell) for name, cell in cells.items() if cell['type'] == 'RAMTP128X16']
    assert len(macros) == banks*macro_lanes, (len(macros), banks*macro_lanes)
    assert not any(cell['type'] == 'RAMTP1024X16' for cell in cells.values())
    assert not any(cell['type'].startswith('$mem') for cell in cells.values())
    assert not module.get('memories')
    assert not any('regfile' in cell['type'] or 'latch' in cell['type'].lower()
                   for cell in cells.values())
    net = lambda name: module['netnames'][name]['bits']
    write_address, read_address = net('write_addr_q'), net('read_addr_q')
    # [0:p_lanes-1] 数组在展开端口中以第零项占据高位，每项内部保持低位在前。
    row_bits = lambda name: [bit for lane in range(lanes)
        for bit in module['ports'][name]['bits'][32*(lanes-1-lane):32*(lanes-lane)]]
    write_row = row_bits('i_row_data') + module['ports']['i_row_tile_done']['bits']
    output_row = row_bits('o_row_data') + module['ports']['o_row_tile_done']['bits']
    read_bank = net('u_rows.read_bank')
    expected_bank_input = (read_address+['0']*(7+len(read_bank)))[7:7+len(read_bank)]
    bank_register_bits = 0
    for index, bit in enumerate(read_bank):
        if isinstance(bit, str):
            assert bit == expected_bank_input[index]
            continue
        matching = [cell for cell in cells.values() if bit in cell['connections'].get('Q', [])]
        assert len(matching) == 1
        register = matching[0]
        assert register['type'] == '$dffe'
        assert integer(register['parameters']['CLK_POLARITY']) == 1
        assert integer(register['parameters']['EN_POLARITY']) == 1
        connections = register['connections']
        assert connections['CLK'] == module['ports']['clk']['bits']
        assert connections['EN'] == net('storage_i_rd_en')
        assert connections['D'][connections['Q'].index(bit)] == expected_bank_input[index]
        bank_register_bits += 1
    qa_symbols, by_location = {}, {}
    for name, cell in macros:
        match = re.search(r'g_bank\[(\d+)\]\.g_lane\[(\d+)\]', name)
        assert match, name
        bank, lane = map(int, match.groups())
        by_location[bank, lane] = cell
        ports = cell['connections']
        assert {port: len(value) for port, value in ports.items()} == MACRO_PORTS
        assert ports['CLKA'] == ports['CLKB'] == module['ports']['clk']['bits']
        assert ports['AA'] == (read_address+['0']*7)[:7]
        assert ports['AB'] == (write_address+['0']*7)[:7]
        assert ports['RET1N'] == ports['COLLDISN'] == ['1']
        assert ports['EMAA'] == ports['EMAB'] == ['0', '1', '0']
        expected_data = (write_row+['0']*16)[16*lane:16*lane+16]
        assert ports['DB'] == expected_data, (name, 'write data')
        expected_mask = ['0' if 16*lane+bit < row_width else '1' for bit in range(16)]
        assert ports['WENB'] == expected_mask, (name, 'write mask')
        for bit_index, bit in enumerate(ports['QA']):
            qa_symbols[bit] = ('sram', bank, lane, bit_index)
    assert set(by_location) == {(bank, lane) for bank in range(banks) for lane in range(macro_lanes)}
    for selected_bank in range(banks):
        overrides = dict(qa_symbols)
        set_value(overrides, read_bank, selected_bank)
        values = CombinationalValues(module, overrides)
        expected = [('sram', selected_bank, bit//16, bit % 16) for bit in range(row_width)]
        assert values.vector(output_row) == expected, ('read data', selected_bank)
        for write_bank in range(banks):
            for read_enable in (0, 1):
                for write_enable in (0, 1):
                    overrides = {}
                    set_value(overrides, read_address, selected_bank*128)
                    set_value(overrides, write_address, write_bank*128)
                    set_value(overrides, net('storage_i_rd_en'), read_enable)
                    set_value(overrides, net('storage_i_wr_en'), write_enable)
                    values = CombinationalValues(module, overrides)
                    for (bank, lane), cell in by_location.items():
                        ports = cell['connections']
                        assert values.vector(ports['CENA']) == [int(not (read_enable and bank == selected_bank))]
                        assert values.vector(ports['CENB']) == [int(not (write_enable and bank == write_bank))]
    flip_flops = sum(len(cell['connections']['Q']) for cell in cells.values()
                     if cell['type'].startswith(('$dff', '$adff', '$sdff')))
    address_width, count_width = max(1, (rows-1).bit_length()), max(1, rows.bit_length())
    ff_bound = 2*address_width + 3*count_width + 1 + max(1, (banks-1).bit_length())
    assert flip_flops <= ff_bound, (flip_flops, ff_bound)
    return dict(macro_count=len(macros), macro_depth=128, macro_width=16,
                physical_storage_bits=len(macros)*2048, logical_storage_bits=rows*row_width,
                unused_storage_bits=len(macros)*2048-rows*row_width,
                inferred_memories=0, control_flip_flops=flip_flops, control_flip_flop_bound=ff_bound,
                write_data_bits_checked=len(macros)*16, write_mask_bits_checked=len(macros)*16,
                read_data_bits_checked=banks*row_width, read_bank_hold_bits_checked=bank_register_bits,
                bank_enable_checks=banks*banks*4*len(macros)*2)


def check_fpga(module, lanes, rows):
    cells = module['cells'].values()
    memories = [cell for cell in cells if cell['type'] == '$mem_v2']
    assert len(memories) == 1
    assert not any(cell['type'].startswith('RAMTP') for cell in cells)
    parameters = memories[0]['parameters']
    assert integer(parameters['WIDTH']) == 32*lanes+1
    assert integer(parameters['SIZE']) == rows
    assert integer(parameters['RD_PORTS']) == integer(parameters['WR_PORTS']) == 1
    assert integer(parameters['RD_CLK_ENABLE']) == integer(parameters['WR_CLK_ENABLE']) == 1
    assert integer(parameters['RD_TRANSPARENCY_MASK']) == 0
    assert integer(parameters['RD_COLLISION_X_MASK']) == 0
    connections = memories[0]['connections']
    assert connections['RD_CLK'] == connections['WR_CLK'] == module['ports']['clk']['bits']
    assert connections['RD_EN'] == module['netnames']['storage_i_rd_en']['bits']
    for enable in (0, 1):
        overrides = {}
        set_value(overrides, module['netnames']['storage_i_wr_en']['bits'], enable)
        assert CombinationalValues(module, overrides).vector(connections['WR_EN']) == [enable]*(32*lanes+1)
    return dict(inferred_memories=1, logical_storage_bits=rows*(32*lanes+1),
                memory_width=32*lanes+1, memory_depth=rows, synchronous_read=True,
                same_address_read='old data', macro_count=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--profiles', nargs='+', default=['16:512', '1:1', '1:15', '1:16', '1:17',
                        '3:127', '3:128', '3:129', '16:511', '16:513', '1:1024', '1:2048', '1:2049'])
    args = parser.parse_args()
    source_root, out = args.source_root.resolve(), args.out.resolve()
    snapshot = out/'sources'
    snapshot.mkdir(parents=True, exist_ok=True)
    sources, hashes = [], {}
    for name in SOURCE_NAMES:
        source, target = source_root/name, snapshot/Path(name).name
        target.write_bytes(source.read_bytes())
        sources.append(target)
        hashes[name] = sha(source)
    stub = ROOT/'test/shared_ia_ps/asic_macro_blackboxes.sv'
    target = snapshot/stub.name
    target.write_bytes(stub.read_bytes())
    sources.append(target)
    hashes[str(stub.relative_to(ROOT))] = sha(stub)
    report = dict(passed=False, validation='SRAM structure, capacity and complete data-bit connectivity',
                  macro_model='black-box interface', source_sha256=hashes, cases=[],
                  source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                                                        cwd=source_root, text=True).strip())
    for profile in args.profiles:
        lanes, rows = map(int, profile.split(':'))
        assert lanes >= 1 and rows >= 1
        for mode in ('asic', 'fpga'):
            name = f'{mode}_l{lanes}_r{rows}'
            folder = out/name
            folder.mkdir(exist_ok=True)
            script, netlist, log = folder/'run.ys', folder/'mapped.json', folder/'run.log'
            defines = '-D ASIC_SYNTHESIS=1 -D ASIC_SRAM=1' if mode == 'asic' else '-D XILINX_FPGA=1'
            commands = [f'read_slang --top {TOP} -D SYNTHESIS=1 {defines} '
                        f'-Gp_lanes={lanes} -Gp_rows={rows} '
                        '--blackboxed-module RAMTP128X16 --blackboxed-module RAMTP1024X16 '+
                        ' '.join(shlex.quote(str(path)) for path in sources),
                        f'hierarchy -check -top {TOP}', 'proc', 'flatten', 'opt', 'memory_dff',
                        'memory_collect', 'opt_clean', 'check -assert',
                        'write_json '+shlex.quote(str(netlist))]
            script.write_text('\n'.join(commands)+'\n')
            command = [sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)]
            with log.open('w') as stream:
                result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
            assert result.returncode == 0, str(log)
            module = json.loads(netlist.read_text())['modules'][TOP]
            checks = check_asic(module, lanes, rows) if mode == 'asic' else check_fpga(module, lanes, rows)
            entry = dict(name=name, mode=mode, lanes=lanes, rows=rows, passed=True, **checks,
                         script_sha256=sha(script), netlist_sha256=sha(netlist), log_sha256=sha(log))
            report['cases'].append(entry)
            print(json.dumps(entry, ensure_ascii=False), flush=True)
            with gzip.open(str(netlist)+'.gz', 'wb') as stream:
                stream.write(netlist.read_bytes())
            netlist.unlink()
    assert all(sha(source_root/name) == hashes[name] for name in SOURCE_NAMES)
    report.update(passed=True, source_unchanged_during_checks=True, checker_sha256=sha(Path(__file__)))
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
