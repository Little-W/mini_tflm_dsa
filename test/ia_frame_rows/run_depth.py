#!/usr/bin/env python3
"""证明尾组行数的并行借位与已保存预取资格保持完整 IA 时序行为。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/loaders/ia_loader.sv')
PROFILES = {
    'production': dict(SIZE=16, BUS_WIDTH=64, COUNT_WIDTH=29, CACHE_BLOCKS=32,
                       COMPACT_S8=0, ORDERED_JOB=1, p_dma_source_layout=1, p_shared_write_stage=1,
                       p_register_dma_request=1, RAM_WORD_ADDR_WIDTH=12),
    'compact': dict(SIZE=16, BUS_WIDTH=64, COUNT_WIDTH=29, CACHE_BLOCKS=32, COMPACT_S8=1,
                       ORDERED_JOB=1, p_dma_source_layout=1, p_shared_write_stage=1,
                       p_register_dma_request=1, RAM_WORD_ADDR_WIDTH=12),
    'generic': dict(SIZE=16, BUS_WIDTH=32, COUNT_WIDTH=8, CACHE_BLOCKS=4, ORDERED_JOB=0),
    'full_count': dict(SIZE=16, BUS_WIDTH=32, COUNT_WIDTH=32, CACHE_BLOCKS=4, ORDERED_JOB=1),
    'short_count': dict(SIZE=16, BUS_WIDTH=32, COUNT_WIDTH=5, CACHE_BLOCKS=4, ORDERED_JOB=1),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log, timeout=300):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, check=True,
                       stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)


def tail_model(source, name):
    start = source.index('    assign frame_last_tiles =')
    end = source.index('    // =======================================================================', start)
    body = source[start:end]
    return f'''module {name} #(parameter SIZE=16, COUNT_WIDTH=29, REG_WIDTH=32,
 parameter LOG2_SIZE=$clog2(SIZE), p_frame_count_width=COUNT_WIDTH>0?COUNT_WIDTH:1)(
 input logic [REG_WIDTH-1:0] k, // 任意流式维度长度
 input logic [REG_WIDTH-1:0] row_tail_tiles, // 任意尾组分块数
 output logic [31:0] frame_last_rows_next // 当前配置的尾组有效行数
);
 logic [REG_WIDTH-1:0] ia_reuse_num_act_comb, rsp_rows_last_tile_comb;
 logic [p_frame_count_width-1:0] frame_last_tiles;
 assign ia_reuse_num_act_comb=row_tail_tiles;
 if(SIZE>1 && (SIZE&(SIZE-1))==0)begin
  assign rsp_rows_last_tile_comb=(k[LOG2_SIZE-1:0]=='0)?REG_WIDTH'(SIZE):REG_WIDTH'(k[LOG2_SIZE-1:0]);
 end else begin
  assign rsp_rows_last_tile_comb=SIZE-((((k+SIZE-1)>>LOG2_SIZE)<<LOG2_SIZE)-k);
 end
'''+body+'\nendmodule\n'


def four_state(reference, current):
    profiles = [(16, 5), (16, 8), (16, 29), (16, 32), (8, 16), (32, 8), (3, 16), (1, 32)]
    text = tail_model(reference, 'tail_reference') + tail_model(current, 'tail_current')
    text += '''module tb;
 reg [31:0] k,row_tail_tiles,global_rows,packed_tiles;
 integer checks=0;integer sample;
 reg [31:0] rng=32'h695e713b;
 function automatic [31:0] random_word;
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
 endfunction
 function automatic logic four(input logic [1:0] v);
  case(v)0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
 endfunction
 wire [31:0] original_prefetch=(global_rows=='0)?'0:packed_tiles;
 wire [31:0] selected_prefetch=(|global_rows)?packed_tiles:'0;
'''
    for index, (size, count) in enumerate(profiles):
        text += f'''wire [31:0] original{index},selected{index};
 tail_reference #(.SIZE({size}),.COUNT_WIDTH({count})) r{index}(k,row_tail_tiles,original{index});
 tail_current #(.SIZE({size}),.COUNT_WIDTH({count})) c{index}(k,row_tail_tiles,selected{index});
'''
    text += '''initial begin
 for(sample=0;sample<30000;sample++)begin
  k=random_word();row_tail_tiles=random_word();global_rows=random_word();packed_tiles=random_word();
  case(sample%19)
   0:begin k=0;row_tail_tiles=0;global_rows=0;end
   1:begin k='1;row_tail_tiles='1;global_rows='1;end
   2:begin k=16;row_tail_tiles=1;global_rows=16;end
   3:begin k=17;row_tail_tiles=2;global_rows=17;end
   4:k='x;
   5:k='z;
   6:row_tail_tiles='x;
   7:row_tail_tiles='z;
   8:global_rows='x;
   9:global_rows='z;
  endcase
  if(sample%5==0)begin
   for(integer bit_index=0;bit_index<32;bit_index++)begin
    k[bit_index]=four(2'(random_word()));
    row_tail_tiles[bit_index]=four(2'(random_word()));
    global_rows[bit_index]=four(2'(random_word()));
    packed_tiles[bit_index]=four(2'(random_word()));
   end
  end
  #1;
  if(original_prefetch!==selected_prefetch)$fatal(1,"Prefetch qualification differs");
  checks++;
'''
    for index in range(len(profiles)):
        text += f'  if(original{index}!==selected{index})$fatal(1,"Frame tail differs profile={index}");checks++;\n'
    text += '''end
 $display("IA_FRAME_DEPTH_FOUR_STATE_PASS checks=%0d",checks);$finish;
end
endmodule
'''
    return text.replace('always_comb', 'always @*')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-source', type=Path, default=ROOT/SOURCE)
    parser.add_argument('--reference', default='aa246aef')
    parser.add_argument('--cases', nargs='+', choices=tuple(PROFILES), default=list(PROFILES))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(['git', 'show', args.reference+':'+str(SOURCE)], cwd=ROOT, text=True)
    current = args.candidate_source.read_text()
    # 同名观察表达式仅描述原有寄存器内容，所有功能输入保持自由。
    marker = '    logic [REG_WIDTH-1:0] global_reduction_q;'
    reference = original.replace(marker, marker+
        '\n    (* keep=1 *) wire global_reduction_nonzero_q = |global_reduction_q;')
    assert marker in original
    paths = {'reference': out/'reference.sv', 'current': out/'current.sv'}
    paths['reference'].write_text(reference); paths['current'].write_text(current)
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    dependencies = {name: resolve([path], ROOT) for name, path in paths.items()}
    results = []
    for name in args.cases:
        parameters = PROFILES[name]
        commands = []
        options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']+[f'-G{k}={v}' for k,v in parameters.items()]
        for label in ['reference', 'current']:
            commands += ['read_slang --top ia_loader '+shlex.join(options+list(map(str, dependencies[label]))),
                         'prep -top ia_loader -flatten', 'memory_map', 'async2sync', 'opt_clean',
                         'rename ia_loader '+label, 'design -stash '+label]
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                     'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 3', 'equiv_status -assert']
        script, log = out/(name+'.ys'), out/(name+'.log'); script.write_text('\n'.join(commands)+'\n')
        execute([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', log.read_text())
        assert match and int(match[2]) == 0
        results.append({'profile': name, 'parameters': parameters, 'passed': True,
                        'equivalent_bits': int(match[1]), 'log_sha256': digest(log)})
        print('IA_FRAME_DEPTH_FORMAL_PASS', name, flush=True)
    bench = out/'four_state.sv'; bench.write_text(four_state(original, current))
    binary, log = out/'four_state.vvp', out/'four_state.log'
    execute(['iverilog', '-g2012', '-s', 'tb', '-o', binary, bench,
             ROOT/'rtl/common/parallel_prefix_add.sv'], out/'four_state_compile.log')
    execute(['vvp', binary], log)
    match = re.search(r'IA_FRAME_DEPTH_FOUR_STATE_PASS checks=(\d+)', log.read_text()); assert match
    report = {'passed': True, 'reference_revision': args.reference, 'inputs_constrained': False,
              'reference_sha256': hashlib.sha256(original.encode()).hexdigest(),
              'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'formal_profiles': results, 'formal_equivalent_bits': sum(r['equivalent_bits'] for r in results),
              'four_state': {'passed': True, 'tail_profiles': 8, 'samples': 30000,
                             'comparisons': int(match[1]), 'log_sha256': digest(log)},
              'test_sha256': digest(Path(__file__))}
    assert current == args.candidate_source.read_text()
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('IA_FRAME_DEPTH_ALL_PASS', flush=True)


if __name__ == '__main__':
    main()
