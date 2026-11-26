#!/usr/bin/env python3
"""检查线性DMA实际使用的高位零值归并及未知值传播。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[2]
WIDTHS=(1,6,7,26,28,32,64)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source=ROOT/'rtl/npu/dma/axi_linear_block_dma.sv';helper=ROOT/'rtl/common/zero_reduce.sv'
    assert '.p_width(REG_WIDTH-$clog2(SIZE)), .p_group_width(6)' in source.read_text()
    assert 'assign limit_high_zero = rd_rsp_columns_high_zero;' in source.read_text()
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in (source,helper)}
    instances='\n'.join(f'''    wire z{w};
    zero_reduce #(.p_width({w}),.p_group_width(6)) u{w}(.i_value(value[{w-1}:0]),.o_zero(z{w}));'''
        for w in WIDTHS)
    checks='\n'.join(f'''            if(z{w}!==!(|value[{w-1}:0]))$fatal(1,"Zero grouping differs width={w}");'''
        for w in WIDTHS)
    bench=out/'tb.sv';bench.write_text(f'''// 各种高位宽度共同检查已知值、部分未知值和零值控制情况。
module tb;
    reg [63:0] value;
    integer rng=32'h478b3f0a,checks=0;
{instances}
    function automatic [31:0] random_word;
        rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
    endfunction
    task compare;
        begin #1;
{checks}
            checks=checks+{len(WIDTHS)};
        end
    endtask
    initial begin
        for(integer bit_index=0;bit_index<64;bit_index++)begin
            value='0;compare();value[bit_index]=1'b1;compare();
            value='x;compare();value[bit_index]=1'b1;compare();
            value='z;compare();value[bit_index]=1'b1;compare();
            value='0;value[bit_index]=1'bx;compare();value[bit_index]=1'bz;compare();
        end
        for(integer sample=0;sample<16384;sample++)begin
            value={{random_word(),random_word()}};compare();
            value[sample%64]=1'bx;compare();value[(sample+31)%64]=1'bz;compare();
        end
        $display("LINEAR_COLUMN_GROUPS_PASS checks=%0d",checks);$finish;
    end
endmodule
''')
    records=[]
    for mode in ('generic','fpga'):
        flags=[]if mode=='generic'else['-DSYNTHESIS=1','-DXILINX_FPGA=1']
        binary=out/(mode+'.vvp');log=out/(mode+'.log')
        with (out/(mode+'_compile.log')).open('w')as f:
            subprocess.run(['iverilog','-g2012','-s','tb',*flags,'-o',str(binary),str(helper),str(bench)],
                           stdout=f,stderr=subprocess.STDOUT,check=True)
        r=subprocess.run(['vvp',str(binary)],capture_output=True,text=True,check=True)
        log.write_text(r.stdout+r.stderr);count=re.search(r'LINEAR_COLUMN_GROUPS_PASS checks=(\d+)',r.stdout);assert count
        records.append(dict(mode=mode,checks=int(count[1]),passed=True,log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
        print(r.stdout,flush=True)
    assert hashes=={str(p):hashlib.sha256(Path(p).read_bytes()).hexdigest()for p in hashes}
    (out/'validation.json').write_text(json.dumps(dict(passed=True,widths=WIDTHS,source_sha256=hashes,cases=records),indent=2)+'\n')


if __name__=='__main__':main()
