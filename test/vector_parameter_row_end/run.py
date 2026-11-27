#!/usr/bin/env python3
"""验证参数数组行末条件的参数范围、完整字节边界与四态传播。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'rtl/npu/conv/vector_parameter_row_end.sv'
CASES = ((2, 2, 4), (3, 2, 2), (4, 3, 4), (6, 5, 8),
         (7, 6, 16), (8, 7, 32), (31, 5, 8), (6, 31, 8))
MODES = (('generic', []), ('fpga', ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']))


def execute(command, log):
    with Path(log).open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=300)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    text = SOURCE.read_text()
    body = """
    vector_parameter_row_end #(
        .p_column_width(p_input_index_w), .p_active_width(p_active_count_w), .p_bus_bytes(p_bus_bytes)
    ) u_row_end (
        .i_column_base(rd_col_base), .i_active(active), .o_complete(parameter_row_complete)
    );
"""
    header = ''' #(
    parameter int p_input_index_w = 6,
    parameter int p_active_count_w = 5,
    parameter int p_bus_bytes = 8
) (
    input logic [p_input_index_w-1:0] rd_col_base, // 本拍返回数据的起始字节索引
    input logic [p_active_count_w-1:0] active, // 本行需要返回的四字节参数数量
    output logic o_last // 当前完整总线拍包含本行的末参数
);
    logic parameter_row_complete;
'''
    model = out / 'models.sv'
    model.write_text('// 比较完整字节表达式与生产参数行末条件。\nmodule reference' + header +
                     "assign parameter_row_complete = 32'(rd_col_base)+32'(p_bus_bytes)>=(32'(active)<<2);\n" +
                     'assign o_last = parameter_row_complete;\nendmodule\n' +
                     'module candidate' + header + body +
                     '\nassign o_last = parameter_row_complete;\nendmodule\n')
    resolve = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    sources = list(map(str, resolve([model], ROOT)))
    bench = out / 'tb.sv'
    bench.write_text('''`timescale 1ns/1ps
// 连续改变列索引、元素数与未知位，比较每次组合输出。
module tb;
parameter int COLUMN_WIDTH=6, ACTIVE_WIDTH=5, BUS_BYTES=8;
reg [COLUMN_WIDTH-1:0] rd_col_base;
reg [ACTIVE_WIDTH-1:0] active;
wire expected, actual;
integer seed=271127;
integer checks=0;
reference #(.p_input_index_w(COLUMN_WIDTH),.p_active_count_w(ACTIVE_WIDTH),.p_bus_bytes(BUS_BYTES)) ref_dut(.*,.o_last(expected));
candidate #(.p_input_index_w(COLUMN_WIDTH),.p_active_count_w(ACTIVE_WIDTH),.p_bus_bytes(BUS_BYTES)) dut(.*,.o_last(actual));
initial begin
    for (integer sample=0; sample<65536; sample=sample+1) begin
        rd_col_base=$random(seed);
        active=$random(seed);
        case (sample%16)
            0: begin active=0; rd_col_base=0; end
            1: begin active=1; rd_col_base='1; end
            2: active=ACTIVE_WIDTH'(BUS_BYTES/4);
            3: active=ACTIVE_WIDTH'(BUS_BYTES/4+1);
            4: rd_col_base[(sample>>4)%COLUMN_WIDTH]=1'bx;
            5: rd_col_base[(sample>>4)%COLUMN_WIDTH]=1'bz;
            6: active[(sample>>4)%ACTIVE_WIDTH]=1'bx;
            7: active[(sample>>4)%ACTIVE_WIDTH]=1'bz;
            8: begin rd_col_base='x; active=0; end
            9: begin rd_col_base='1; active='z; end
            10: begin rd_col_base=0; active='1; end
            11: begin rd_col_base='1; active='1; end
            default: begin end
        endcase
        #1;
        if (actual!==expected) $fatal(1,"参数行末条件不同，检查 %0d",checks);
        checks=checks+1;
    end
    $display("PASS comparisons=%0d",checks);
    $finish;
end
endmodule
''')
    results = []
    for mode, flags in MODES:
        for column, active, byte_count in CASES:
            name = f'{mode}_column{column}_active{active}_bytes{byte_count}'
            parameters = [f'-Gp_input_index_w={column}', f'-Gp_active_count_w={active}',
                          f'-Gp_bus_bytes={byte_count}']
            commands = []
            for label in ('reference', 'candidate'):
                commands += ['read_slang --top '+label+' '+shlex.join([*flags, *parameters, *sources]),
                             'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                             'prep -top '+label+' -flatten', 'opt -full', 'design -stash '+label]
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from candidate -as candidate candidate',
                         'equiv_make reference candidate proof', 'hierarchy -top proof',
                         'equiv_simple', 'equiv_status -assert']
            script, log = out/(name+'.ys'), out/(name+'_formal.log')
            script.write_text('\n'.join(commands)+'\n')
            execute([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
            executable = out/(name+'.vvp')
            execute(['iverilog','-g2012',*flags,'-s','tb',f'-Ptb.COLUMN_WIDTH={column}',
                     f'-Ptb.ACTIVE_WIDTH={active}',f'-Ptb.BUS_BYTES={byte_count}',
                     '-o',executable,*sources,bench],out/(name+'_compile.log'))
            simulation_log=out/(name+'_four_state.log')
            execute(['vvp',executable],simulation_log)
            if 'PASS comparisons=65536' not in simulation_log.read_text():
                raise RuntimeError(str(simulation_log))
            results.append({'mode':mode,'column_width':column,'active_width':active,
                            'bus_bytes':byte_count,'formal':True,'four_state_comparisons':65536,
                            'proof_log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
            print(name+' PASS',flush=True)
    if SOURCE.read_text()!=text:
        raise RuntimeError('验证期间生产源码发生变化')
    report={'passed':True,'input_assumptions':[],'all_output_bits_compared':True,
            'source_sha256':hashlib.sha256(text.encode()).hexdigest(),'cases':results,
            'four_state_comparisons':sum(item['four_state_comparisons'] for item in results)}
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
