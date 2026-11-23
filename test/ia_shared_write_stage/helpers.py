"""生成生产 IA 缓存和共享存储的统一比较模块。"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test/ia_timing'))
from run_interface import port_declarations

SOURCES = ['rtl/npu/loaders/ia_loader_cache_mgr.sv',
           'rtl/npu/buffers/ia_ps_channel_ram.sv', 'rtl/npu/compute/select_add.sv']
PARAMETERS = dict(DATA_WIDTH=16, SIZE=16, BUS_WIDTH=64, DMA_LANES=8, REG_WIDTH=32,
                  CACHE_BLOCKS=32, COMPACT_S8=1,
                  RAM_WORD_ADDR_WIDTH=12, p_compact_offset_width=9,
                  SLOT_BLOCKS=64, p_addr_width=12, p_bank_count_width=3)


def make_wrapper(path, formal=False):
    cache = (ROOT / SOURCES[0]).read_text()
    channel = (ROOT / SOURCES[1]).read_text()
    cache_ports = port_declarations(cache)
    channel_ports = port_declarations(channel)
    ram_names = {name for _, _, name, _ in cache_ports if name.startswith('ram_')}
    ports = [port for port in cache_ports if port[2] not in ram_names]
    ports += [port for port in channel_ports if not port[2].startswith(('i_ia', 'o_ia'))
              and port[2] not in ('clk', 'rst_n')]
    if formal:
        ports.append(('output', 'logic [4:0]', 'o_properties', ''))
    lines = ['module cache_shared #(',
             "    parameter bit p_shared_write_stage=0, p_common_ps_address=0,",
             ',\n'.join(f'    parameter int {name}={value}' for name, value in PARAMETERS.items()),
             ') (', ',\n'.join(f'    {direction} {kind} {name} {array}'
                                for direction, kind, name, array in ports), ');']
    lines += [f'    {kind} {name} {array};' for _, kind, name, array in cache_ports
              if name in ram_names]
    parameters = [name for name in PARAMETERS if name not in
                  ('SLOT_BLOCKS', 'p_addr_width', 'p_bank_count_width')]
    lines += ['    ia_loader_cache_mgr #(',
              ',\n'.join(f'        .{name}({name})' for name in parameters) +
              ",\n        .p_dma_source_layout(1'b1),\n        .p_shared_write_stage(p_shared_write_stage)",
              '    ) u_cache (', ',\n'.join(f'        .{name}({name})'
                         for _, _, name, _ in cache_ports), '    );',
              '    logic [p_addr_width-1:0] ps_read_address [4], ps_write_address [4];',
              '    for (genvar channel=0; channel<4; channel++) begin : g_ps_address',
              '        assign ps_read_address[channel] = p_common_ps_address ? i_ps_read_addr[0] : i_ps_read_addr[channel];',
              '        assign ps_write_address[channel] = p_common_ps_address ? i_ps_write_addr[0] : i_ps_write_addr[channel];',
              '    end']
    mapping = dict(i_ia_read_en='ram_port_rd_en', i_ia_write_en='ram_port_wr_en',
        i_ia_read_addr='ram_port_rd_addr', i_ia_write_addr='ram_port_wr_addr',
        o_ia_read_data='ram_port_rd_data', i_ia_write_data='ram_port_wr_data',
        i_ia_write_mask='ram_port_wr_mask', i_ia_shared_write_data='ram_shared_wr_data',
        i_ps_read_addr='ps_read_address', i_ps_write_addr='ps_write_address',
        i_ps_read_en='p_common_ps_address ? {4{i_ps_read_en[0]}} : i_ps_read_en',
        i_ps_write_en='p_common_ps_address ? {4{i_ps_write_en[0]}} : i_ps_write_en')
    lines += ['    ia_ps_channel_ram #(.p_bank_bytes(8192), .p_total_bytes(57344),',
              '        .p_shared_write_stage(p_shared_write_stage)) u_memory (',
              ',\n'.join(f'        .{name}({mapping.get(name, name)})'
                         for _, _, name, _ in channel_ports), '    );']
    if formal:
        lines += [
            '    assign o_properties[0] = !ram_port_wr_en[1] || ram_shared_wr_data == ram_port_wr_data[1];',
            '    assign o_properties[1] = !(ram_port_wr_en[0] && !ram_port_wr_en[1]) || ram_shared_wr_data == ram_port_wr_data[0];',
            '    assign o_properties[2] = !ram_port_wr_en[1] || ram_port_wr_addr[1][0];',
            "    assign o_properties[3] = !(ram_port_wr_en == 2'b11) || !ram_port_wr_addr[0][0];",
            '    assign o_properties[4] = !u_memory.ia_bank_write_en[1] || ram_shared_wr_data == u_memory.ia_bank_write_data[1];']
    lines.append('endmodule')
    path.write_text('\n'.join(lines) + '\n')
    return ports


def make_physical_context(path, ports):
    lines = ['module physical_context #(parameter bit p_shared_write_stage=0) (',
             '    input logic clk, input logic serial_in, output logic serial_out);']
    lines += [f'    localparam int {name}={value};' for name, value in PARAMETERS.items()]
    lines += [f'    {kind} {name} {array};' for _, kind, name, array in ports if name != 'clk']
    inputs = [port for port in ports if port[0] == 'input' and port[2] != 'clk']
    outputs = [port for port in ports if port[0] == 'output']
    for group, entries in [('input', inputs), ('output', outputs)]:
        for index, (_, _, name, _) in enumerate(entries):
            previous = ('0' if index == 0 else
                        f'p_{group}_offset_{index-1} + $bits({entries[index-1][2]})')
            lines.append(f'    localparam int p_{group}_offset_{index} = {previous};')
        lines.append(f'    localparam int p_{group}_bits = p_{group}_offset_{len(entries)-1} + $bits({entries[-1][2]});')
    lines += ['    (* shreg_extract = "no", keep = 1 *) logic [p_input_bits-1:0] input_shift;',
              '    logic [p_output_bits-1:0] output_capture;',
              '    always_ff @(posedge clk) input_shift <= {input_shift[p_input_bits-2:0], serial_in};',
              '    assign serial_out = ^output_capture;']
    for group, entries in [('input', inputs), ('output', outputs)]:
        for index, (_, _, name, array) in enumerate(entries):
            if array:
                expression = array.strip()[1:-1]
                if ':' in expression:
                    left, right = expression.split(':')
                    count = abs(eval(left, {}, PARAMETERS) - eval(right, {}, PARAMETERS)) + 1
                else:
                    count = eval(expression, {}, PARAMETERS)
                lines.append(f'    for (genvar element=0; element<{count}; element++) begin : g_{group}_{name}')
                width, value = f'$bits({name}[0])', name + '[element]'
                offset = f'p_{group}_offset_{index} + element*{width}'
            else:
                width, value, offset = f'$bits({name})', name, f'p_{group}_offset_{index}'
            if group == 'input':
                lines.append(f'    assign {value} = input_shift[{offset} +: {width}];')
            else:
                lines.append(f'    always_ff @(posedge clk) output_capture[{offset} +: {width}] <= {value};')
            if array:
                lines.append('    end')
    lines += ["    cache_shared #(.p_shared_write_stage(p_shared_write_stage), .p_common_ps_address(1'b1)) u_core (",
              ',\n'.join(f'        .{name}({name})' for _, _, name, _ in ports), '    );', 'endmodule']
    path.write_text('\n'.join(lines) + '\n')
