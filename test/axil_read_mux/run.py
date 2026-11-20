#!/usr/bin/env python3
"""逐周期比较 AXI-Lite 配置模块的全部公开输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from prepare_measurement import PARAMETERS, ROOT, SOURCE
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source


def run_logged(command, path):
    with path.open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)


def testbench(ports, parameters, cycles):
    lines = ['module tb;', '    integer checked_cycles = 0;', '    integer writes = 0;',
             '    integer reads = 0;']
    inputs = [name for name, value in ports.items() if value['direction'] == 'input']
    outputs = [name for name, value in ports.items() if value['direction'] == 'output']
    for name, value in ports.items():
        width = len(value['bits'])
        shape = f'[{width-1}:0] ' if width > 1 else ''
        if value['direction'] == 'input':
            lines.append(f'    logic {shape}{name};')
        else:
            lines += [f'    logic {shape}gold_{name};', f'    logic {shape}gate_{name};']
    param_text = ', '.join(f'.{key}(32\'h{value:08x})' for key, value in parameters.items())
    for module, prefix in [('npu_axil_reg_if_ref', 'gold'), ('npu_axil_reg_if', 'gate')]:
        connections = [f'.{name}({name if name in inputs else prefix + "_" + name})' for name in ports]
        lines.append(f'    {module} #({param_text}) u_{prefix} (\n        ' + ',\n        '.join(connections) + '\n    );')
    lines += ['    task automatic tick;', '        #5;',
              '        if (s_axil_awvalid && gold_s_axil_awready) writes = writes + 1;',
              '        if (s_axil_arvalid && gold_s_axil_arready) reads = reads + 1;',
              '        clk = 1; #1; checked_cycles = checked_cycles + 1;']
    for name in outputs:
        lines.append(f'        if (gold_{name} !== gate_{name}) $fatal(1, "{name} cycle=%0d", checked_cycles);')
    lines += ['        #4; clk = 0;', '    endtask',
              '    task automatic write_word(input integer address, input logic [31:0] data, input logic [7:0] mask);',
              '        s_axil_awaddr = address; s_axil_wdata = data; s_axil_wstrb = mask;',
              '        s_axil_awvalid = 1; s_axil_wvalid = 1; tick();',
              '        s_axil_awvalid = 0; s_axil_wvalid = 0; tick(); tick();',
              '    endtask', '    task automatic read_word(input integer address);',
              '        s_axil_araddr = address; s_axil_arvalid = 1; tick();',
              '        s_axil_arvalid = 0; tick();', '    endtask', '    initial begin']
    for name in inputs:
        lines.append(f"        {name} = '0;")
    lines += ['        repeat (3) tick(); rst_n = 1;',
              '        s_axil_bready = 1; s_axil_rready = 1; npu_sa_ready = 1;',
              '        for (integer pass = 0; pass < 2; pass++) begin',
              '            for (integer word = 0; word < 128; word++) begin',
              "                write_word(word << 2, $urandom & 32'hffff_fffe, pass ? $urandom : 8'hff);",
              '                read_word(word << 2);', '            end', '        end',
              '        for (integer value = 0; value < 40; value++) begin',
              "            write_word(16'h0108, value, 8'hff); read_word(16'h0108);",
              "            write_word(16'h0108, 32'h0100_0000 | value, 8'hff); read_word(16'h0108);",
              '        end', f'        for (integer cycle = 0; cycle < {cycles}; cycle++) begin']
    for name in inputs:
        if name in ('clk', 'rst_n'):continue
        width = len(ports[name]['bits'])
        if width <= 32:
            lines.append(f'            {name} = {width}\'($urandom);')
        else:
            words = (width + 31) // 32
            lines.append(f'            {name} = {width}\'(\u007b' + ', '.join(['$urandom'] * words) + '\u007d);')
    lines += ['            rst_n = (cycle % 4096) > 1;',
              '            if (cycle % 3) begin',
              '                s_axil_awaddr = ($urandom_range(0, 127) << 2) | $urandom_range(0, 3);',
              '                s_axil_araddr = ($urandom_range(0, 127) << 2) | $urandom_range(0, 3);',
              '            end', '            npu_done_valid = ($urandom_range(0, 15) == 0);',
              '            tick();', '        end',
              f'        $display("AXIL_READ_MUX_PASS cycles=%0d outputs={len(outputs)} writes=%0d reads=%0d", checked_cycles, writes, reads);',
              '        $finish;', '    end', 'endmodule']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='c7088884')
    parser.add_argument('--verilator', default='verilator-modern')
    parser.add_argument('--cycles', type=int, default=100000)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    (out / 'reference.sv').write_text(re.sub(r'\bnpu_axil_reg_if\b', 'npu_axil_reg_if_ref', reference))
    (out / 'current.sv').write_text(current)
    package = ROOT / 'rtl/npu/conv/conv_im2col_pkg.sv'
    results = []
    profiles = [('production', PARAMETERS),
                ('wide_data', {**PARAMETERS, 'AXIL_DATA_WIDTH': 64,
                               'AXIL_ADDR_WIDTH': 20, 'SHARED_IA_BANK_MASK': 4294967295})]
    for name, parameters in profiles:
        folder = out / name
        folder.mkdir(exist_ok=True)
        flags = ' '.join(f'-G{key}=32\'h{value:08x}' for key, value in parameters.items())
        script = folder / 'ports.ys'
        script.write_text(f'read_slang --top npu_axil_reg_if {flags} {package} {out / "current.sv"}\n'
                          f'proc\nwrite_json {folder / "ports.json"}\n')
        run_logged([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                    '--worker', str(script)], folder / 'ports.log')
        ports = json.loads((folder / 'ports.json').read_text())['modules']['npu_axil_reg_if']['ports']
        tb = folder / 'tb.sv'
        tb.write_text(testbench(ports, parameters, args.cycles))
        command = [args.verilator, '--binary', '--timing', '--assert', '-Wno-fatal',
                   '-j', '1', '--top-module', 'tb', '--Mdir', str(folder / 'obj'),
                   str(package), str(out / 'reference.sv'), str(out / 'current.sv'), str(tb)]
        run_logged(command, folder / 'compile.log')
        binary = folder / 'obj/Vtb'
        result = subprocess.run([str(binary)], cwd=ROOT, text=True, capture_output=True, check=True)
        (folder / 'run.log').write_text(result.stdout + result.stderr)
        match = re.search(r'AXIL_READ_MUX_PASS (.*)', result.stdout)
        assert match, result.stdout
        counters = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', match[1])}
        row = {'name': name, 'passed': True, 'parameters': parameters, **counters,
               'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}
        results.append(row)
        print(json.dumps(row), flush=True)
    assert current == (ROOT / SOURCE).read_text()
    (out / 'summary.json').write_text(json.dumps({'passed': True, 'profiles': results,
        'reference': args.reference, 'all_public_outputs_including_invalid_cycles': True,
        'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
        'reference_sha256': hashlib.sha256(reference.encode()).hexdigest()}, indent=2) + '\n')


if __name__ == '__main__':
    main()
