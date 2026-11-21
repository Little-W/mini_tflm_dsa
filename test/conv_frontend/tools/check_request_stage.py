#!/usr/bin/env python3
"""证明请求寄存级的容量、顺序及全部元数据的保存关系。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = root / 'rtl/npu/conv/conv_im2col_frontend.sv'
    text = source.read_text()
    controls = '\n'.join(re.search(pattern, text, re.S)[0] for pattern in (
        r'  assign cache_port_valid = .*?;', r'  assign cache_req_ready = .*?;'))
    start = text.rindex('  always_ff', 0, text.index('    if (!rst_n) request_pending'))
    registers = text[start:text.index('  conv_read_cache #', start)]
    for port, value in (('req_addr', 'request_addr_q'), ('req_geometry', 'request_geometry_q'),
                        ('req_event_first', 'request_event_first_q'),
                        ('req_window_index_valid', 'request_index_valid_q'),
                        ('req_window_index', 'request_index_q'), ('req_window_epoch', 'request_epoch_q'),
                        ('req_window_progress', 'request_progress_q')):
        assert re.search(r'\.' + port + r'\(REGISTER_CACHE_REQUEST\s*\?\s*' + value + r'\s*:', text), port
    proof = out / 'request_stage.sv'
    proof.write_text('''module request_stage_proof (
    input logic clk, rst_n, cache_req_valid, cache_port_ready,
    input logic [31:0] cache_req_addr, req_index, req_epoch, request_output_y,
    input logic geometry_tile, req_index_valid,
    input logic [34:0] request_y,
    output logic cache_req_ready, cache_port_valid,
    output logic [146:0] output_data,
    output logic equivalent
);
    localparam bit REGISTER_CACHE_REQUEST=1;
    logic request_pending;
    logic [31:0] request_addr_q, request_index_q, request_epoch_q, request_progress_q;
    logic [15:0] request_y_q;
    logic request_geometry_q, request_event_first_q, request_index_valid_q;
''' + controls + '\n' + registers + '''
    logic [1:0] expected_count;
    logic [146:0] expected_data, input_data;
    logic accepted, delivered;
    assign input_data={cache_req_addr,geometry_tile,
        (geometry_tile && cache_req_addr[3:0]==0),req_index_valid,
        req_index,req_epoch,request_y[15:0],request_output_y};
    assign output_data={request_addr_q,request_geometry_q,request_event_first_q,
        request_index_valid_q,request_index_q,request_epoch_q,request_y_q,request_progress_q};
    assign accepted=cache_req_valid && cache_req_ready;
    assign delivered=cache_port_valid && cache_port_ready;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) expected_count<=0;
        else expected_count<=expected_count+2'(accepted)-2'(delivered);
    end
    always_ff @(posedge clk) begin
        if (accepted) expected_data<=input_data;
    end
    assign equivalent=(expected_count<=1) &&
        (cache_port_valid==(expected_count!=0)) &&
        (!cache_port_valid || output_data==expected_data);
endmodule
''')
    result = {'passed': True, 'metadata_bits': 147,
              'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'proof_sha256': hashlib.sha256(proof.read_bytes()).hexdigest(),
              'input_assumptions': ['rst_n=0 at the first sampled edge'], 'runs': []}
    for name, command in (
        ('reset', 'sat -seq 2 -set-at 1 rst_n 0 -prove equivalent 1 -verify -show-inputs -show-outputs'),
        ('induction', 'sat -seq 1 -tempinduct-inductonly -maxsteps 1 -prove equivalent 1 -verify -show-inputs -show-outputs')):
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text('read_slang --top request_stage_proof ' + shlex.quote(str(proof)) + '\n' +
                          'prep -top request_stage_proof -flatten\nasync2sync\ndffunmap\nopt\ncheck -assert\n' +
                          command + '\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True)
        assert 'SUCCESS' in log.read_text()
        result['runs'].append({'name': name, 'passed': True})
    tb = out / 'tb_four_state.sv'
    tb.write_text('''module tb_four_state;
    reg clk=0,rst_n=0,cache_req_valid=0,cache_port_ready=0;
    reg [31:0] cache_req_addr=0,req_index=0,req_epoch=0,request_output_y=0;
    reg geometry_tile=0,req_index_valid=0;
    reg [34:0] request_y=0;
    wire cache_req_ready,cache_port_valid,equivalent;
    wire [146:0] output_data;
    request_stage_proof dut(.*);
    always #5 clk=~clk;
    reg [164:0] payload;
    integer sample;
    initial begin
        repeat(2) @(negedge clk);
        for (sample=0;sample<20000;sample=sample+1) begin
            rst_n=sample%257!=0;
            cache_req_valid=$random;
            cache_port_ready=$random;
            payload={$random,$random,$random,$random,$random,$random};
            if (sample%3==0) payload[sample%165]=1'bx;
            if (sample%5==0) payload[(sample*7)%165]=1'bz;
            {cache_req_addr,req_index,req_epoch,request_output_y,
             geometry_tile,req_index_valid,request_y}=payload;
            @(posedge clk); #1;
            if (cache_port_valid !== (dut.expected_count!=0) ||
                (cache_port_valid && output_data!==dut.expected_data))
                $fatal(1,"request stage sample %0d",sample);
            @(negedge clk);
        end
        $display("REQUEST_STAGE_FOUR_STATE_PASS samples=20000 metadata_bits=147");
        $finish;
    end
endmodule
''')
    binary = out / 'four_state.vvp'
    with (out / 'compile.log').open('w') as stream:
        subprocess.run(['/home/agent/.local/bin/iverilog', '-g2012', '-s', 'tb_four_state',
                        '-o', str(binary), str(proof), str(tb)], stdout=stream,
                       stderr=subprocess.STDOUT, check=True)
    run = subprocess.run(['/home/agent/.local/bin/vvp', str(binary)], capture_output=True, text=True, check=True)
    (out / 'four_state.log').write_text(run.stdout + run.stderr)
    assert 'REQUEST_STAGE_FOUR_STATE_PASS' in run.stdout
    result['four_state_samples'] = 20000
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
