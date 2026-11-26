#!/usr/bin/env python3
"""验证通道组边界化简与完整掩码末尾选择的组合结果。"""
from __future__ import annotations

from formal_compilation import slang_command

import argparse
import json
from pathlib import Path
import runpy
import shlex
import sys

from check_word_match import ROOT, bench, digest, run


def model(lanes, narrow, contiguous):
    width = (5*lanes+6)//2
    return f'''module match_proof(input logic [{width-1}:0] i_a,i_b,output logic equivalent);
logic [{lanes}:0] group_range,boundary;
logic [{lanes-1}:0] column_lane,active_lane,word_s8,word_s16,available;
logic narrow_output,past_active,word_output,input_s16,actual,reference_value;
assign {{group_range,column_lane,active_lane,word_s8,word_s16,narrow_output,past_active,word_output,input_s16}}={{i_a,i_b}};
assign boundary[0]=!group_range[0];
for(genvar lane=0;lane<{lanes};lane++)begin:g_lane
 assign boundary[lane+1]=group_range[lane]&&!group_range[lane+1];
 assign available[lane]=(!narrow_output||lane<{narrow})&&
  (past_active||(group_range[lane]&&active_lane[lane]))&&column_lane[lane]&&
  (!word_output||(input_s16?word_s16[lane]:word_s8[lane]));
end
conv_im2col_mask_end #(.p_lanes({lanes}),.p_contiguous({contiguous})) u_reference(
 .i_available(available),.i_boundary(boundary),.o_end(reference_value));
conv_stream_group_end #(.p_lanes({lanes}),.p_narrow_lanes({narrow}),.p_contiguous({contiguous})) u_actual(
 .i_group_range(group_range),.i_column_lane(column_lane),.i_active_lane(active_lane),
 .i_word_s8(word_s8),.i_word_s16(word_s16),.i_narrow_output(narrow_output),.i_past_active(past_active),
 .i_word_output(word_output),.i_input_s16(input_s16),.o_end(actual));
assign equivalent=actual===reference_value;
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=ROOT/'rtl/npu/conv/conv_stream_group_end.sv')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    dependencies = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = dependencies([args.source.resolve(), ROOT/'rtl/npu/conv/conv_im2col_mask_end.sv'], ROOT)
    hashes = {str(path): digest(path) for path in sources}
    simulation_sources = []
    for path in sources:
        target = out/('simulation_'+path.name)
        target.write_text(path.read_text().replace('parameter int unsigned', 'parameter integer').replace(
            'localparam int unsigned', 'localparam integer'))
        simulation_sources.append(target)
    proofs, simulations = [], []
    for lanes, narrow, contiguous in ((lanes, narrow, contiguous)
            for lanes, narrow in ((1, 1), (4, 2), (8, 8), (8, 4), (16, 8)) for contiguous in (0, 1)):
        name = f'lanes{lanes}_narrow{narrow}_contiguous{contiguous}'
        generated = out/(name+'.sv')
        generated.write_text(model(lanes, narrow, contiguous))
        script, log = out/(name+'.ys'), out/(name+'.log')
        script.write_text(slang_command()+'--top match_proof '+shlex.join([*map(str, sources), str(generated)])+
                         '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                         'prep -top match_proof -flatten\ncheck -assert\n'
                         'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise ValueError('组末边界化简形式证明未完成')
        proofs.append(dict(lanes=lanes, narrow=narrow, contiguous=contiguous, passed=True, log_sha256=digest(log)))
        width = (5*lanes+6)//2
        generated_bench = out/('tb_'+name+'.sv')
        generated_bench.write_text(bench(width))
        binary = out/(name+'.vvp')
        run(['iverilog', '-g2012', '-s', 'tb', '-o', binary,
             *simulation_sources, generated, generated_bench], out/('compile_'+name+'.log'))
        log = out/('simulation_'+name+'.log')
        run(['vvp', binary], log)
        checks = 2+32*(4*width+3)
        if f'WORD_MATCH_PASS width={width} checks={checks}' not in log.read_text():
            raise ValueError('组末边界化简四态检查未完成')
        simulations.append(dict(lanes=lanes, narrow=narrow, contiguous=contiguous, passed=True, checks=checks, log_sha256=digest(log)))
    if any(digest(path) != value for path, value in hashes.items()):
        raise ValueError('验证期间生产源码发生变化')
    report = dict(passed=True, input_assumptions=[], source_sha256=hashes,
                  formal=proofs, four_state=simulations)
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('GROUP_END_PASS formal='+str(len(proofs))+
          ' four_state='+str(sum(row['checks'] for row in simulations)))


if __name__ == '__main__':
    main()
