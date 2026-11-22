#!/usr/bin/env python3
"""验证 IA 写入范围编码的完整输入与四态传播。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CASES = [(2, 1), (3, 1), (3, 2), (4, 1), (4, 2), (4, 4),
         (8, 1), (8, 2), (8, 3), (8, 4), (8, 8),
         (16, 1), (16, 2), (16, 3), (16, 4), (16, 8), (16, 16),
         (17, 4), (17, 8), (32, 4), (32, 8), (32, 16), (32, 32),
         (64, 4), (64, 8), (64, 32), (64, 64)]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(root, name):
    source = root / 'rtl/npu/loaders/ia_loader_cache_mgr.sv'
    text = source.read_text()
    start = text.index('  logic [ROW_CNT_W-1:0] write_extent,')
    stop = text.index('  always_ff @(posedge clk)', start)
    block = text[start:stop]
    return f'''module {name} #(parameter integer SIZE=16,DMA_LANES=8)(
      input logic [DMA_LANES-1:0] i_valid,
      input logic [$clog2(SIZE)-1:0] wr_col_base,
      output logic [$clog2(SIZE+1)-1:0] o_extent,
      output logic o_any);
      localparam integer LOG2_SIZE=$clog2(SIZE);
      localparam integer ROW_CNT_W=$clog2(SIZE+1);
      logic wr_valid[DMA_LANES];
      logic [SIZE-1:0] write_source_mask,write_shifted_mask;
      for(genvar lane=0;lane<DMA_LANES;lane++)begin:g_valid
        assign wr_valid[lane]=i_valid[lane];
      end
      for(genvar lane=0;lane<SIZE;lane++)begin:g_mask
        if(lane<DMA_LANES)begin:g_input
          assign write_source_mask[lane]=wr_valid[lane];
        end else begin:g_zero
          assign write_source_mask[lane]=1'b0;
        end
      end
      assign write_shifted_mask=write_source_mask<<wr_col_base;
    ''' + block + '''
      assign o_extent=write_extent;
      assign o_any=any_lane_write;
    endmodule
    '''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--tool-root', type=Path, default=ROOT)
    parser.add_argument('--reuse-results', type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    roots = {'reference': args.reference_root.resolve(), 'current': args.source_root.resolve()}
    hashes = {name: digest(root/'rtl/npu/loaders/ia_loader_cache_mgr.sv') for name, root in roots.items()}
    source = args.out/'extent.sv'
    source.write_text(''.join(extract(root, name) for name, root in roots.items()) + '''
      module proof #(parameter integer SIZE=16,DMA_LANES=8)(
        input logic [DMA_LANES-1:0] i_valid,
        input logic [$clog2(SIZE)-1:0] wr_col_base,
        output logic equivalent);
        logic [$clog2(SIZE+1)-1:0] old_extent,new_extent;
        logic old_any,new_any;
        reference #(.SIZE(SIZE),.DMA_LANES(DMA_LANES)) u_ref(
          .i_valid(i_valid),.wr_col_base(wr_col_base),.o_extent(old_extent),.o_any(old_any));
        current #(.SIZE(SIZE),.DMA_LANES(DMA_LANES)) u_new(
          .i_valid(i_valid),.wr_col_base(wr_col_base),.o_extent(new_extent),.o_any(new_any));
        assign equivalent=({old_extent,old_any}==={new_extent,new_any});
      endmodule
    ''')
    rows = []
    for size, lanes in CASES:
        script = args.out/f's{size}_l{lanes}.ys'
        log = script.with_suffix('.log')
        script.write_text('read_slang --top proof ' +
            f'-GSIZE={size} -GDMA_LANES={lanes} '+shlex.quote(str(source))+'\n'+
            'prep -top proof -flatten\ncheck -assert\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            run = subprocess.run([sys.executable, str(args.tool_root/'scripts/fpga/open_fpga_synth.py'),
                                  '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT)
        if run.returncode or 'SUCCESS!' not in log.read_text():
            raise RuntimeError(str(log))
        rows.append(dict(size=size, lanes=lanes, passed=True, log_sha256=digest(log)))
    bench = args.out/'event.sv'
    bench.write_text('''module tb #(parameter integer SIZE=16,DMA_LANES=8);
      logic [63:0] valid_bits;
      logic [5:0] column_bits;
      logic equivalent;
      integer checks=0;
      integer random_value;
      proof #(.SIZE(SIZE),.DMA_LANES(DMA_LANES)) dut(
        .i_valid(valid_bits[DMA_LANES-1:0]),.wr_col_base(column_bits[$clog2(SIZE)-1:0]),
        .equivalent(equivalent));
      task automatic check_current;
        #1;
        if(equivalent!==1'b1)$fatal(1,"extent mismatch size=%0d lanes=%0d valid=%h column=%b",SIZE,DMA_LANES,valid_bits,column_bits);
        checks++;
      endtask
      initial begin
        valid_bits='0;column_bits='0;
        for(integer column=0;column<64;column++)begin
          column_bits=6'(column);
          if(column%8==0)$display("IA_EXTENT_COLUMN %0d",column);
          for(integer mask=0;mask<256;mask++)begin
            valid_bits=64'(mask);
            check_current();
          end
        end
        for(integer sample=0;sample<20000;sample++)begin
          if(sample%5000==0)$display("IA_EXTENT_SAMPLE %0d",sample);
          valid_bits={$urandom,$urandom};column_bits=6'($urandom);
          for(integer bit_index=0;bit_index<64;bit_index++)begin
            random_value=$urandom_range(0,15);
            if(random_value==0)valid_bits[bit_index]=1'bx;
            else if(random_value==1)valid_bits[bit_index]=1'bz;
          end
          for(integer bit_index=0;bit_index<6;bit_index++)begin
            random_value=$urandom_range(0,7);
            if(random_value==0)column_bits[bit_index]=1'bx;
            else if(random_value==1)column_bits[bit_index]=1'bz;
          end
          check_current();
        end
        $display("IA_EXTENT_FOUR_STATE_PASS checks=%0d",checks);
        $finish;
      end
    endmodule
    ''')
    reusable = {}
    if args.reuse_results is not None:
        previous = json.loads((args.reuse_results/'summary.json').read_text())
        if (previous.get('passed') is not True or previous['source_sha256'] != hashes or
                previous['bench_sha256'] != digest(bench) or
                digest(args.reuse_results/'extent.sv') != digest(source)):
            raise RuntimeError('Completed results do not match the generated model')
        reusable = {(row['size'], row['lanes']): row for row in previous['four_state_runs']}
    event_rows = []
    for size, lanes in CASES:
        if (size, lanes) in reusable:
            row = reusable[(size, lanes)]
            log = args.reuse_results/f'four_state_s{size}_l{lanes}.log'
            binary = args.reuse_results/f'four_state_s{size}_l{lanes}.vvp'
            if (row['passed'] is not True or row['comparisons'] != 64*256+20000 or
                    digest(log) != row['log_sha256'] or digest(binary) != row['binary_sha256'] or
                    'IA_EXTENT_FOUR_STATE_PASS checks=36384' not in log.read_text()):
                raise RuntimeError(str(log))
            event_rows.append(dict(row, completed_results=str(args.reuse_results.resolve())))
            continue
        binary = args.out/f'four_state_s{size}_l{lanes}.vvp'
        compile_log = args.out/f'four_state_s{size}_l{lanes}_compile.log'
        run = subprocess.run(['/home/agent/.local/bin/iverilog','-g2012','-s','tb',
                              f'-Ptb.SIZE={size}',f'-Ptb.DMA_LANES={lanes}',
                              '-o',str(binary),str(source),str(bench)],capture_output=True,text=True)
        compile_log.write_text(run.stdout+run.stderr)
        if run.returncode: raise RuntimeError(str(compile_log))
        log = args.out/f'four_state_s{size}_l{lanes}.log'
        with log.open('w') as stream:
            run = subprocess.run(['/home/agent/.local/bin/vvp','-i',str(binary)],stdout=stream,stderr=subprocess.STDOUT,timeout=900)
        if run.returncode or 'IA_EXTENT_FOUR_STATE_PASS' not in log.read_text(): raise RuntimeError(str(log))
        event_rows.append(dict(size=size,lanes=lanes,passed=True,comparisons=64*256+20000,
                               log_sha256=digest(log),binary_sha256=digest(binary)))
        print(dict(size=size,lanes=lanes,four_state_pass=True),flush=True)
    assert hashes=={name:digest(root/'rtl/npu/loaders/ia_loader_cache_mgr.sv')for name,root in roots.items()}
    summary=dict(passed=True,source_sha256=hashes,input_constraints=[],runs=rows,
                 four_state_parameter_cases=len(CASES),four_state_comparisons=(64*256+20000)*len(CASES),
                 four_state_runs=event_rows,bench_sha256=digest(bench))
    (args.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
