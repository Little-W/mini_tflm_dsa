#!/usr/bin/env python3
"""验证前端三种窗口步长匹配，并生成寄存器之间的局部综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
from source_sections import read_module, declarations
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log, timeout=180):
    with log.open('w') as output:
        result = subprocess.run(command, cwd=ROOT, stdout=output,
                                stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(str(log))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--vectors', type=int, default=120000)
    args = parser.parse_args()
    if args.vectors < 256:
        parser.error('--vectors must be at least 256')
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source, text = read_module(root, 'descriptor')
    helper = root/'rtl/common/add_equal.sv'
    hashes = {str(path.relative_to(root)): digest(path) for path in (source, helper)}
    first = text.index('  assign negative_group =')
    last = text.index('  // 空间分块起点', first)
    unknown_difference = re.search(r'`ifndef SYNTHESIS\s*logic \[32:0\] reduction_difference;'
                                   r'.*?`endif', text, re.S)[0]
    actual = (declarations(text, ('negative_group', 'target_difference', 'target_difference_match'))+
              unknown_difference+'\n'+text[first:last]).replace('c.group_c', 'group_c')
    ports = '''(
 input logic [31:0] tile_q0,window_next_q,
 input logic [15:0] group_c,last_group_channel_q,
 output logic [2:0] o_match
);
'''
    models = out/'window_match.sv'
    models.write_text('module window_match_actual'+ports+'''
 logic [3:1] incoming_tap_match_o_equal;
'''+actual+'''
 assign o_match=incoming_tap_match_o_equal[3:1];
endmodule

module window_match_mathematical'''+ports+'''
 logic [16:0] negative_group;
 logic [32:0] difference_value;
 assign negative_group={|group_c,~last_group_channel_q};
 assign difference_value={1'b0,tile_q0}-{1'b0,window_next_q};
 assign o_match[0]=difference_value=={17'd0,group_c};
 assign o_match[1]=difference_value=={{16{negative_group[16]}},negative_group};
 assign o_match[2]=difference_value=={{15{negative_group[16]}},negative_group,1'b0};
endmodule

module comparison(
 input logic [31:0] tile_q0,window_next_q,
 input logic [15:0] group_c,last_group_channel_q,
 output logic equivalent
);
 logic [2:0] actual_matches,expected_matches;
 window_match_actual u_actual(.tile_q0,.window_next_q,.group_c,.last_group_channel_q,
     .o_match(actual_matches));
 window_match_mathematical u_expected(.tile_q0,.window_next_q,.group_c,.last_group_channel_q,
     .o_match(expected_matches));
 assign equivalent=actual_matches==expected_matches;
endmodule
''')
    script, formal_log = out/'formal.ys', out/'formal.log'
    script.write_text('read_slang -D SYNTHESIS=1 --top comparison '+
                      shlex.join(map(str, (helper, models)))+
                      '\nprep -top comparison -flatten\ncheck -assert\n'
                      'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
         '--worker', str(script)], formal_log)
    if 'SUCCESS!' not in formal_log.read_text():
        raise RuntimeError(str(formal_log))
    bench = out/'tb_window_match.sv'
    bench.write_text('''module tb;
 logic [31:0] tile_q0,window_next_q;
 logic [15:0] group_c,last_group_channel_q;
 logic [2:0] actual_matches,expected_matches;
 logic [95:0] sample;
 logic [31:0] random_state;
 integer vector_index,bit_index,unknown_index,known_vectors,unknown_vectors;
 window_match_actual u_actual(.tile_q0,.window_next_q,.group_c,.last_group_channel_q,
     .o_match(actual_matches));
 window_match_mathematical u_expected(.tile_q0,.window_next_q,.group_c,.last_group_channel_q,
     .o_match(expected_matches));
 function automatic [31:0] random_word(input logic unused);
   random_state=random_state^(random_state<<13);
   random_state=random_state^(random_state>>17);
   random_state=random_state^(random_state<<5);
   return random_state;
 endfunction
 initial begin
   random_state=32'h7251abc9;known_vectors=0;unknown_vectors=0;
   for(vector_index=0;vector_index<VECTORS;vector_index=vector_index+1)begin
     sample={random_word(1'b0),random_word(1'b0),random_word(1'b0)};
     // 定向样本覆盖零通道、最大通道和三十二位边界附近的三个步长。
     if(vector_index%4!=0)begin
       case(vector_index%8)
         0:sample[15:0]=16'd0;
         1:sample[15:0]=16'd1;
         2:sample[15:0]=16'hffff;
         default:;
       endcase
       sample[31:16]=sample[15:0]-16'd1;
       case(vector_index%7)
         0:sample[63:32]=32'd0;
         1:sample[63:32]=32'hffffffff;
         2:sample[63:32]=32'h80000000;
         3:sample[63:32]=32'h7fffffff;
         default:;
       endcase
       case(vector_index%3)
         0:sample[95:64]=sample[63:32]+32'(sample[15:0]);
         1:sample[95:64]=sample[63:32]-32'(sample[15:0]);
         2:sample[95:64]=sample[63:32]-(32'(sample[15:0])<<1);
       endcase
     end
     if(vector_index%2==1)begin
       unknown_index=int'(random_word(1'b0)%96);
       sample[unknown_index]=vector_index%4==1?1'bx:1'bz;
       if(vector_index%5==0)begin
         bit_index=int'(random_word(1'b0)%96);
         sample[bit_index]=1'bx;
       end
       unknown_vectors=unknown_vectors+1;
     end else known_vectors=known_vectors+1;
     {tile_q0,window_next_q,last_group_channel_q,group_c}=sample;
     #1;
     if(actual_matches!==expected_matches)
       $fatal(1,"window match vector=%0d input=%h actual=%b expected=%b",
              vector_index,sample,actual_matches,expected_matches);
   end
   $display("WINDOW_MATCH_PASS vectors=%0d known=%0d unknown=%0d flags=%0d",
            VECTORS,known_vectors,unknown_vectors,3*VECTORS);
   $finish;
 end
endmodule
'''.replace('VECTORS', str(args.vectors)))
    executable, compile_log, numeric_log = out/'window_match.vvp', out/'compile.log', out/'numeric.log'
    run(['iverilog', '-g2012', '-s', 'tb', '-o', str(executable),
         str(helper), str(models), str(bench)], compile_log)
    run(['vvp', str(executable)], numeric_log)
    match = re.search(r'WINDOW_MATCH_PASS vectors=(\d+) known=(\d+) unknown=(\d+) flags=(\d+)',
                      numeric_log.read_text())
    if not match:
        raise RuntimeError(str(numeric_log))

    wrappers = out/'registered_window_match.sv'
    wrapper_text = ''
    cases = {}
    for mode in ('actual', 'mathematical'):
        top = f'registered_window_match_{mode}'
        wrapper_text += f'''module {top}(
 input logic clk,
 input logic [95:0] inputs,
 output logic [2:0] o_match
);
 logic [95:0] inputs_q;
 logic [2:0] matches_next;
 always_ff @(posedge clk)begin
   inputs_q<=inputs;
   o_match<=matches_next;
 end
 window_match_{mode} u_match(
   .tile_q0(inputs_q[95:64]),.window_next_q(inputs_q[63:32]),
   .last_group_channel_q(inputs_q[31:16]),.group_c(inputs_q[15:0]),
   .o_match(matches_next));
endmodule
'''
        cases[top] = {'top': top, 'options': ['-D', 'SYNTHESIS=1'],
                      'sources': list(map(str, (helper, models, wrappers))),
                      'configuration': '96-bit unconstrained input, three 33-bit modular step o_match, registered input and output'}
    wrappers.write_text(wrapper_text)
    (out/'cases.json').write_text(json.dumps(cases, indent=2)+'\n')
    if hashes != {str(path.relative_to(root)): digest(path) for path in (source, helper)}:
        raise RuntimeError('Source changed during validation')
    report = {'passed': True, 'source_sha256': hashes,
              'formal': {'passed': True, 'input_bits': 96, 'inputs_constrained': False,
                         'output_bits': 3, 'log_sha256': digest(formal_log)},
              'four_state': {'passed': True, 'vectors': int(match[1]),
                             'known_vectors': int(match[2]), 'unknown_vectors': int(match[3]),
                             'flag_comparisons': int(match[4]), 'log_sha256': digest(numeric_log)},
              'generated_sha256': {p.name: digest(p) for p in (models, bench, wrappers)},
              'scope': '实际窗口匹配表达式的完整三十三位模运算，包含 X/Z 输入的事件仿真语义'}
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
