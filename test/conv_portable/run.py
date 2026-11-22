#!/usr/bin/env python3
"""验证独立卷积算术模块与权重存储的参数行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log: Path, timeout=180):
    with log.open('w') as output:
        result = subprocess.run(list(map(str, command)), cwd=ROOT, stdout=output,
                                stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(str(log) + '\n' + log.read_text()[-5000:])


FORMAL = {
    'address': ('vector_read_address_add', '''
 input logic clk,
 input logic [31:0] base,offset,
 input logic [15:0] channel,
 output logic equivalent
);
 logic [31:0] actual;
 logic [1:0] carry;
 logic [33:0] expected;
 vector_read_address_add u_dut(.clk,.i_base(base),.i_offset(offset),.i_channel(channel),
                              .o_address(actual),.o_carry(carry));
 assign expected={2'b0,base}+{2'b0,offset}+{18'd0,channel};
 assign equivalent={carry,actual}==expected;
endmodule
'''),
    'reduce': ('vector_reduce_alu', '''
 input logic clk,
 input logic signed [31:0] lhs,rhs,
 input logic maximum,minimum,
 output logic equivalent
);
 logic signed [31:0] actual,expected;
 vector_reduce_alu u_dut(.clk,.i_lhs(lhs),.i_rhs(rhs),.i_max(maximum),.i_min(minimum),.o_result(actual));
 always_comb begin
   expected=lhs+rhs;
   if(maximum)expected=lhs>rhs?lhs:rhs;
   if(minimum)expected=lhs<rhs?lhs:rhs;
 end
 assign equivalent=actual==expected;
endmodule
'''),
    'coordinate': ('vector_coordinate_bound', '''
 input logic signed [33:0] coordinate,
 input logic [15:0] limit,
 output logic equivalent
);
 logic actual;
 vector_coordinate_bound u_dut(.i_coordinate(coordinate),.i_limit(limit),.o_in_bounds(actual));
 assign equivalent=actual==(coordinate>=34'sd0 && coordinate<$signed({18'd0,limit}));
endmodule
'''),
    'interval': ('vector_interval_bound', '''
 input logic signed [16:0] coordinate,minimum,maximum,
 output logic equivalent
);
 logic actual;
 vector_interval_bound u_dut(.i_coordinate(coordinate),.i_minimum(minimum),.i_maximum(maximum),.o_inside(actual));
 assign equivalent=actual==(coordinate>=minimum && coordinate<maximum);
endmodule
'''),
}

MEMORY_BENCH = r'''
module tb;
 localparam int DEPTH=DEPTH_VALUE, CHANNELS=CHANNELS_VALUE;
 logic clk=0,write_enable=0;
 logic [31:0] write_address=0,read_address=0;
 logic [CHANNELS-1:0] write_mask='0;
 logic [8*CHANNELS-1:0] write_data='0;
 wire [8*CHANNELS-1:0] row_data;
 wire signed [7:0] byte_data;
 logic [8*CHANNELS-1:0] rows[DEPTH],expected_row;
 logic [7:0] bytes[DEPTH],expected_byte;
 integer checks=0,seed;
 vector_weight_store #(.p_channels(CHANNELS),.p_depth(DEPTH)) u_rows(
   .clk,.i_wr_en(write_enable),.i_wr_tap(write_address),.i_wr_mask(write_mask),
   .i_wr_data(write_data),.i_rd_tap(read_address),.o_rd_data(row_data));
 vector_weight_bank #(.DEPTH(DEPTH)) u_bytes(
   .clk,.write_enable,.write_address,.read_address,
   .write_data(write_data[7:0]),.read_data(byte_data));
 task automatic step;
   clk=0;
   #1;
   // 同步整行读取采样写入前的数据，异步字节读取反映写入后的内容。
   expected_row=read_address<DEPTH?rows[read_address]:'0;
   if(write_enable && write_address<DEPTH)begin
     for(int lane=0;lane<CHANNELS;lane++)begin
       if(write_mask[lane])rows[write_address][8*lane+:8]=write_data[8*lane+:8];
     end
     bytes[write_address]=write_data[7:0];
   end
   expected_byte=read_address<DEPTH?bytes[read_address]:8'd0;
   clk=1;
   #1;
   if(row_data!==expected_row || byte_data!==expected_byte)
     $fatal(1,"weight storage mismatch depth=%0d channels=%0d cycle=%0d read=%h actual=%h expected=%h byte=%h expected_byte=%h",
            DEPTH,CHANNELS,checks,read_address,row_data,expected_row,byte_data,expected_byte);
   checks+=2;
   clk=0;
   #1;
 endtask
 initial begin
   seed=32'h71a3c590;seed=$urandom(seed);
   for(int index=0;index<DEPTH;index++)begin
     write_enable=1;write_address=index;read_address=index;write_mask='1;
     for(int lane=0;lane<CHANNELS;lane++)write_data[8*lane+:8]=8'($urandom());
     step();
   end
   for(int sample=0;sample<20000;sample++)begin
     write_enable=$urandom_range(0,1);
     write_address=$urandom_range(0,DEPTH+3);
     read_address=sample%3==0?write_address:$urandom_range(0,DEPTH+3);
     for(int lane=0;lane<CHANNELS;lane++)begin
       write_data[8*lane+:8]=8'($urandom());
       write_mask[lane]=$urandom_range(0,1);
     end
     case(sample%23)
       0:write_enable=1'bx;
       1:write_enable=1'bz;
       2:write_mask[$urandom_range(0,CHANNELS-1)]=1'bx;
       3:write_mask[$urandom_range(0,CHANNELS-1)]=1'bz;
       4:write_data[$urandom_range(0,8*CHANNELS-1)]=1'bx;
       5:write_data[$urandom_range(0,8*CHANNELS-1)]=1'bz;
       6:write_address[0]=1'bx;
       7:read_address[0]=1'bx;
       8:write_address[31]=1'b1;
       9:read_address[31]=1'b1;
       default:;
     endcase
     step();
   end
   $display("WEIGHT_STORAGE_PASS depth=%0d channels=%0d checks=%0d",DEPTH,CHANNELS,checks);
   $finish;
 end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--only', choices=[*FORMAL, 'weights'])
    args = parser.parse_args()
    source = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = {'passed': False, 'input_constraints': None, 'formal': [], 'storage': [],
              'source_sha256': {}}
    selected = [args.only] if args.only else [*FORMAL, 'weights']
    for name in selected:
        if name == 'weights':
            continue
        module, body = FORMAL[name]
        rtl = source / 'rtl/npu/conv' / (module + '.sv')
        dependencies = [rtl]
        if name in ('address', 'reduce'):
            dependencies.append(source / 'rtl/common/parallel_prefix_add.sv')
        for path in dependencies:
            report['source_sha256'][str(path)] = digest(path)
        harness = out / (name + '.sv')
        harness.write_text('module comparison(\n' + body)
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text('read_slang --top comparison ' + shlex.join(map(str, [*dependencies, harness])) +
                          '\nprep -top comparison -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        execute([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        assert 'SUCCESS!' in log.read_text(), log
        row = {'module': module, 'passed': True, 'log_sha256': digest(log)}
        report['formal'].append(row)
        print(json.dumps(row), flush=True)
    if 'weights' in selected:
        dependencies = [source/'rtl/npu/conv/vector_weight_store.sv',
                        source/'rtl/npu/conv/vector_weight_bank.sv', source/'rtl/common/regfile.v']
        for path in dependencies:
            report['source_sha256'][str(path)] = digest(path)
        for depth, channels in ((1, 1), (7, 4), (49, 16), (49, 32)):
            stem = f'weights_{depth}_{channels}'
            bench, binary = out / (stem + '.sv'), out / (stem + '.vvp')
            bench.write_text(MEMORY_BENCH.replace('DEPTH_VALUE', str(depth)).replace('CHANNELS_VALUE', str(channels)))
            execute(['iverilog', '-g2012', '-s', 'tb', '-o', binary, *dependencies, bench], out/(stem+'_build.log'))
            log = out / (stem + '.log')
            execute(['vvp', binary], log)
            assert 'WEIGHT_STORAGE_PASS' in log.read_text(), log
            row = {'depth': depth, 'channels': channels, 'checks': 2*(depth+20000),
                   'passed': True, 'log_sha256': digest(log)}
            report['storage'].append(row)
            print(json.dumps(row), flush=True)
    assert all(digest(Path(path)) == value for path, value in report['source_sha256'].items())
    report['passed'] = True
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
