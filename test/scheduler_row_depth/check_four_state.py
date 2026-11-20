#!/usr/bin/env python3
"""检查实际列数取整、行地址和控制计数算术的四态结果位。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from prove import ROOT, SOURCE, HELPERS, REFERENCE, digest, read_rtl_source

PROFILES = [(1, 1), (4, 4), (16, 32), (16, 0), (16, 64)]


def compatible(text):
    return text.replace('parameter int unsigned', 'parameter integer').replace('localparam int unsigned', 'localparam integer')


def model(source, label, size, reuse):
    frames = 1 if size == 1 else 3 if size == 4 else 17 if reuse == 64 else 16
    first = source.index('    if (SHIFT == 0) begin : g_single_column')
    last = source.index('    assign current_rows', first)
    column = source[first:last]
    header = f'''module {label}(
    input wire [31:0] row_base,stream_rows_remaining,stationary_rows,
    input wire [({reuse}!=0?$clog2({reuse}*{size}+1):32)-1:0] current_rows,
    input wire [32:0] opened_input,active_input,column_input,column_total,k_input,
    input wire [4:0] slice_shift_input,
    output wire [294:0] result
);
    localparam SIZE={size},MAX_REUSE_TILES={reuse},SHIFT=$clog2(SIZE),TILE_W=32-SHIFT;
    localparam ID_W=({frames}>1)?$clog2({frames}):1;
    localparam ROW_PART_W=MAX_REUSE_TILES>1?$clog2(MAX_REUSE_TILES):MAX_REUSE_TILES==1?1:TILE_W;
    localparam ROW_COUNT_W=MAX_REUSE_TILES!=0?$clog2(MAX_REUSE_TILES*SIZE+1):32;
    localparam SLICE_SHIFT_W=ROW_COUNT_W>2?$clog2(ROW_COUNT_W):1;
    localparam PART_MATH_W=ROW_COUNT_W>(ROW_PART_W+1)?ROW_COUNT_W:(ROW_PART_W+1);
    wire [ID_W:0] opened=opened_input;
    wire [ID_W:0] opened_after_init,active_after_frame;
    wire [ID_W-1:0] active_id=active_input;
    wire [TILE_W:0] next_column_tile=column_input,column_tiles=column_total;
    wire [TILE_W:0] column_after_part,remaining_columns;
    wire [TILE_W-1:0] k_word=k_input;
    wire [TILE_W-1:0] active_frame_k,frame_k_after_command;
    wire [ROW_COUNT_W-1:0] prepare_rows=current_rows;
    wire [SLICE_SHIFT_W-1:0] slice_shift=slice_shift_input;
    wire [PART_MATH_W-1:0] prepare_rows_extended,prepare_rows_last_value,prepare_rows_last;
    wire [PART_MATH_W-1:0] prepare_part_quotient,prepare_part_rounded;
    wire [ROW_PART_W:0] result_parts;
    wire [TILE_W:0] remaining_columns_i_a,remaining_columns_i_b,remaining_columns_o_sum;
    wire remaining_columns_i_carry,remaining_columns_o_carry;
    wire [96:0] row_results;
    wire [TILE_W:0] incoming_column_tiles;
    wire [31:0] row_advance_i_a,row_advance_i_b,row_advance_o_sum;
    wire row_advance_i_carry,row_advance_o_carry;
    wire [31:0] stream_remaining_i_a,stream_remaining_i_b,stream_remaining_o_sum;
    wire stream_remaining_i_carry,stream_remaining_o_carry;
'''
    if label == 'current':
        first = source.index('    assign row_advance_i_a =')
        last = source.index('    function automatic logic [31:0] minimum', first)
        arithmetic = source[first:last]
        first = source.index('    assign opened_after_init[0] =')
        last = source.index('    // 初始切片偏移与帧索引同时保存',first)
        counters = source[first:last].replace('frame_k[active_id]','k_word')
        first = source.index('    assign prepare_rows_extended =')
        last = source.index('    always_ff @(posedge clk)',first)
        parts = source[first:last]
        capture = "PART_MATH_W'(ROW_COUNT_W'(minimum(32'(cfg_rows), stream_rows_remaining)))"
        assert parts.count(capture)==1
        parts = parts.replace(capture,"PART_MATH_W'(prepare_rows)")
        parts += "    assign prepare_rows_last=prepare_rows_last_value;\n    assign result_parts=(ROW_PART_W+1)'(prepare_part_rounded);\n"
        first = source.index('    assign remaining_columns_i_a =')
        last = source.index('    assign group_parts =',first)
        columns = source[first:last]
    else:
        match = re.findall(r'row_base <= (row_base \+ current_rows);', source)
        assert len(match) == 1
        arithmetic = f'''    assign row_advance_o_sum = {match[0]};
    assign stream_remaining_o_sum = stream_rows_remaining - 32'(current_rows);
'''
        opened = re.search(r"opened <= (opened \+ [^;]+);",source)[1]
        active = re.search(r"\(ID_W\+1\)'\(active_id\) \+ \(ID_W\+1\)'\(1\)",source)[0]
        col = re.search(r"next_column_tile <= (next_column_tile \+ [^;]+);",source)[1]
        k = re.search(r"frame_k\[active_id\] <= active_init \? TILE_W'\(1\) : ([^;]+);",source)[1].replace('frame_k[active_id]','k_word')
        part = re.search(r"prepare_parts <= sliced \? (.*?) : \(ROW_PART_W\+1\)'\(1\);",source)[1]
        diff = re.search(r'assign remaining_columns = (.*?);',source)[1]
        counters = f'''    assign opened_after_init={opened};
    assign active_after_frame={active};
    assign column_after_part={col};
    assign frame_k_after_command={k};
'''
        parts = f'    assign result_parts={part};\n'
        columns = f'    assign remaining_columns={diff};\n'
    return header + arithmetic + counters + parts + columns + column + '''
    assign row_results={row_advance_o_sum,stream_remaining_o_sum,incoming_column_tiles};
    assign result={33'(opened_after_init),33'(active_after_frame),33'(column_after_part),
        33'(frame_k_after_command),33'(result_parts),33'(remaining_columns),row_results};
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    helper = out / 'parallel_prefix_add.sv'
    helper.write_text(compatible((ROOT / HELPERS[1]).read_text()))
    report = {'passed': False, 'source_sha256': digest(ROOT / SOURCE),
              'reference_sha256': hashlib.sha256(original.encode()).hexdigest(),
              'helper_sha256': {name:digest(ROOT / name) for name in HELPERS},
              'scope': 'actual column rounding, row arithmetic, counter increments, column difference and slice rounding; slice decrement is observed at the captured row value',
              'property': 'every known reference result bit is preserved; unknown reference bits may resolve',
              'strict_four_state_equivalence': False, 'profiles': []}
    for size,reuse in PROFILES:
        folder = out / f's{size}_r{reuse}'
        folder.mkdir(exist_ok=True)
        models = []
        for label,source in [('reference',original),('current',current)]:
            path = folder / (label + '.sv')
            path.write_text(model(source,label,size,reuse))
            models.append(path)
        width = (reuse*size).bit_length() if reuse else 32
        tb = folder / 'tb.sv'
        tb.write_text(f'''module tb;
localparam W=96+{width}+170;
reg [W-1:0] inputs;
wire [294:0] reference_value,current_value;
integer seed=32'h213f7a91;
integer checks=0,known_bits=0,refined_bits=0,unknown_bits=0;
reference u_reference(.row_base(inputs[31:0]),.stream_rows_remaining(inputs[63:32]),
    .stationary_rows(inputs[95:64]),.current_rows(inputs[96+:{width}]),
    .opened_input(inputs[96+{width}+:33]),.active_input(inputs[129+{width}+:33]),
    .column_input(inputs[162+{width}+:33]),.column_total(inputs[195+{width}+:33]),
    .k_input(inputs[228+{width}+:33]),.slice_shift_input(inputs[261+{width}+:5]),.result(reference_value));
current u_current(.row_base(inputs[31:0]),.stream_rows_remaining(inputs[63:32]),
    .stationary_rows(inputs[95:64]),.current_rows(inputs[96+:{width}]),
    .opened_input(inputs[96+{width}+:33]),.active_input(inputs[129+{width}+:33]),
    .column_input(inputs[162+{width}+:33]),.column_total(inputs[195+{width}+:33]),
    .k_input(inputs[228+{width}+:33]),.slice_shift_input(inputs[261+{width}+:5]),.result(current_value));
initial begin
  for(integer sample_i=0;sample_i<8192;sample_i=sample_i+1) begin
    for(integer bit_i=0;bit_i<W;bit_i=bit_i+1) begin
      case(sample_i<256 ? 2 : ($random(seed)&15))
        0: inputs[bit_i]=1'bx;
        1: inputs[bit_i]=1'bz;
        default: inputs[bit_i]=$random(seed);
      endcase
    end
    if(sample_i==0) inputs='0;
    if(sample_i==1) inputs='1;
    #1;
    checks=checks+1;
    for(integer bit_i=0;bit_i<295;bit_i=bit_i+1) begin
      if(reference_value[bit_i]===1'b0 || reference_value[bit_i]===1'b1) begin
        known_bits=known_bits+1;
        if(current_value[bit_i]!==reference_value[bit_i])
          $fatal(1,"Known result mismatch sample=%0d bit=%0d ref=%h current=%h",
                 checks,bit_i,reference_value,current_value);
      end else if(current_value[bit_i]===1'b0 || current_value[bit_i]===1'b1)
        refined_bits=refined_bits+1;
      else unknown_bits=unknown_bits+1;
    end
  end
  $display("FOUR_STATE_PASS checks=%0d known_bits=%0d refined_bits=%0d unknown_bits=%0d",
           checks,known_bits,refined_bits,unknown_bits);
  $finish;
end
endmodule
''')
        binary = folder / 'four_state.vvp'
        command = ['iverilog','-g2012','-s','tb','-o',str(binary)] + [str(p) for p in models+[helper,tb]]
        with (folder / 'build.log').open('w') as stream:
            subprocess.run(command,check=True,stdout=stream,stderr=subprocess.STDOUT,timeout=60)
        result = subprocess.run(['vvp',str(binary)],capture_output=True,text=True,timeout=60)
        (folder / 'run.log').write_text(result.stdout+result.stderr)
        match = re.search(r'FOUR_STATE_PASS checks=(\d+) known_bits=(\d+) refined_bits=(\d+) unknown_bits=(\d+)',result.stdout)
        assert result.returncode == 0 and match,result.stdout+result.stderr
        row = {'SIZE':size,'MAX_REUSE_TILES':reuse,'passed':True,
               **dict(zip(['checks','known_bits','refined_bits','unknown_bits'],map(int,match.groups()))),
               'build_command':command,'run_log_sha256':digest(folder/'run.log'),
               'model_sha256':{p.name:digest(p) for p in models+[helper,tb]}}
        report['profiles'].append(row)
        print(json.dumps({key:row[key] for key in ['SIZE','MAX_REUSE_TILES','passed','checks']}),flush=True)
    assert (ROOT / SOURCE).read_text() == current
    report['passed']=True
    report['checks']=sum(row['checks'] for row in report['profiles'])
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    main()
