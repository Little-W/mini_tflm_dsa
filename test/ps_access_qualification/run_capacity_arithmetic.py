#!/usr/bin/env python3
"""检查帧容量融合算术的二值等价与四态结果。"""
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


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT/'rtl/npu/ps_compact/ps_frame_store.sv'
    text = source.read_text()
    start = text.index('    for (genvar frame = 0; frame < FRAME_COUNT; frame++) begin : g_frame_capacity')
    body = text[start:text.index('        always_ff', start)]
    model = out/'arithmetic.sv'
    model.write_text('''// 直接使用生产容量算术，比较融合和值与定宽逐级结果。
module capacity_arithmetic #(
    parameter int FRAME_COUNT=16, MAX_FRAME_ROWS=512, POOL_BYTES=57344,
    BANK_BYTES=8192, EXTERNAL_RAM=1,
    BANKS=EXTERNAL_RAM!=0 ? POOL_BYTES/BANK_BYTES : 4,
    BANK_DEPTH=EXTERNAL_RAM!=0 ? BANK_BYTES/16 : POOL_BYTES/64,
    BANK_ADDR_BITS=$clog2(BANK_DEPTH)>0 ? $clog2(BANK_DEPTH) : 1,
    ROTATION_BITS=$clog2(BANKS)>0 ? $clog2(BANKS) : 1,
    FRAME_ID_BITS=FRAME_COUNT>1 ? $clog2(FRAME_COUNT) : 1,
    LENGTH_BITS=$clog2(MAX_FRAME_ROWS+1),
    RAW_LINEAR_BITS=$clog2(FRAME_COUNT*MAX_FRAME_ROWS*4+1),
    p_pool_words_width=BANK_ADDR_BITS+ROTATION_BITS+2,
    p_capacity_rows_width=RAW_LINEAR_BITS-2>p_pool_words_width-2 ?
        RAW_LINEAR_BITS-2 : p_pool_words_width-2,
    W=p_capacity_rows_width+32
) (
    input logic [W-1:0] stimulus, // 任意存储池行数和目录间隔
    output logic equivalent // 所有帧的剩余行数逐位相同
);
    logic [p_capacity_rows_width-1:0] configured_pool_rows;
    logic [31:0] cfg_directory_stride;
    logic [FRAME_COUNT-1:0] frame_equal;
    assign {configured_pool_rows,cfg_directory_stride}=stimulus;
''' + body + '''
        assign frame_equal[frame]=(available_rows===available_rows_direct);
    end
    assign equivalent=&frame_equal;
endmodule
''')
    resolver = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolver([model], ROOT)
    profiles = [(16,512,57344,8192,1), (16,47,4096,2048,0),
                (6,33,8192,2048,1), (1,1,4096,2048,0)]
    runs = []
    for frames, rows, pool, bank, external in profiles:
        folder=out/f'f{frames}_r{rows}'
        folder.mkdir(exist_ok=True)
        parameters=dict(FRAME_COUNT=frames,MAX_FRAME_ROWS=rows,POOL_BYTES=pool,
                        BANK_BYTES=bank,EXTERNAL_RAM=external)
        script,log=folder/'proof.ys',folder/'proof.log'
        script.write_text('read_slang -DSYNTHESIS=1 --top capacity_arithmetic '+
            ' '.join(f'-G{k}={v}' for k,v in parameters.items())+' '+
            shlex.join(map(str,sources))+
            '\nprep -top capacity_arithmetic -flatten\nsat -verify -prove equivalent 1\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                '--worker',str(script)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=300)
        if 'SUCCESS!' not in log.read_text():
            raise RuntimeError(f'容量算术证明未完成：{log}')
        banks=pool//bank if external else 4
        depth=bank//16 if external else pool//64
        raw=(frames*rows*4).bit_length()
        cw=max(raw-2,max(1,(depth-1).bit_length())+max(1,(banks-1).bit_length()))
        width=cw+32
        bench=folder/'four_state.sv'
        bench.write_text(f'''// 覆盖借位、目录乘积回绕、未知位与高阻位。
module tb;
    logic [{width-1}:0] stimulus;
    logic equivalent;
    integer checks=0;
    capacity_arithmetic #({','.join(f'.{k}({v})' for k,v in parameters.items())}) u_proof(
        .stimulus(stimulus),.equivalent(equivalent));
    task automatic check;
        #1;
        if (equivalent!==1'b1) $fatal(1,"Capacity arithmetic differs: %b",stimulus);
        checks++;
    endtask
    initial begin
        stimulus='0;check();stimulus='1;check();stimulus='x;check();stimulus='z;check();
        for (int sample=0;sample<10000;sample++) begin
            for (int b=0;b<{width};b++) stimulus[b]=1'($urandom);
            check();stimulus[sample%{width}]=1'bx;check();
            stimulus[sample%{width}]=1'bz;check();
        end
        $display("PS_CAPACITY_ARITHMETIC_PASS checks=%0d",checks);
        $finish;
    end
endmodule
''')
        binary=folder/'four_state.vvp'
        with (folder/'compile.log').open('w') as stream:
            subprocess.run(['iverilog','-g2012','-s','tb','-o',str(binary),
                *map(str,sources),str(bench)],stdout=stream,stderr=subprocess.STDOUT,check=True)
        result=subprocess.run(['vvp',str(binary)],capture_output=True,text=True,check=True,timeout=300)
        (folder/'run.log').write_text(result.stdout+result.stderr)
        match=re.search(r'PS_CAPACITY_ARITHMETIC_PASS checks=(\d+)',result.stdout)
        if match is None or int(match[1])!=30004:
            raise RuntimeError('容量算术四态比较未完成')
        row={'parameters':parameters,'formal_synthesis_branch':True,
             'four_state_checks':int(match[1]),'formal_log_sha256':digest(log),
             'simulation_log_sha256':digest(folder/'run.log')}
        runs.append(row)
        print(json.dumps(row),flush=True)
    report={'passed':True,'input_constraints':None,'runs':runs,
            'source_sha256':digest(source),'model_sha256':digest(model)}
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
