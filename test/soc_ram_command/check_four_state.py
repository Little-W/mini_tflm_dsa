#!/usr/bin/env python3
"""记录实际命令判定的四态传播，分别统计未知值变化。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from common import snapshot,miter


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference',default='1ff5aaee')
    args=parser.parse_args();out=args.out.resolve()
    functions,inputs=snapshot(out/'inputs',args.reference)
    model=out/'miter.sv';model.write_text(miter(*functions))
    profiles=[(aw,shift) for aw in [8,16,32,40] for shift in range(6)]
    instances=[];reports=[]
    for index,(aw,shift) in enumerate(profiles):
        instances.append(f'''    command_miter #(.AW({aw}),.ADDR_LSB({shift})) u{index}(
        .byte_addr(address[{aw-1}:0]),.len(length),.size(size),.burst(burst),
        .reference_bad(reference_bad[{index}]),.current_bad(current_bad[{index}]),.correct());''')
        fields=['equal_results','unknown_to_zero','unknown_to_one','zero_to_unknown','one_to_unknown']
        format_text=json.dumps({'address_width':aw,'address_lsb':shift,'samples':65536,
                               **{name:'%0d' for name in fields}}).replace('"%0d"','%0d')
        reports.append('        $display("RESULT '+format_text.replace('"','\\"')+'",'+
                       ','.join(f'{name}[{index}]' for name in fields)+');')

    bench=out/'tb.sv'
    bench.write_text('''module tb;
    reg [39:0] address;
    reg [7:0] length;
    reg [2:0] size;
    reg [1:0] burst;
    wire [23:0] reference_bad,current_bad;
    integer equal_results[24],unknown_to_zero[24],unknown_to_one[24],zero_to_unknown[24],one_to_unknown[24];
'''+ '\n'.join(instances)+'''
    initial begin
        for(integer n=0;n<24;n++)begin equal_results[n]=0;unknown_to_zero[n]=0;unknown_to_one[n]=0;zero_to_unknown[n]=0;one_to_unknown[n]=0;end
        for(integer sample=0;sample<65536;sample++)begin
            address={$urandom,$urandom};length=$urandom;size=$urandom;burst=$urandom;
            if(sample>=16384)begin
                size=3'($urandom_range(0,4));burst=sample%2 ? 2'b01 : 2'b00;
                if(burst==0)length=8'($urandom_range(0,15));
                case(sample%8)
                    0:address[(sample/8)%40]=1'bx;
                    1:address[(sample/8)%40]=1'bz;
                    2:length[(sample/8)%8]=1'bx;
                    3:length[(sample/8)%8]=1'bz;
                    4:size[(sample/8)%3]=1'bx;
                    5:size[(sample/8)%3]=1'bz;
                    6:burst[(sample/8)%2]=1'bx;
                    7:burst[(sample/8)%2]=1'bz;
                endcase
            end
            #1;
            for(integer n=0;n<24;n++)begin
                if(reference_bad[n]===current_bad[n])equal_results[n]++;
                else if(reference_bad[n]===1'bx && current_bad[n]===1'b0)begin
                    if(unknown_to_zero[n]==0)$display("EXAMPLE profile=%0d address=%h len=%h size=%b burst=%b reference=x current=0",n,address,length,size,burst);
                    unknown_to_zero[n]++;
                end else if(reference_bad[n]===1'bx && current_bad[n]===1'b1)unknown_to_one[n]++;
                else if(reference_bad[n]===1'b0 && current_bad[n]===1'bx)zero_to_unknown[n]++;
                else if(reference_bad[n]===1'b1 && current_bad[n]===1'bx)begin
                    if(one_to_unknown[n]==0)$display("EXAMPLE profile=%0d address=%h len=%h size=%b burst=%b reference=1 current=x",n,address,length,size,burst);
                    one_to_unknown[n]++;
                end else $fatal(1,"Unexpected known-result difference sample=%0d profile=%0d ref=%b current=%b address=%h len=%h size=%b burst=%b",sample,n,reference_bad[n],current_bad[n],address,length,size,burst);
            end
        end
'''+ '\n'.join(reports)+'''
        $display("SOC_RAM_COMMAND_FOUR_STATE_PASS");$finish;
    end
endmodule
''')
    with (out/'compile.log').open('w') as log:
        subprocess.run(['iverilog','-g2012','-s','tb','-o',str(out/'sim'),str(model),str(bench)],
                       stdout=log,stderr=subprocess.STDOUT,check=True)
    result=subprocess.run(['vvp',str(out/'sim')],capture_output=True,text=True)
    (out/'run.log').write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    assert 'SOC_RAM_COMMAND_FOUR_STATE_PASS' in result.stdout
    rows=[json.loads(line.removeprefix('RESULT ')) for line in result.stdout.splitlines() if line.startswith('RESULT ')]
    assert len(rows)==24
    assert all(row['unknown_to_zero']==0 for row in rows if row['address_lsb']==5)
    assert all(row['unknown_to_zero']>0 for row in rows if row['address_lsb']<5)
    report={'passed':True,'inputs':inputs,'profiles':rows,
            'four_state_equivalent':False,
            'defined_binary_input_behavior':'proven equal separately by complete-input SAT',
            'total_samples':sum(row['samples'] for row in rows),
            'total_unknown_to_zero':sum(row['unknown_to_zero'] for row in rows),
            'known_zero_to_one_or_one_to_zero':0,
            'total_unknown_to_one':sum(row['unknown_to_one'] for row in rows),
            'total_zero_to_unknown':sum(row['zero_to_unknown'] for row in rows),
            'total_one_to_unknown':sum(row['one_to_unknown'] for row in rows),
            'miter_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),
            'testbench_sha256':hashlib.sha256(bench.read_bytes()).hexdigest(),
            'log_sha256':hashlib.sha256((out/'run.log').read_bytes()).hexdigest()}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ['passed','total_samples','total_unknown_to_zero','four_state_equivalent']}))


if __name__=='__main__':main()
