#!/usr/bin/env python3
"""证明缓存标签匹配寄存与原标签、地址寄存具有相同周期及四态结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = args.source_root.resolve() / 'rtl/npu/dma/cache/conv_read_cache.sv'
    text = source.read_text()
    start = text.index('  logic [WAYS-1:0][31:LB] lookup_tag_raw;')
    end = text.index('  if (DEMAND_DEPTH == 1) begin : g_direct_response_lookup', start)
    actual = text[start:end]
    proof = out / 'tag_stage.sv'
    proof.write_text('''module tag_stage_proof #(parameter int WAYS=2, LB=7, DEMAND_DEPTH=2) (
    input logic clk, rst_n, req_fire,
    input logic [WAYS-1:0][31:LB] raw_tag,
    input logic [31:0] next_address,
    input logic [WAYS-1:0] valid_lookup,
    output logic equivalent, four_state_equal, observed
);
    typedef struct packed { logic [31:0] address; } request_t;
    request_t work_request, lookup_read_request;
    logic [31:0] demand_addr;
    logic [WAYS-1:0][31:LB] reference_tag;
    logic [WAYS-1:0][31:LB] lookup_tag;
    logic [WAYS-1:0] work_tag_hits, demand_tag_hits;
    logic [WAYS-1:0] reference_work_hits, reference_demand_hits;
    assign lookup_read_request.address = next_address;
''' + actual + '''
    assign lookup_tag_raw = raw_tag;
    always_ff @(posedge clk) begin
        work_request <= lookup_read_request;
        reference_tag <= raw_tag;
        lookup_tag <= raw_tag;
        if (!rst_n) begin demand_addr <= 32'd0; observed <= 1'b0; end
        else begin
            observed <= 1'b1;
            if (req_fire) demand_addr <= work_request.address;
        end
    end
    for (genvar way=0; way<WAYS; way++) begin : g_reference
        assign reference_work_hits[way] = valid_lookup[way] &&
            reference_tag[way] == work_request.address[31:LB];
        assign reference_demand_hits[way] = valid_lookup[way] &&
            reference_tag[way] == demand_addr[31:LB];
    end
    assign equivalent = !observed ||
        {work_tag_hits, demand_tag_hits} == {reference_work_hits, reference_demand_hits};
    assign four_state_equal =
        {work_tag_hits, demand_tag_hits} === {reference_work_hits, reference_demand_hits};
endmodule
''')
    result = {'passed': True, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'proof_sha256': hashlib.sha256(proof.read_bytes()).hexdigest(), 'formal': [],
              'input_constraints': ['rst_n=0 at the first sampled edge']}
    for ways in (1, 2):
        for line_shift in (4, 7, 8):
            name = f'w{ways}_l{line_shift}'
            script, log = out / (name + '.ys'), out / (name + '.log')
            script.write_text('read_slang --top tag_stage_proof -GWAYS=' + str(ways) +
                ' -GLB=' + str(line_shift) + ' ' + shlex.quote(str(proof)) + '\n' +
                'prep -top tag_stage_proof -flatten\ncheck -assert\n' +
                'sat -seq 2 -set-at 1 rst_n 0 -set-at 1 req_fire 0 -prove-skip 1 -prove equivalent 1 -verify\n' +
                'sat -seq 1 -tempinduct-inductonly -maxsteps 1 -prove equivalent 1 -verify\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                               check=True, timeout=120)
            if 'Induction step proven: SUCCESS!' not in log.read_text():
                raise RuntimeError('Tag comparison induction did not complete: ' + str(log))
            result['formal'].append({'ways': ways, 'line_bytes': 1 << line_shift, 'passed': True})
            print('TAG_STAGE_FORMAL_PASS', name, flush=True)
    tb = out / 'tb.sv'
    tb.write_text('''module tb;
    logic clk=0, rst_n=0, req_fire=0;
    logic [1:0][31:7] raw_tag;
    logic [31:0] next_address;
    logic [1:0] valid_lookup;
    wire equivalent, four_state_equal, observed;
    logic [31:7] random_tag;
    integer checks=0;
    tag_stage_proof dut(.*);
    initial begin
        raw_tag='0; next_address='0; valid_lookup='0;
        #1; clk=1; #1; clk=0; rst_n=1;
        for (int sample=0; sample<20000; sample++) begin
            req_fire=1'($urandom);
            if (sample%11==0) req_fire=1'bx;
            if (sample%17==0) req_fire=1'bz;
            next_address=$urandom;
            valid_lookup=2'($urandom);
            for (int way=0; way<2; way++) begin
                random_tag=25'($urandom);
                if (sample%5==0) random_tag=next_address[31:7];
                if (sample%7==0) random_tag[sample%25+7]=1'bx;
                if (sample%13==0) random_tag[sample%25+7]=1'bz;
                raw_tag[way]=random_tag;
            end
            if (sample%19==0) next_address[sample%32]=1'bx;
            if (sample%23==0) next_address[sample%32]=1'bz;
            #1; clk=1; #1;
            if (four_state_equal !== 1'b1)
                $fatal(1,"Tag stage differs at sample %0d",sample);
            checks++;
            clk=0;
        end
        $display("TAG_STAGE_FOUR_STATE_PASS samples=%0d",checks);
        $finish;
    end
endmodule
''')
    with (out / 'compile.log').open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(out / 'sim'), str(proof), str(tb)],
                       stdout=stream, stderr=subprocess.STDOUT, check=True)
    run = subprocess.run(['vvp', str(out / 'sim')], capture_output=True, text=True, timeout=60)
    (out / 'run.log').write_text(run.stdout + run.stderr)
    if run.returncode or 'TAG_STAGE_FOUR_STATE_PASS samples=20000' not in run.stdout:
        raise RuntimeError('Tag four-state comparison did not complete: ' + str(out / 'run.log'))
    result['four_state_samples'] = 20000
    if result['source_sha256'] != hashlib.sha256(source.read_bytes()).hexdigest():
        raise RuntimeError('Cache source changed during tag proof')
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
