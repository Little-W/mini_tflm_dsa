#!/usr/bin/env python3
"""从实际 RTL 提取配置检查，验证零值、边界值及未知输入的四态结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/control/ps_window_scheduler.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-ref', default='0097b66ed57e1b8ef00e402e89dc5b274f1626be')
    parser.add_argument('--out', type=Path, default=ROOT/'build/scheduler_config_timing/four_state')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = args.source_root.resolve()/SOURCE
    comparator = args.source_root.resolve()/'rtl/common/unsigned_compare.sv'
    current = source.read_text()
    reference = subprocess.check_output(['git', 'show', f'{args.reference_ref}:{SOURCE}'],
                                        cwd=ROOT, text=True)
    pattern = r'if\s*\((config_error != 0.*?)\)\s*begin'
    expected = re.search(pattern, reference, re.S)[1]
    actual = re.search(pattern, current, re.S)[1]
    begin = current.index('    logic incoming_window_oversized')
    end = current.index('    logic [31:0] cfg_stream', begin)
    logic = current[begin:end] + '\n' + re.search(
        r'    assign incoming_slice_invalid =.*?;', current, re.S)[0]
    profiles = [(4, 2, 0), (8, 4, 1), (16, 8, 16), (16, 16, 16), (16, 16, 0), (16, 16, 32)]
    reports = []
    hashes = {str(path): digest(path) for path in (source, comparator, Path(__file__))}
    for size, frames, reuse in profiles:
        stem = f's{size}_f{frames}_r{reuse}'
        testbench = out/(stem+'.sv')
        testbench.write_text(f'''module tb;
    localparam integer SIZE={size}, FRAME_COUNT={frames}, MAX_REUSE_TILES={reuse};
    localparam integer SHIFT=$clog2(SIZE), WIDTH=195;
    logic [WIDTH-1:0] stimulus, saved;
    logic [31:0] stream_rows, stationary_rows, reduction, reuse_rows, window_frames, slice_tiles;
    logic [1:0] config_error;
    logic slice_shape_o_valid;
    integer checks=0, seed=32'h06593f8a;
    assign {{stream_rows,stationary_rows,reduction,reuse_rows,window_frames,slice_tiles,config_error,slice_shape_o_valid}}=stimulus;
{logic}
    wire actual=({actual});
    wire expected=({expected});
    task automatic check;
        #1;
        if(actual !== expected) $fatal(1,"configuration stimulus=%b actual=%b expected=%b",stimulus,actual,expected);
        checks++;
    endtask
    initial begin
        stimulus={{32'd1,32'd1,32'd1,32'd1,32'd1,32'd0,2'd0,1'b1}};check();
        for(integer trial=0;trial<4096;trial++) begin
            for(integer bit_index=0;bit_index<WIDTH;bit_index++) stimulus[bit_index]=$random(seed);
            if(trial<128) begin
                stimulus={{32'd1,32'd1,32'd1,
                    32'(1+trial%(MAX_REUSE_TILES>0 ? MAX_REUSE_TILES : 64)),
                    32'(1+trial%FRAME_COUNT),32'(trial%2),2'd0,1'b1}};
            end
            check();saved=stimulus;
            if(trial<128) for(integer bit_index=0;bit_index<WIDTH;bit_index++) begin
                stimulus=saved;stimulus[bit_index]=1'bx;check();
                stimulus=saved;stimulus[bit_index]=1'bz;check();
            end
        end
        for(integer bound_case=0;bound_case<4;bound_case++) begin
            stimulus={{32'd1,32'd1,32'd1,32'(MAX_REUSE_TILES),32'(FRAME_COUNT),32'd0,2'd0,1'b1}};
            case(bound_case)
                0: stimulus[98:67]=32'd0;
                1: stimulus[98:67]=32'(MAX_REUSE_TILES+1);
                2: stimulus[66:35]=32'(FRAME_COUNT+1);
                3: stimulus[34:3]=32'(MAX_REUSE_TILES+1);
            endcase
            check();
        end
        stimulus='x;check();stimulus='z;check();
        $display("SCHEDULER_CONFIG_FOUR_STATE_PASS checks=%0d",checks);$finish;
    end
endmodule
''')
        for mode in ('XILINX_FPGA', 'ASIC_SYNTHESIS'):
            binary = out/(stem+'_'+mode)
            command = ['iverilog', '-g2012', '-D'+mode+'=1', '-s', 'tb',
                       '-o', str(binary), str(testbench), str(comparator)]
            with (out/(stem+'_'+mode+'.compile.log')).open('w') as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
            result = subprocess.run(['vvp', str(binary)], text=True, capture_output=True, timeout=120)
            log = out/(stem+'_'+mode+'.log')
            log.write_text(result.stdout+result.stderr)
            match = re.search(r'SCHEDULER_CONFIG_FOUR_STATE_PASS checks=(\d+)', result.stdout)
            if result.returncode or match is None:
                raise RuntimeError(f'配置四态检查未通过：{log}')
            record = {'size': size, 'frame_count': frames, 'max_reuse_tiles': reuse,
                      'mode': mode, 'passed': True, 'checks': int(match[1]),
                      'testbench_sha256': digest(testbench), 'log_sha256': digest(log)}
            reports.append(record)
            print(json.dumps(record), flush=True)
    if hashes != {name: digest(Path(name)) for name in hashes}:
        raise RuntimeError('验证期间源文件发生变化')
    report = {'passed': True, 'reference_ref': args.reference_ref,
              'source_sha256': hashes, 'profiles': reports,
              'checks': sum(row['checks'] for row in reports)}
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
