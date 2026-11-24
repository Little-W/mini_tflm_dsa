#!/usr/bin/env python3
"""证明缓存标签匹配寄存与原标签、地址寄存具有相同周期及四态结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def block(text, marker):
    start = text.index(marker)
    begin = text.index('begin', start)
    depth = 0
    for token in re.finditer(r'\bbegin\b|\bend\b', text[begin:]):
        depth += 1 if token[0] == 'begin' else -1
        if depth == 0:
            return text[start:begin + token.end()]
    raise RuntimeError('RTL 过程未完整提取: ' + marker)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = args.source_root.resolve() / 'rtl/npu/dma/cache/conv_windowed_cache.sv'
    if not source.is_file():
        source = source.with_name('conv_read_cache.sv')
    text = source.read_text()
    actual = block(text, 'end else begin : g_direct_tag_compare')
    actual = actual.split('\n', 1)[1].rsplit('end', 1)[0]
    activity = block(actual, 'always_ff @(posedge clk or negedge rst_n)')
    actual = actual.replace(activity, '', 1).replace('logic cache_active_q;', "wire cache_active_q=1'b1;")
    actual = actual.replace('request_queue[request_head].address', 'head_address')
    request_selection = block(text, 'always_comb begin\n    lookup_read_request =')
    proof = out / 'tag_stage.sv'
    proof.write_text('''module tag_stage_proof #(parameter int WAYS=2, LB=7, DEMAND_DEPTH=1) (
    input logic clk, rst_n, req_fire, req_valid, request_count,
    input logic [1:0] fg_state, head_set, next_set, miss_set,
    input logic [WAYS-1:0][3:0][31:LB] tag_memory,
    input logic [31:0] next_address, head_address,
    input logic [WAYS-1:0][3:0] resident_memory,
    output logic equivalent, four_state_equal, observed
);
    localparam int SI=2, DQ_AW=1, DQ_CW=1, WI=WAYS>1?$clog2(WAYS):1;
    localparam [1:0] F_IDLE=0;
    wire [1:0] fill_state=F_IDLE;
    wire [WI-1:0] fill_way=0;
    if(1)begin:g_saved_fill_match
      wire lookup_fill_set_match_q=0;
      wire fill_active_q=0;
    end
    localparam logic [1:0] FG_MISS=2'd1;
    localparam logic [0:0] request_head=1'b0;
    typedef struct packed { logic [31:0] address; logic [SI-1:0] set_index; } request_t;
    request_t work_request, lookup_read_request, incoming_request;
    request_t request_queue [2];
    logic [SI-1:0] lookup_read_set, lookup_set;
    logic [31:2] lookup_read_word;
    logic [1:0] lookup_candidate_select, lookup_request_select;
    logic [2:0] lookup_candidate_enable;
    wire [3:0] lookup_candidate_conflict='0, lookup_candidate_fill_match='0;
    wire ram_wen=1'b0;
    wire configured=1'b1, clearing=1'b0;
    logic [3:0][SI-1:0] lookup_candidate_set;
    logic [31:0] demand_addr;
    logic [WAYS-1:0][31:LB] reference_tag;
    logic [WAYS-1:0][31:LB] lookup_tag;
    logic [WAYS-1:0] work_tag_hits, demand_tag_hits;
    logic [WAYS-1:0] reference_work_hits, reference_demand_hits;
    logic [WAYS-1:0] reference_resident;
    assign incoming_request={next_address,next_set};
    assign request_queue[0]={head_address,head_set};
    assign request_queue[1]='0;
    assign lookup_set=miss_set;
    assign lookup_candidate_set={miss_set,next_set,2'd0,head_set};
''' + request_selection + '\n' + actual + '''
    for (genvar way=0;way<WAYS;way++) begin : g_read
        assign lookup_tag_raw[way]=tag_memory[way][lookup_read_set];
        assign lookup_candidate_tags[way][0]=tag_memory[way][head_set];
        assign lookup_candidate_tags[way][1]=tag_memory[way][next_set];
        assign lookup_candidate_tags[way][2]=tag_memory[way][miss_set];
        assign lookup_candidate_valid_next[way][0]=resident_memory[way][head_set];
        assign lookup_candidate_valid_next[way][1]=resident_memory[way][next_set];
        assign lookup_candidate_valid_next[way][2]=resident_memory[way][miss_set];
        assign lookup_valid_next[way]=resident_memory[way][lookup_read_set];
        always_ff @(posedge clk) reference_resident[way] <= resident_memory[way][lookup_read_set];
    end
    always_ff @(posedge clk) begin
        work_request <= lookup_read_request;
        reference_tag <= lookup_tag_raw;
        lookup_tag <= lookup_tag_raw;
        if (!rst_n) begin demand_addr <= 32'd0; observed <= 1'b0; end
        else begin
            observed <= 1'b1;
            if (req_fire) demand_addr <= work_request.address;
        end
    end
    for (genvar way=0; way<WAYS; way++) begin : g_reference
        assign reference_work_hits[way] = reference_resident[way] &&
            reference_tag[way] == work_request.address[31:LB];
        assign reference_demand_hits[way] = reference_resident[way] &&
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
              'input_constraints': ['rst_n=0 at the first sampled edge',
                                    'req_fire=0 at the first sampled edge']}
    for ways in (1, 2):
        for line_shift in (3, 4, 5, 6, 7, 8):
            name = f'w{ways}_l{line_shift}'
            script, log = out / (name + '.ys'), out / (name + '.log')
            script.write_text('read_slang --top tag_stage_proof -DSYNTHESIS=1 -GWAYS=' + str(ways) +
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
    logic clk=0, rst_n=0, req_fire=0, req_valid=0, request_count=0;
    logic [1:0] fg_state=0, head_set=0, next_set=0, miss_set=0;
    logic [199:0] tag_memory_flat;
    wire [1:0][3:0][31:7] tag_memory=tag_memory_flat;
    logic [31:0] next_address, head_address;
    logic [7:0] resident_memory_flat;
    wire [1:0][3:0] resident_memory=resident_memory_flat;
    wire equivalent, four_state_equal, observed;
    logic [31:7] random_tag;
    integer checks=0;
    tag_stage_proof dut(.*);
    initial begin
        tag_memory_flat='0; next_address='0; head_address='0; resident_memory_flat='0;
        #1; clk=1; #1; clk=0; rst_n=1;
        for (int sample=0; sample<20000; sample++) begin
            req_fire=1'($urandom);
            if (sample%11==0) req_fire=1'bx;
            if (sample%17==0) req_fire=1'bz;
            req_valid=1'($urandom); request_count=1'($urandom);
            fg_state=2'($urandom); head_set=2'($urandom);
            next_set=2'($urandom); miss_set=2'($urandom);
            next_address=$urandom; head_address=$urandom;
            resident_memory_flat=8'($urandom);
            if (sample%53==0) resident_memory_flat[sample%8]=1'bx;
            if (sample%59==0) resident_memory_flat[sample%8]=1'bz;
            for (int way=0; way<2; way++) begin
                for (int set_index=0;set_index<4;set_index++) begin
                    random_tag=25'($urandom);
                    if (sample%5==0 && set_index==next_set) random_tag=next_address[31:7];
                    if (sample%3==0 && set_index==head_set) random_tag=head_address[31:7];
                    if (sample%7==0) random_tag[sample%25+7]=1'bx;
                    if (sample%13==0) random_tag[sample%25+7]=1'bz;
                    tag_memory_flat[(way*4+set_index)*25+:25]=random_tag;
                end
            end
            if (sample%19==0) next_address[sample%32]=1'bx;
            if (sample%23==0) next_address[sample%32]=1'bz;
            if (sample%29==0) request_count=1'bx;
            if (sample%31==0) req_valid=1'bz;
            if (sample%37==0) fg_state[sample%2]=1'bx;
            if (sample%41==0) head_set[sample%2]=1'bz;
            if (sample%43==0) next_set[sample%2]=1'bx;
            if (sample%47==0) miss_set[sample%2]=1'bz;
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
