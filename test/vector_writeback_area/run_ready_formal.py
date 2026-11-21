#!/usr/bin/env python3
"""证明真实写回接收条件与发布条件，并比较四态控制输入。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'rtl/npu/conv/vector_writeback.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assignments(source, label):
    text = '\n'.join(re.search(r'  assign ' + name + r'\s*=.*?;', source, re.S)[0]
                     for name in ('publish_fire', 'request_ready'))
    for name in ('publish_fire', 'request_ready'):
        text = re.sub(r'\b' + name + r'\b', label + '_' + name, text)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='dde5e7c9')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    old = subprocess.check_output(['git', 'show',
        args.reference + ':rtl/npu/conv/vector_writeback.sv'], cwd=ROOT, text=True)
    new = SOURCE.read_text()
    model = out / 'ready_model.sv'
    model.write_text(f'''module ready_model #(parameter integer TILE=16,
    parameter integer COUNT_WIDTH=$clog2(4*TILE+1),CAPACITY=4*TILE)(
    input logic [1:0] c_st,input logic [COUNT_WIDTH-1:0] pending_bytes,
    input logic request_valid,pending_last,append_compatible,append_fits,flush,wr_done,wr_error,
    output logic reference_publish_fire,reference_request_ready,
    output logic candidate_publish_fire,candidate_request_ready,output logic equal_result);
    localparam logic [1:0] IDLE=2'd0,RESPONSE=2'd3;
{assignments(old,'reference')}
{assignments(new,'candidate')}
    assign equal_result = {{reference_publish_fire,reference_request_ready}} ==
                          {{candidate_publish_fire,candidate_request_ready}};
endmodule
''')
    report = {'passed': False, 'reference': args.reference, 'source_sha256': digest(SOURCE),
              'inputs_constrained': False, 'runs': []}
    for tile in (1, 3, 8, 16, 32, 64):
        script = out / f'tile_{tile}.ys'
        log = out / f'tile_{tile}.log'
        script.write_text(f'read_slang --top ready_model -GTILE={tile} {shlex.quote(str(model))}\n'
                          'prep -top ready_model -flatten\nopt -full\n'
                          'sat -verify -prove equal_result 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
                                     '--worker', script], cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT)
        passed = result.returncode == 0 and 'SUCCESS' in log.read_text()
        report['runs'].append({'tile': tile, 'passed': passed, 'log_sha256': digest(log)})
        if not passed:
            raise RuntimeError(f'写回控制证明未完成：{log}')
    tb = out / 'four_state.sv'
    tb.write_text('''module tb;
    logic [1:0] c_st;
    logic [6:0] pending_bytes;
    logic [6:0] controls;
    wire reference_publish_fire,reference_request_ready,candidate_publish_fire,candidate_request_ready;
    integer checked=0;
    ready_model dut(.c_st(c_st),.pending_bytes(pending_bytes),
        .request_valid(controls[0]),.pending_last(controls[1]),.append_compatible(controls[2]),
        .append_fits(controls[3]),.flush(controls[4]),.wr_done(controls[5]),.wr_error(controls[6]),
        .reference_publish_fire(reference_publish_fire),.reference_request_ready(reference_request_ready),
        .candidate_publish_fire(candidate_publish_fire),.candidate_request_ready(candidate_request_ready),
        .equal_result());
    function automatic logic four_state(input integer value);
        case(value) 0:four_state=0;1:four_state=1;2:four_state=1'bx;default:four_state=1'bz;endcase
    endfunction
    initial begin
        for(integer state_index=0;state_index<4;state_index=state_index+1) begin
            c_st=2'(state_index);
            for(integer count_index=0;count_index<4;count_index=count_index+1) begin
                case(count_index)
                    0:pending_bytes=0;1:pending_bytes=64;2:pending_bytes=127;default:pending_bytes='x;
                endcase
                for(integer pattern=0;pattern<16384;pattern=pattern+1) begin
                    for(integer bit_index=0;bit_index<7;bit_index=bit_index+1)
                        controls[bit_index]=four_state((pattern>>(2*bit_index))&3);
                    #1;
                    if({reference_publish_fire,reference_request_ready} !==
                       {candidate_publish_fire,candidate_request_ready})
                        $fatal(1,"writeback control mismatch state=%b count=%b controls=%b",c_st,pending_bytes,controls);
                    checked=checked+1;
                end
            end
        end
        $display("WRITEBACK_READY_FOUR_STATE_PASS checks=%0d",checked);$finish;
    end
endmodule
''')
    binary = out / 'four_state.vvp'
    build = subprocess.run(['iverilog','-g2012','-s','tb','-o',str(binary),str(model),str(tb)],
                           capture_output=True,text=True)
    (out / 'four_state_build.log').write_text(build.stdout+build.stderr)
    if build.returncode:
        raise RuntimeError('写回四态测试编译未完成')
    run = subprocess.run(['vvp',str(binary)],capture_output=True,text=True)
    (out / 'four_state.log').write_text(run.stdout+run.stderr)
    count = re.search(r'WRITEBACK_READY_FOUR_STATE_PASS checks=(\d+)',run.stdout)
    if run.returncode or count is None or digest(SOURCE) != report['source_sha256']:
        raise RuntimeError('写回四态检查未完成或源码已改变')
    report['four_state'] = {'passed': True, 'checks': int(count[1]),
                            'log_sha256': digest(out / 'four_state.log')}
    report['model_sha256'] = digest(model)
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__':
    main()
