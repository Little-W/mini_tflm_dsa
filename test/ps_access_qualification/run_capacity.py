#!/usr/bin/env python3
"""检查共享容量比较在任意目录状态和四态输入下的结果。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'rtl/npu/ps_compact/ps_frame_store.sv'
    text = source.read_text()
    bound_start = text.index('    if (p_capacity_rows_width < 32)')
    bound_end = text.index('    // 配置阶段保存各帧', bound_start)
    bounds = text[bound_start:bound_end]
    per_frame = re.search(r'        assign frame_capacity_match\[frame\] =.*?;', text, re.S)[0]
    start = text.index('    assign selected_available_rows =')
    selection = text[start:text.index('    logic complete_now;', start)]
    model = out / 'capacity.sv'
    model.write_text('''// 对生产 RTL 的帧目录选择和容量资格进行独立组合检查。
module capacity_proof #(
    parameter int FRAME_COUNT=16, p_capacity_rows_width=13,
    FRAME_ID_BITS=FRAME_COUNT>1 ? $clog2(FRAME_COUNT) : 1,
    W=FRAME_COUNT*(p_capacity_rows_width+1)+FRAME_ID_BITS+66
) (
    input logic [W-1:0] stimulus, // 全部剩余容量、请求行数、帧编号和帧类型
    output logic equivalent // 共享比较与逐项比较的结果逐位相同
);
    logic [FRAME_COUNT-1:0][p_capacity_rows_width:0] frame_available_rows_q;
    logic [FRAME_COUNT-1:0] frame_capacity_match;
    logic [FRAME_ID_BITS-1:0] frame_id;
    logic [31:0] frame_rows, frame_reserve_rows;
    logic frame_init, frame_final;
    logic incoming_rows_bounded, incoming_request_fits;
    logic [p_capacity_rows_width:0] selected_available_rows;
    logic selected_capacity_match;
    assign {frame_available_rows_q,frame_id,frame_rows,frame_reserve_rows,frame_init,frame_final}=stimulus;
''' + bounds + '\n    for (genvar frame=0;frame<FRAME_COUNT;frame++) begin : g_reference\n' +
        per_frame + '\n    end\n' + selection + '''
    assign equivalent=(incoming_request_fits ===
        ((frame_init && frame_final) || frame_capacity_match[frame_id]));
endmodule
''')
    runs = []
    for frames, width in ((4, 8), (16, 13), (3, 10)):
        folder = out / f'f{frames}_w{width}'
        folder.mkdir(exist_ok=True)
        script, log = folder / 'proof.ys', folder / 'proof.log'
        script.write_text(
            f'read_slang --top capacity_proof -GFRAME_COUNT={frames} -Gp_capacity_rows_width={width} {model}\n'
            'prep -top capacity_proof -flatten\nsat -verify -prove equivalent 1\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                           stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=300)
        if 'SUCCESS!' not in log.read_text():
            raise RuntimeError(f'容量组合证明未完成：{log}')
        id_width = max(1, (frames-1).bit_length())
        bits = frames*(width+1)+id_width+66
        bench = folder / 'four_state.sv'
        bench.write_text(f'''// 覆盖容量边界、无效帧编号、未知位与高阻位。
module tb;
    logic [{bits-1}:0] stimulus;
    wire equivalent;
    integer checks=0;
    capacity_proof #(.FRAME_COUNT({frames}),.p_capacity_rows_width({width})) u_proof(
        .stimulus(stimulus),.equivalent(equivalent));
    task automatic check;
        #1;
        if (equivalent!==1'b1) $fatal(1,"Capacity differs: %b",stimulus);
        checks++;
    endtask
    initial begin
        stimulus='0;check();stimulus='1;check();stimulus='x;check();stimulus='z;check();
        for (int sample=0;sample<20000;sample++) begin
            for (int bit_index=0;bit_index<{bits};bit_index++) stimulus[bit_index]=1'($urandom);
            if (sample%4!=0) begin
                stimulus[33:2]=32'($urandom%{1<<width});
                stimulus[65:34]=32'($urandom%{1<<width});
            end
            if (sample%7==0) stimulus[65:2]='0;
            check();
            stimulus[sample%{bits}]=1'bx;check();
            stimulus[sample%{bits}]=1'bz;check();
        end
        $display("PS_CAPACITY_FOUR_STATE_PASS checks=%0d",checks);
        $finish;
    end
endmodule
''')
        binary = folder / 'four_state.vvp'
        with (folder / 'compile.log').open('w') as stream:
            subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(binary), str(model), str(bench)],
                           stdout=stream, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run(['vvp', str(binary)], capture_output=True, text=True, check=True, timeout=300)
        (folder / 'run.log').write_text(result.stdout+result.stderr)
        match = re.search(r'PS_CAPACITY_FOUR_STATE_PASS checks=(\d+)', result.stdout)
        if match is None or int(match[1]) != 60004:
            raise RuntimeError('容量四态比较未完成')
        row = {'frame_count': frames, 'capacity_width': width, 'formal': True,
               'four_state_checks': int(match[1]),
               'formal_log_sha256': hashlib.sha256(log.read_bytes()).hexdigest(),
               'simulation_log_sha256': hashlib.sha256((folder/'run.log').read_bytes()).hexdigest()}
        runs.append(row)
        print(json.dumps(row), flush=True)
    report = {'passed': True, 'input_constraints': None, 'runs': runs,
              'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'model_sha256': hashlib.sha256(model.read_bytes()).hexdigest()}
    (out / 'summary.json').write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n')


if __name__ == '__main__':
    main()
