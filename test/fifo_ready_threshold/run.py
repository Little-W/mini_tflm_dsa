#!/usr/bin/env python3
"""验证完整输出容量比较模块在任意输入和四态输入下的行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/writeback/fifo_bank_watermark.sv'
HELPER = 'rtl/npu/writeback/fifo_ready_threshold.sv'
WIDTHS = (1, 2, 3, 4, 5, 6, 7, 9, 12, 16, 32, 64)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=360)
    return log.read_text()


def pair(width):
    return f'''// 同时比较全部输入编码，容量阈值不施加限制。
module pair_{width}(input wire [63:0] ready, threshold, input wire partial,
                    output wire reference_full, current_full);
    watermark_reference #(.p_banks(32), .p_count_width({width}),
        .p_precomputed_threshold(1)) u_reference (
        .i_reserve(32'd0), .i_ready_banks(ready[{width-1}:0]),
        .i_partial_write(partial), .i_ready_threshold(threshold[{width-1}:0]),
        .o_full(reference_full));
    fifo_bank_watermark #(.p_banks(32), .p_count_width({width}),
        .p_precomputed_threshold(1)) u_current (
        .i_reserve(32'd0), .i_ready_banks(ready[{width-1}:0]),
        .i_partial_write(partial), .i_ready_threshold(threshold[{width-1}:0]),
        .o_full(current_full));
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='07a199ac')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip()
    reference = out/'reference.sv'
    reference.write_text(subprocess.check_output(['git', 'show', commit+':'+SOURCE], cwd=ROOT,
                                                text=True).replace('fifo_bank_watermark', 'watermark_reference'))
    sources = [reference, ROOT/SOURCE, ROOT/HELPER, ROOT/'rtl/common/parallel_prefix_add.sv']
    hashes = {str(p): digest(p) for p in sources}
    pairs = ''.join(pair(width) for width in WIDTHS)
    instances = '\n'.join(f'    pair_{w} u{w}(.ready,.threshold,.partial,\n'
                            f'        .reference_full(reference_full[{i}]),.current_full(current_full[{i}]));'
                            for i, w in enumerate(WIDTHS))
    models = out/'models.sv'
    models.write_text(pairs+f'''module proof(input wire [63:0] ready,threshold,
    input wire partial,output wire equivalent);
    wire [{len(WIDTHS)-1}:0] reference_full,current_full;
{instances}
    assign equivalent = reference_full == current_full;
endmodule
''')
    bench = out/'tb.sv'
    bench.write_text(f'''// 覆盖六位完整输入空间、任意宽度边界以及未知值传播。
module tb;
    reg [63:0] ready,threshold,known_ready,known_threshold;
    reg partial;
    wire [{len(WIDTHS)-1}:0] reference_full,current_full;
    integer rng=32'h27af035b,checks=0,choice;
{instances}
    function automatic [31:0] random_word;
        rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
    endfunction
    task check;
        begin
            #1;checks=checks+{len(WIDTHS)};
            if(reference_full!==current_full)
                $fatal(1,"Capacity threshold differs ready=%h threshold=%h partial=%b",ready,threshold,partial);
        end
    endtask
    initial begin
        for(integer a=0;a<64;a++)for(integer b=0;b<64;b++)for(integer c=0;c<2;c++)begin
            ready=64'(a);threshold=64'(b);partial=1'(c);check();
        end
        for(integer sample=0;sample<16384;sample++)begin
            ready={{random_word(),random_word()}};threshold={{random_word(),random_word()}};
            partial=1'(random_word());
            if(sample>=8192)begin
                for(integer bit_index=0;bit_index<64;bit_index++)begin
                    choice=random_word()%8;
                    if(choice==0)ready[bit_index]=1'bx;
                    if(choice==1)ready[bit_index]=1'bz;
                    choice=random_word()%8;
                    if(choice==0)threshold[bit_index]=1'bx;
                    if(choice==1)threshold[bit_index]=1'bz;
                end
                choice=random_word()%4;
                if(choice==0)partial=1'bx;
                if(choice==1)partial=1'bz;
            end
            check();
        end
        for(integer sample=0;sample<64;sample++)begin
            known_ready={{random_word(),random_word()}};
            known_threshold=(sample%2==0)?known_ready:{{random_word(),random_word()}};
            for(integer bit_index=0;bit_index<64;bit_index++)begin
                ready=known_ready;threshold=known_threshold;partial=1'(sample);
                ready[bit_index]=1'bx;check();ready[bit_index]=1'bz;check();
                ready=known_ready;threshold[bit_index]=1'bx;check();threshold[bit_index]=1'bz;check();
            end
        end
        ready='x;threshold='x;partial=1'bx;check();
        ready='z;threshold='z;partial=1'bz;check();
        $display("FIFO_THRESHOLD_PASS checks=%0d",checks);$finish;
    end
endmodule
''')
    records=[]
    for mode in ('generic','fpga'):
        flags=[] if mode=='generic' else ['-DSYNTHESIS=1','-DXILINX_FPGA=1']
        script=out/(mode+'.ys');log=out/(mode+'.log')
        script.write_text('read_slang --top proof '+shlex.join(flags+list(map(str,sources+[models])))+
                          '\nprep -top proof -flatten\nsat -verify -prove equivalent 1\n')
        text=run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
        assert 'SUCCESS!' in text
        binary=out/(mode+'.vvp')
        run(['iverilog','-g2012','-s','tb',*flags,'-o',binary,*sources,models,bench],out/(mode+'_compile.log'))
        numeric=out/(mode+'_four_state.log')
        text=run(['vvp',binary],numeric)
        count=re.search(r'FIFO_THRESHOLD_PASS checks=(\d+)',text);assert count
        records.append(dict(mode=mode,widths=WIDTHS,passed=True,checks=int(count[1]),
                            formal_log_sha256=digest(log),four_state_log_sha256=digest(numeric)))
        print(text,flush=True)
    assert hashes=={str(p):digest(p) for p in sources}
    report=dict(passed=True,reference_commit=commit,source_sha256=hashes,input_assumptions=[],cases=records)
    (out/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
