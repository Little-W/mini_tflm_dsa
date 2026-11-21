#!/usr/bin/env python3
"""检查实际查询地址选择、有效位存储与同拍转发在四态输入下的结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RTL = Path('rtl/npu/dma/cache/conv_read_cache.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def set_fields(text):
    return text.replace('.set_index', '').replace('request_queue', 'queue_set').replace('incoming_request', 'incoming_set')


def model(label, text, sets, depth):
    start = text.index('  always_comb begin\n    lookup_read_request = request_count==0')
    end = text.index('    lookup_read_word =', start)
    lookup = set_fields(text[start:end]) + '  end\n'
    start = text.index('    end else begin : g_current_lookup_valid')
    end = text.index('    assign valid_match_address[0]', start)
    capture = text[start:end].replace('    end else begin : g_current_lookup_valid',
                                     '    if (1) begin : g_current_lookup_valid', 1)
    current = 'lookup_candidate_valid' in capture
    candidates = ''
    candidate_count = 0
    if current:
        declaration = re.search(r'  logic \[(\d+):0\]\[SI-1:0\] lookup_candidate_set;', text)
        candidate_count = int(declaration[1]) + 1
        start = declaration.start()
        end = text.index('  // 填充组号与查询快照', start)
        candidates = set_fields('\n'.join(line for line in text[start:end].splitlines() if not any(name in line for name in ['lookup_candidate_word', 'lookup_candidate_fill_match', 'logic lookup_fill_match'])))
    write_start = text.index('    assign valid_i_wr_en = rst_n && metadata_enable')
    write_end = text.index(';', write_start) + 1
    write_enable = text[write_start:write_end]
    return f'''module {label} #(
    parameter integer SETS={sets}, DEMAND_DEPTH={depth}, SI=$clog2(SETS),
    DQ_AW=$clog2(DEMAND_DEPTH), DQ_CW=$clog2(DEMAND_DEPTH+1)
) (
    input wire clk, rst_n, cfg_valid, cfg_ready,
    input wire [1:0] fg_state,
    input wire req_fire, req_valid,
    input wire [DQ_CW-1:0] request_count,
    input wire [DQ_AW-1:0] request_head,
    input wire bypass_q,
    input wire [SI-1:0] demand_set, demand_fill_set, incoming_set,
    input wire [DEMAND_DEPTH-1:0][SI-1:0] queue_set,
    input wire clearing, metadata_fill, fill_way,
    input wire [SI-1:0] valid_i_wr_addr,
    input wire [0:0] valid_i_wr_data,
    output wire valid_q
);
    localparam integer PORTS={6+candidate_count};
    localparam integer WI=1, metadata_way=0;
    localparam [1:0] FG_IDLE=0, FG_MISS=1, FG_RESP=2;
    logic [SI-1:0] lookup_set, lookup_read_set, lookup_read_request;
    wire [PORTS-1:0][SI-1:0] valid_i_rd_addr;
    wire [PORTS-1:0][0:0] valid_o_rd_data;
    wire [5:0] valid_read_value;
    wire valid_i_wr_en;
    wire metadata_enable = !(cfg_valid && cfg_ready);
{write_enable}
    assign lookup_set = bypass_q ? demand_fill_set : demand_set;
    for (genvar port_index=1; port_index<6; port_index++)
        assign valid_i_rd_addr[port_index] = '0;
{lookup}
{candidates}
{capture}
    regfile #(.p_data_width(1), .p_depth(SETS), .p_addr_width(SI),
              .p_write_unit(1), .p_read_ports(PORTS), .p_sync_read(1'b0)) u_storage (
        .clk, .i_wr_en(valid_i_wr_en), .i_wr_addr(valid_i_wr_addr),
        .i_wr_data(valid_i_wr_data), .i_wr_mask(1'b1),
        .i_rd_en({{PORTS{{1'b1}}}}), .i_rd_addr(valid_i_rd_addr), .o_rd_data(valid_o_rd_data)
    );
    assign valid_q = valid_read_value[0];
endmodule
'''


def bench(sets, depth):
    si=(sets-1).bit_length();aw=(depth-1).bit_length();cw=depth.bit_length()
    fields='rst_n cfg_valid cfg_ready fg_state req_fire req_valid request_count request_head bypass_q demand_set demand_fill_set incoming_set queue_set clearing metadata_fill fill_way valid_i_wr_addr valid_i_wr_data'.split()
    instances=[]
    for label in ('reference','current'):
        instances.append(f'{label} u_{label}(.clk(clk),'+','.join(f'.{name}({name})' for name in fields)+f',.valid_q({label}_q));')
    return rf'''module tb;
    localparam integer SI={si}, DQ_AW={aw}, DQ_CW={cw}, DEMAND_DEPTH={depth};
    localparam integer WIDTH=12+DQ_CW+DQ_AW+(4+DEMAND_DEPTH)*SI;
    logic clk=0;
    wire rst_n,cfg_valid,cfg_ready,req_fire,req_valid,bypass_q,clearing,metadata_fill,fill_way;
    wire [1:0] fg_state;
    wire [DQ_CW-1:0] request_count;
    wire [DQ_AW-1:0] request_head;
    wire [SI-1:0] demand_set,demand_fill_set,incoming_set,valid_i_wr_addr;
    wire [DEMAND_DEPTH-1:0][SI-1:0] queue_set;
    wire [0:0] valid_i_wr_data;
    logic [WIDTH-1:0] stimulus=0,saved;
    assign {{{','.join(fields)}}}=stimulus;
    wire reference_q,current_q;
    {chr(10).join(instances)}
    reg [31:0] rng=32'h12c87ae5;
    integer checks=0,known_checks=0,unknown_cycles=0;
    task randomize;
        begin
            for(integer index=0;index<WIDTH;index=index+1) begin
                rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);
                stimulus[index]=rng[0];
            end
        end
    endtask
    task tick;
        begin
            #2;clk=1;#2;
            if(reference_q!==current_q)$fatal(1,"有效位保存结果不同 input=%b reference=%b current=%b",stimulus,reference_q,current_q);
            checks=checks+1;
            if(current_q===1'b0 || current_q===1'b1)known_checks=known_checks+1;
            clk=0;#1;
        end
    endtask
    initial begin
        for(integer cycle=0;cycle<4000;cycle=cycle+1)begin randomize();tick();end
        for(integer trial=0;trial<128;trial=trial+1)begin
            randomize();saved=stimulus;
            for(integer index=0;index<WIDTH;index=index+1)begin
                stimulus=saved;stimulus[index]=1'bx;tick();unknown_cycles=unknown_cycles+1;
                stimulus=saved;stimulus[index]=1'bz;tick();unknown_cycles=unknown_cycles+1;
            end
        end
        if(known_checks<1000)$fatal(1,"已确定有效位结果的检查数量不足");
        $display("{{\"passed\":true,\"checks\":%0d,\"known_result_checks\":%0d,\"four_state_cycles\":%0d}}",checks,known_checks,unknown_cycles);
        $finish;
    end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        'reference': args.reference_root.resolve() / RTL,
        'current': args.source_root.resolve() / RTL,
    }
    memory = args.source_root.resolve() / 'rtl/common/regfile.v'
    manifest = {str(path): digest(path)
                for path in [*paths.values(), memory, Path(__file__).resolve()]}
    runs = []
    for sets, depth in [(2, 2), (16, 2), (32, 4), (4, 4)]:
        name = f'sets{sets}_depth{depth}'
        source = out / (name + '.sv')
        source.write_text('\n'.join(
            model(label, path.read_text(), sets, depth)
            for label, path in paths.items()) + bench(sets, depth))
        binary = out / (name + '.vvp')
        with (out / (name + '.compile.log')).open('w') as stream:
            subprocess.run(
                ['iverilog', '-g2012', '-s', 'tb', '-o', str(binary),
                 str(memory), str(source)],
                stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
        result = subprocess.run(['vvp', str(binary)], text=True, capture_output=True, timeout=120)
        log = out / (name + '.log')
        log.write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f'四态比较未通过：{log}')
        record = json.loads(next(line for line in result.stdout.splitlines()
                                 if line.startswith('{')))
        record.update(SETS=sets, DEMAND_DEPTH=depth,
                      bench_sha256=digest(source), log_sha256=digest(log), log=str(log))
        runs.append(record)
        print(json.dumps(record), flush=True)
    if any(digest(Path(path)) != sha for path, sha in manifest.items()):
        raise RuntimeError('验证期间输入文件发生变化')
    report = {
        'passed': True,
        'source_sha256': manifest,
        'profiles': runs,
        'total_checks': sum(record['checks'] for record in runs),
    }
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
