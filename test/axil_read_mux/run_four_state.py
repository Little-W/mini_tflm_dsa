#!/usr/bin/env python3
"""检查实际地址表、选择语句和银行数量保存的四态行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from prepare_measurement import ROOT, SOURCE
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source


def normalize(text):
    return re.sub(r'\s+', '', text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='c7088884')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    constants = {name: int(value, 16) for name, value in
                 re.findall(r"localparam logic \[11:0\] (\w+)\s*=\s*12'h([0-9a-f]+)", original)}
    first = original.index('        case (rd_word_addr)')
    block = original[first:original.index('        endcase', first)]
    entries = list(re.finditer(r"^            (REG_\w+|12'h[0-9a-f]+):", block, re.M))
    addresses = []
    assignments = 0
    for index, entry in enumerate(entries):
        label = entry[1]
        value = int(label[4:], 16) if label.startswith("12'h") else constants[label]
        addresses.append(value)
        body = block[entry.end():entries[index+1].start() if index+1 < len(entries)
                     else block.index('            default:')]
        for assignment in re.findall(r'read_data_next(?:\[[^\]]+\])?\s*=.*?;', body, re.S):
            converted = assignment.replace('read_data_next', f'read_words[{label}]')
            assert normalize(converted) in normalize(current), label
            assignments += 1
    actual_labels = re.findall(r"read_words\[(REG_\w+|12'h[0-9a-f]+)\]", current)
    actual_addresses = {int(label[4:], 16) if label.startswith("12'h") else constants[label]
                        for label in actual_labels}
    assert actual_addresses == set(addresses)
    first = current.index("        read_data_next = '0;")
    end = current.index('\n    end', first)
    selection = current[first:end]
    assert 'case' not in selection and 'read_words[rd_word_addr[p_read_addr_width-1:0]]' in selection
    results = []
    for width in (32, 64):
        folder = out / f'data{width}'
        folder.mkdir(exist_ok=True)
        old_cases = '\n'.join(f"            12'h{address:03x}: reference_data = read_words[{address}];"
                              for address in addresses)
        fill = '\n'.join(f'            read_words[{address}] = {{{{$urandom}}, {{$urandom}}}};\n'
                         f'            if ((sample + {address}) % 11 == 0) read_words[{address}][7:0] = \'x;\n'
                         f'            if ((sample + {address}) % 13 == 0) read_words[{address}][15:8] = \'z;'
                         for address in addresses)
        tb = folder / 'tb.sv'
        tb.write_text(f'''module tb;
    localparam integer p_read_addr_width = 7;
    logic [11:0] rd_word_addr;
    logic [{width-1}:0] read_words [0:127];
    logic [{width-1}:0] reference_data, read_data_next;
    always_comb begin
        reference_data = '0;
        case (rd_word_addr)
{old_cases}
            default: begin end
        endcase
    end
    always_comb begin
{selection}
    end
    initial begin
        for (integer word = 0; word < 128; word++) read_words[word] = '0;
        for (integer sample = 0; sample < 11264; sample++) begin
{fill}
            if (sample < 4096) rd_word_addr = 12'(sample);
            else if (sample < 7168) begin
                rd_word_addr = 12'((sample - 4096) / 24);
                if (sample % 2) rd_word_addr[((sample - 4096) % 24) / 2] = 1'bx;
                else rd_word_addr[((sample - 4096) % 24) / 2] = 1'bz;
            end else begin
                rd_word_addr = 12'($urandom);
                if (sample % 3 == 0) rd_word_addr[$urandom_range(0, 11)] = 1'bx;
                if (sample % 5 == 0) rd_word_addr[$urandom_range(0, 11)] = 1'bz;
            end
            #1;
            if (reference_data !== read_data_next) $fatal(1, "Read selection differs sample=%0d address=%h", sample, rd_word_addr);
        end
        $display("AXIL_READ_FOUR_STATE_PASS samples=11264 width={width}");
        $finish;
    end
endmodule
''')
        with (folder / 'compile.log').open('w') as stream:
            subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(folder / 'sim'), str(tb)],
                           stdout=stream, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run(['vvp', str(folder / 'sim')], text=True, capture_output=True, check=True)
        (folder / 'run.log').write_text(result.stdout + result.stderr)
        assert 'AXIL_READ_FOUR_STATE_PASS' in result.stdout
        results.append({'data_width': width, 'samples': 11264, 'passed': True})
        print(json.dumps(results[-1]), flush=True)
    width_first = current.index('    localparam int p_shared_count_width')
    width_last = current.index(';', width_first) + 1
    width_expression = current[width_first:width_last]
    valid_first = current.index('    wire shared_allocation_valid =')
    valid_last = current.index(';', valid_first) + 1
    valid_expression = current[valid_first:valid_last]
    bank_tb = out / 'bank_tb.sv'
    bank_module = """module bank_check #(parameter logic [31:0] SHARED_IA_BANK_MASK = 6)(
    input logic clk, rst_n, input logic [31:0] shared_ia_banks_next);
    localparam bit SHARED_CAPABLE = 1'b1;
    logic [31:0] reference_value, current_value;
""" + width_expression + '\n' + valid_expression + """
    always @(posedge clk) begin
        if (!rst_n) begin reference_value <= 1; current_value <= 1; end
        else if (shared_allocation_valid) begin
            reference_value <= shared_ia_banks_next;
            current_value <= 32'(shared_ia_banks_next[p_shared_count_width-1:0]);
        end
    end
    always @(negedge clk) begin
        if (reference_value !== current_value) $fatal(1, "Bank value differs mask=%h", SHARED_IA_BANK_MASK);
    end
endmodule
module tb;
    logic clk=0, rst_n;
    logic [31:0] next_value;
"""
    masks = [2, 6, 18, 130, 32770, 2147483650, 4294967295]
    instances = '\n'.join(f"    bank_check #(32'h{mask:08x}) u_bank{index}(clk, rst_n, next_value);"
                           for index, mask in enumerate(masks))
    bank_tb.write_text(bank_module + instances + """
    initial begin
        for (integer sample=0; sample<100004; sample++) begin
            rst_n = sample>2 && sample%997>2;
            next_value = sample%3 ? 32'($urandom_range(0,39)) : $urandom;
            if (sample%11==0) next_value[$urandom_range(0,31)] = 1'bx;
            if (sample%13==0) next_value[$urandom_range(0,31)] = 1'bz;
            #1; clk=1; #1; clk=0; #1;
        end
        $display("AXIL_BANK_FOUR_STATE_PASS samples=100004 masks=7");
        $finish;
    end
endmodule
""")
    with (out / 'bank_compile.log').open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(out / 'bank_sim'), str(bank_tb)],
                       stdout=stream, stderr=subprocess.STDOUT, check=True)
    bank_run = subprocess.run(['vvp', str(out / 'bank_sim')], text=True, capture_output=True, check=True)
    (out / 'bank_run.log').write_text(bank_run.stdout + bank_run.stderr)
    assert 'AXIL_BANK_FOUR_STATE_PASS' in bank_run.stdout
    (out / 'summary.json').write_text(json.dumps({'passed': True, 'profiles': results,
        'address_states': ['0', '1', 'x', 'z'], 'data_states': ['0', '1', 'x', 'z'],
        'decoded_addresses': len(addresses), 'unchanged_word_assignments': assignments,
        'bank_masks': masks, 'bank_samples': 100004,
        'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
        'reference_sha256': hashlib.sha256(original.encode()).hexdigest()}, indent=2) + '\n')


if __name__ == '__main__':
    main()
