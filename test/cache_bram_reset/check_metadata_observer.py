#!/usr/bin/env python3
"""对实际元数据写事件记录执行四态存储对照。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
FIELDS = [('valid', 1), ('tags', 25), ('fill_epoch', 10), ('hit_epoch', 10),
          ('fill_rank', 32), ('hit_rank', 32), ('hint_rank', 32)]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source_root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = source_root / 'rtl/npu/dma/cache/conv_cache_metadata_way.sv'
    if not source.exists():
        source = source_root / 'rtl/npu/dma/cache/conv_windowed_cache.sv'
    if not source.exists():
        source = source_root / 'rtl/npu/dma/cache/conv_read_cache.sv'
    regfile = source_root / 'rtl/common/regfile.v'
    text = source.read_text()
    start = text.index('    logic observed_valid [SETS];')
    end = text.index('    for (genvar metadata_set=0;', start)
    body = text[start:end].replace('u_rank_source.', 'rank_')
    body = body.replace('    wire [1:0] observed_rank_source [SETS];\n', '')
    declarations = ['logic clk=0; always #5 clk=~clk;']
    connections, instances, comparisons, updates = [], [], [], []
    for name, width in FIELDS:
        for suffix, bits in [('en', 1), ('addr', 'SI'), ('data', width), ('mask', 1)]:
            declarations.append(f'logic [{bits}-1:0] {name}_i_wr_{suffix};')
            connections.append(f'{name}_i_wr_{suffix}')
        declarations += [f'wire [SETS-1:0][{width}-1:0] {name}_reference;',
                         f'wire [SETS-1:0][SI-1:0] {name}_read_address;']
        instances.append(f'''for(genvar address=0;address<SETS;address++)begin:g_{name}_read
 assign {name}_read_address[address]=SI'(address);
end
regfile #(.p_data_width({width}),.p_depth(SETS),.p_addr_width(SI),.p_write_unit({width}),
 .p_read_ports(SETS),.p_sync_read(0)) u_{name}(
 .clk(clk),.i_wr_en({name}_i_wr_en),.i_wr_addr({name}_i_wr_addr),
 .i_wr_data({name}_i_wr_data),.i_wr_mask({name}_i_wr_mask),
 .i_rd_en({{SETS{{1'b1}}}}),.i_rd_addr({name}_read_address),.o_rd_data({name}_reference));''')
        comparisons.append(f'''if(observed_{name}[address] !== {name}_reference[address])
 $fatal(1,"metadata record mismatch {name} cycle=%0d address=%0d",cycle,address); checks++;''')
        updates += [f'{name}_i_wr_en=$urandom;', f'{name}_i_wr_mask=$urandom;',
                    f'{name}_i_wr_addr=$urandom;', f'{name}_i_wr_data=$urandom;']
        updates += [f'''case(cycle%19)
 0: {name}_i_wr_en=1'bx;
 1: {name}_i_wr_en=1'bz;
 2: {name}_i_wr_mask=1'bx;
 3: {name}_i_wr_mask=1'bz;
 4: {name}_i_wr_addr[cycle%SI]=1'bx;
 5: {name}_i_wr_addr[cycle%SI]=1'bz;
 6: {name}_i_wr_data[cycle%{width}]=1'bx;
 7: {name}_i_wr_data[cycle%{width}]=1'bz;
 default: begin end
endcase''']
    declarations += ['logic [2:0] rank_bank_i_wr_en;', 'logic [2:0][SI-1:0] rank_bank_i_wr_addr;',
                     'logic [2:0][1:0] rank_bank_i_wr_data;', 'logic rank_bank_i_wr_mask;',
                     'wire [SETS-1:0][SI-1:0] rank_read_address;',
                     'wire [SETS-1:0][1:0] rank_reference[3];']
    instances += ['''for(genvar address=0;address<SETS;address++)begin:g_rank_read
 assign rank_read_address[address]=SI'(address);
end
for(genvar bank=0;bank<3;bank++)begin:g_rank_reference
 regfile #(.p_data_width(2),.p_depth(SETS),.p_addr_width(SI),.p_write_unit(2),
 .p_read_ports(SETS),.p_sync_read(0)) u_bank(
 .clk(clk),.i_wr_en(rank_bank_i_wr_en[bank]),.i_wr_addr(rank_bank_i_wr_addr[bank]),
 .i_wr_data(rank_bank_i_wr_data[bank]),.i_wr_mask(rank_bank_i_wr_mask),
 .i_rd_en({SETS{1'b1}}),.i_rd_addr(rank_read_address),.o_rd_data(rank_reference[bank]));
end''']
    comparisons += ['''for(int bank=0;bank<3;bank++)begin
 if(observed_rank_bank[bank][address] !== rank_reference[bank][address])
  $fatal(1,"metadata source mismatch cycle=%0d bank=%0d address=%0d",cycle,bank,address);
 checks++;
end''']
    updates += ['''rank_bank_i_wr_en=$urandom; rank_bank_i_wr_addr=$urandom;
rank_bank_i_wr_data=$urandom; rank_bank_i_wr_mask=$urandom;
case(cycle%13)
 0: rank_bank_i_wr_en[0]=1'bx;
 1: rank_bank_i_wr_en[1]=1'bz;
 2: rank_bank_i_wr_mask=1'bx;
 3: rank_bank_i_wr_mask=1'bz;
 4: rank_bank_i_wr_addr[0][0]=1'bx;
 5: rank_bank_i_wr_addr[1][0]=1'bz;
 6: rank_bank_i_wr_data[2][0]=1'bx;
 7: rank_bank_i_wr_data[2][1]=1'bz;
 default: begin end
endcase''']
    template = '''module metadata_record_test;
localparam integer SETS=PARAM_SETS, SI=$clog2(SETS), p_tag_width=25, EPOCH_W=10;
integer checks=0;
DECLARATIONS
RECORDED_WRITES
REFERENCE_INSTANCES
initial begin
 for(int cycle=0;cycle<4096;cycle++)begin
  @(negedge clk);
  INPUT_UPDATES
  @(posedge clk); #1;
  for(int address=0;address<SETS;address++)begin
   OUTPUT_COMPARISONS
  end
 end
 $display("METADATA_RECORD_PASS sets=%0d cycles=4096 checks=%0d",SETS,checks);
 $finish;
end
endmodule
'''
    for marker, value in [('DECLARATIONS', declarations), ('RECORDED_WRITES', [body]),
                          ('REFERENCE_INSTANCES', instances), ('INPUT_UPDATES', updates),
                          ('OUTPUT_COMPARISONS', comparisons)]:
        template = template.replace(marker, '\n'.join(value))
    model = out / 'regfile.v'
    model.write_text(regfile.read_text().replace('parameter bit ', 'parameter ').replace(
        'parameter int ', 'parameter integer '))
    report = dict(passed=False, source_sha256=sha(source), regfile_sha256=sha(regfile), profiles=[])
    for sets in (2, 16, 128):
        testbench, binary = out / f's{sets}.sv', out / f's{sets}.vvp'
        testbench.write_text(template.replace('PARAM_SETS', str(sets)))
        log = out / f's{sets}_compile.log'
        with log.open('w') as stream:
            subprocess.run(['iverilog', '-g2012', '-s', 'metadata_record_test', '-o', str(binary),
                            str(model), str(testbench)], stdout=stream, stderr=subprocess.STDOUT, check=True)
        completed = subprocess.run(['vvp', str(binary)], capture_output=True, text=True, check=True)
        (out / f's{sets}_run.log').write_text(completed.stdout + completed.stderr)
        matched = re.search(r'METADATA_RECORD_PASS sets=(\d+) cycles=(\d+) checks=(\d+)', completed.stdout)
        assert matched and int(matched[1]) == sets
        entry = dict(sets=sets, passed=True, cycles=int(matched[2]), checks=int(matched[3]),
                     model_sha256=sha(testbench))
        report['profiles'].append(entry)
        print(json.dumps(entry), flush=True)
    assert report['source_sha256'] == sha(source) and report['regfile_sha256'] == sha(regfile)
    report.update(passed=True, checker_sha256=sha(Path(__file__)))
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
