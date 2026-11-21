#!/usr/bin/env python3
"""检查线性 DMA 的字节旋转、末拍比较和相邻计数的四态行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def section(text, start, end):
    begin = text.index(start)
    return text[begin:text.index(end, begin)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rtl', type=Path, default=ROOT / 'rtl/npu/dma/axi_linear_block_dma.sv')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    rtl = args.rtl.resolve()
    source = rtl.read_text()
    comparator = ROOT / 'rtl/common/add_equal.sv'
    comparator_copy = out / comparator.name
    comparator_copy.write_bytes(comparator.read_bytes())
    hashes = {str(path): sha(path) for path in [rtl, comparator, Path(__file__).resolve()]}
    rotation = section(source, '    // 同一字节旋转', '    always_comb begin\n        wr_aligned_wdata')
    counter = section(source, '    // 相邻计数提前并行形成', '    logic wr_done_r;')
    read_compare = section(source, '    localparam int unsigned p_read_last_groups',
                           '    // 末拍和末行条件并行准备')
    write_compare = section(source, '    localparam int unsigned p_row_equal_groups', '    wire wr_row_end =')
    records = []
    for bus, count_width in [(32, 1), (64, 3), (128, 5), (256, 9)]:
        folder = out / f'b{bus}_c{count_width}'
        folder.mkdir(exist_ok=True)
        bench = folder / 'tb.sv'
        bench.write_text(f'''module tb;
    localparam int BUS_WIDTH={bus}, BYTE_PER_BEAT=BUS_WIDTH/8;
    localparam int ADDR_LSB=$clog2(BYTE_PER_BEAT), BEAT_CNT_W=9, WR_OUTS_W={count_width};
    typedef logic [BEAT_CNT_W-1:0] beat_count_t;
    typedef struct packed {{logic [7:0] burst_len_m1; beat_count_t cross_last; logic linear_read;}} head_t;
    head_t rd_head;
    logic [BUS_WIDTH-1:0] src_wdata;
    logic [BYTE_PER_BEAT-1:0] src_wmask;
    logic [ADDR_LSB-1:0] wr_row_offset;
    logic [2*BUS_WIDTH-1:0] wr_shifted_data;
    logic [2*BYTE_PER_BEAT-1:0] wr_shifted_mask;
    logic [WR_OUTS_W-1:0] wr_pending_data_cnt;
    beat_count_t rd_rsp_beat_cnt, wr_beat_cnt, wr_cfg_cross_last;
    logic [7:0] wr_burst, unknown_burst;
    logic rd_rsp_last_without_cross, rd_rsp_last_with_cross;
    logic rsp_last_equal_o_equal;
    logic [BEAT_CNT_W-1:0] helper_a, helper_b;
    logic helper_carry;
    logic expected_read_plain, expected_read_cross, expected_write_cross;
    logic [2*BUS_WIDTH-1:0] expected_data;
    logic [2*BYTE_PER_BEAT-1:0] expected_mask;
    logic [WR_OUTS_W-1:0] expected_inc, expected_dec;
    integer checks=0;
    integer rng=32'h13579bdf;
    assign helper_a=beat_count_t'(rd_head.burst_len_m1);
    assign helper_b=beat_count_t'(1);
    assign helper_carry=1'b0;
    add_equal #(.p_width(BEAT_CNT_W),.p_use_lut(1'b0)) helper(
        .i_a(helper_a),.i_b(helper_b),.i_target(rd_rsp_beat_cnt),
        .i_carry_in(helper_carry),.o_equal(rsp_last_equal_o_equal));
{rotation}
{counter}
{read_compare}
{write_compare}
    task automatic verify;
        begin
            rd_head.cross_last=beat_count_t'(rd_head.burst_len_m1)+beat_count_t'(1);
            wr_cfg_cross_last=beat_count_t'(wr_burst)+beat_count_t'(1);
            #1;
            expected_data={{{{BUS_WIDTH{{1'b0}}}},src_wdata}} << {{wr_row_offset,3'b000}};
            expected_mask={{{{BYTE_PER_BEAT{{1'b0}}}},src_wmask}} << wr_row_offset;
            expected_inc=wr_pending_data_cnt+WR_OUTS_W'(1);
            expected_dec=wr_pending_data_cnt-WR_OUTS_W'(1);
            expected_read_plain=rd_head.linear_read ? rd_rsp_beat_cnt==beat_count_t'(0) :
                rd_rsp_beat_cnt==beat_count_t'(rd_head.burst_len_m1);
            expected_read_cross=rd_head.linear_read ? rd_rsp_beat_cnt==beat_count_t'(1) :
                rsp_last_equal_o_equal;
            expected_write_cross=wr_beat_cnt==(beat_count_t'(wr_burst)+beat_count_t'(1));
            if(wr_shifted_data!==expected_data || wr_shifted_mask!==expected_mask)
                $fatal(1,"byte selection mismatch");
            if(wr_pending_increment!==expected_inc || wr_pending_decrement!==expected_dec)
                $fatal(1,"count arithmetic mismatch");
            if(rd_rsp_last_without_cross!==expected_read_plain || rd_rsp_last_with_cross!==expected_read_cross)
                $fatal(1,"read completion comparison mismatch");
            if(wr_cross_row_end!==expected_write_cross)
                $fatal(1,"write completion comparison mismatch");
            checks+=7;
        end
    endtask
    initial begin
        for(integer sample=0;sample<4000;sample++) begin
            for(integer bit_index=0;bit_index<BUS_WIDTH;bit_index++)
                src_wdata[bit_index]=$random(rng);
            src_wmask=$random(rng); wr_row_offset=ADDR_LSB'(sample);
            wr_pending_data_cnt=$random(rng); rd_rsp_beat_cnt=$random(rng);
            wr_beat_cnt=$random(rng); wr_burst=$random(rng);
            rd_head.burst_len_m1=$random(rng); rd_head.linear_read=sample%2;
            if(sample%3==0) rd_rsp_beat_cnt=beat_count_t'(rd_head.burst_len_m1)+beat_count_t'(sample%2);
            if(sample%5==0) wr_beat_cnt=beat_count_t'(wr_burst)+beat_count_t'(1);
            if(sample%7==0) wr_pending_data_cnt='0;
            if(sample%11==0) wr_pending_data_cnt='1;
            verify();
            if(sample%2==0) begin
                src_wdata[sample%BUS_WIDTH]=1'bx; src_wmask[sample%BYTE_PER_BEAT]=1'bz;
                verify();
            end
            if(sample%5==0) begin
                wr_row_offset[sample%ADDR_LSB]=1'bx;
                wr_pending_data_cnt[sample%WR_OUTS_W]=1'bz;
                rd_rsp_beat_cnt[sample%BEAT_CNT_W]=1'bx;
                wr_burst[sample%8]=1'bz;
                verify();
            end
            if(sample%13==0) begin
                rd_head.linear_read=1'bx;
                unknown_burst=rd_head.burst_len_m1; unknown_burst[sample%8]=1'bz;
                rd_head.burst_len_m1=unknown_burst;
                wr_beat_cnt[(sample+2)%BEAT_CNT_W]=1'bx;
                verify();
            end
        end
        $display("LINEAR_DMA_FOUR_STATE_PASS checks=%0d bus=%0d count_width=%0d",checks,BUS_WIDTH,WR_OUTS_W);
        $finish;
    end
endmodule
''')
        binary = folder / 'sim.vvp'
        commands = [['iverilog', '-g2012', '-s', 'tb', '-o', str(binary), str(bench), str(comparator_copy)],
                    ['vvp', str(binary)]]
        output = ''
        for command, name in zip(commands, ['compile.log', 'run.log']):
            result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (folder / name).write_text(result.stdout)
            if result.returncode:
                raise RuntimeError(result.stdout[-7000:])
            output = result.stdout
        match = re.search(r'LINEAR_DMA_FOUR_STATE_PASS checks=(\d+)', output)
        if not match:
            raise RuntimeError(output)
        result = dict(bus_width=bus, count_width=count_width, passed=True, checks=int(match[1]),
                      bench_sha256=sha(bench), log_sha256=sha(folder / 'run.log'))
        records.append(result)
        print(json.dumps(result), flush=True)
    if hashes != {str(path): sha(path) for path in [rtl, comparator, Path(__file__).resolve()]}:
        raise RuntimeError('Sources changed during verification')
    (out / 'summary.json').write_text(json.dumps({'passed':True, 'source_sha256':hashes,
        'strict_four_state_comparison':True, 'profiles':records}, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
