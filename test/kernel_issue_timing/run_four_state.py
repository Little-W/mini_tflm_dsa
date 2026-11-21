#!/usr/bin/env python3
"""检查请求资格、逐维遍历及共享算术在未知值和高阻值下的精确结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
FLAGS = ('managed_mode', 'ctrl_load_req', 'comparison_stored_ready', 'comparison_match_q',
         'buf_load_commit', 'buf_discard_ready', 'transfer_active', 'ext_dma_busy',
         'buf_load_ready', 'cache_flush', 'init_cfg', 'load_weight_granted',
         'command_waiting', 'demand_confirmed')
RESULTS = ('ctrl_buf_load_ready', 'cache_hit_fire', 'discard_fire', 'buf_discard_head',
           'demand_issue', 'prefetch_issue', 'load_weight_req', 'ctrl_load_granted',
           'dma_start', 'prefetch_dma_start', 'demand_dma_start')
PRIVATE = ('cache_data_available', 'demand_data_available', 'managed_grant_ready',
           'unmanaged_grant_ready', 'managed_request_available', 'selected_request_available',
           'managed_prefetch_available', 'selected_prefetch', 'request_permitted')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def request_model(text, name):
    start = text.index('  assign ctrl_buf_load_ready =')
    stop = text.index('  assign buf_load_start =', start)
    body = text[start:stop].replace('load_idle_o_start', '(load_weight_req && load_weight_granted)')
    inputs = '\n'.join(f'    wire {signal} = inputs[{index+2}];' for index, signal in enumerate(FLAGS))
    return f'''module {name}(input wire [15:0] inputs, output wire [10:0] results);
    localparam PF_EMPTY=2'd0, PF_PENDING=2'd1, PF_LOADING=2'd2, PF_CACHED=2'd3;
    wire [1:0] prefetch_state = inputs[1:0];
{inputs}
    logic {','.join(RESULTS + PRIVATE)};
{body}
    assign results = {{{','.join(RESULTS)}}};
endmodule
'''


def traversal_model(text, name):
    sequential = text.index('  always_ff @(posedge clk or negedge rst_n) begin')
    start = text.index('            if (!last_col_in_group) begin', sequential)
    stop = text.index('\n          end\n\n          if (buf_weight_sending_done)', start)
    updates = text[start:stop].replace('<=', '=')
    qualifier = ''
    if 'advance_row' in text:
        match = re.search(r'  always_comb begin\n(    advance_row =.*?)\n  end\n\n  always_ff', text, re.S)
        if match is None:
            raise RuntimeError('找不到独立遍历资格表达式')
        qualifier = match[1]
    return f'''module {name} #(parameter integer W=29)(
    input wire [8*W+7*32-1:0] values, input wire [3:0] boundaries,
    output wire [6*W+3*32-1:0] result);
    typedef logic [W-1:0] count_t;
    logic [W-1:0] load_col_in_group,load_tile_row,load_l2,load_repeat;
    logic [W-1:0] group_base_col,current_group_width,first_group_width,following_group_width;
    logic [31:0] col_addr_offset,row_addr_offset,group_base_addr;
    logic [31:0] col_addr_step,row_addr_step,group_addr_step_q,base_addr_reg;
    logic [31:0] column_offset_increment,row_offset_increment,group_address_increment;
    logic [W-1:0] group_column_increment;
    logic [3:0][W-1:0] traversal_o_next;
    logic advance_row,advance_group,advance_repeat;
    wire last_col_in_group=boundaries[0],last_tile_row=boundaries[1];
    wire last_l2_group=boundaries[2],last_repeat=boundaries[3];
    always_comb begin
        {{load_col_in_group,load_tile_row,load_l2,load_repeat,group_base_col,current_group_width,
          first_group_width,following_group_width,col_addr_offset,row_addr_offset,group_base_addr,
          col_addr_step,row_addr_step,group_addr_step_q,base_addr_reg}} = values;
        traversal_o_next[0]=load_col_in_group+W'(1);
        traversal_o_next[1]=load_tile_row+W'(1);
        traversal_o_next[2]=load_l2+W'(1);
        traversal_o_next[3]=load_repeat+W'(1);
        column_offset_increment=col_addr_offset+col_addr_step;
        row_offset_increment=row_addr_offset+row_addr_step;
        group_column_increment=group_base_col+current_group_width;
        group_address_increment=group_base_addr+group_addr_step_q;
{qualifier}
{updates}
    end
    assign result={{load_col_in_group,load_tile_row,load_l2,load_repeat,group_base_col,current_group_width,
                    col_addr_offset,row_addr_offset,group_base_addr}};
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--scheduler-source', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    hashes = {}
    texts = {}
    for label, folder in [('reference', args.reference_root.resolve()), ('current', args.source_root.resolve())]:
        texts[label] = {}
        for name in ('kernel_loader.sv', 'kernel_loader_ctrl.sv'):
            path = folder / 'rtl/npu/loaders' / name
            hashes[str(path)] = digest(path)
            texts[label][name] = path.read_text()
    models = out / 'models.sv'
    model_text = ''.join(request_model(texts[label]['kernel_loader.sv'], label + '_request') +
                         traversal_model(texts[label]['kernel_loader_ctrl.sv'], label + '_traversal')
                         for label in texts)
    if args.scheduler_source:
        scheduler = args.scheduler_source.resolve()
        hashes[str(scheduler)] = digest(scheduler)
        assignments = []
        for signal in ('active_q_next', 'reduction_last', 'stationary_rows_last'):
            match = re.search(r'    assign ' + signal + r' = .*?;', scheduler.read_text(), re.S)
            if match is None:
                raise RuntimeError(f'找不到共享算术：{signal}')
            assignments.append(match[0])
        model_text += '''module scheduler_arithmetic_model #(
    parameter integer SIZE=16)(input logic [31:0] active_q0,reduction,stationary_rows,
    output wire [95:0] result);
    wire [31:0] active_q_next,reduction_last,stationary_rows_last;
''' + '\n'.join(assignments) + '''
    assign result={active_q_next,reduction_last,stationary_rows_last};
endmodule
'''
    models.write_text(model_text)
    reports = []
    for width, size in ((1, 1), (29, 16), (33, 32)):
        folder = out / f'w{width}_s{size}'
        folder.mkdir(exist_ok=True)
        tb = folder / 'tb.sv'
        scheduler_declarations = '''    logic [31:0] active_q0,reduction,stationary_rows;
    wire [95:0] arithmetic_actual;
    scheduler_arithmetic_model #(.SIZE(SIZE)) arithmetic_dut(active_q0,reduction,stationary_rows,arithmetic_actual);
''' if args.scheduler_source else ''
        scheduler_test = '''        for(integer sample_i=0;sample_i<4096;sample_i++)begin
            active_q0=$urandom;reduction=$urandom;stationary_rows=$urandom;
            if(sample_i>=1024)begin
                case(sample_i%6)
                    0:active_q0[sample_i%32]=1'bx;
                    1:active_q0[sample_i%32]=1'bz;
                    2:reduction[sample_i%32]=1'bx;
                    3:reduction[sample_i%32]=1'bz;
                    4:stationary_rows[sample_i%32]=1'bx;
                    5:stationary_rows[sample_i%32]=1'bz;
                endcase
            end
            #1;
            if(arithmetic_actual !== {active_q0+32'(SIZE),reduction-32'd1,stationary_rows-32'd1})
                $fatal(1,"Scheduler arithmetic differs");
            arithmetic_checks++;
        end
''' if args.scheduler_source else ''
        tb.write_text(f'''module tb;
    localparam W={width}, SIZE={size}, V=8*W+7*32;
    logic [15:0] controls;
    wire [10:0] reference_request_result,current_request_result;
    logic [V-1:0] values;
    logic [3:0] boundaries;
    wire [6*W+3*32-1:0] reference_traversal_result,current_traversal_result;
    integer request_checks=0,traversal_checks=0,arithmetic_checks=0;
    reference_request ref_request(controls,reference_request_result);
    current_request dut_request(controls,current_request_result);
    reference_traversal #(.W(W)) ref_traversal(values,boundaries,reference_traversal_result);
    current_traversal #(.W(W)) dut_traversal(values,boundaries,current_traversal_result);
{scheduler_declarations}
    function automatic logic state_bit(input integer v);
        case(v) 0:return 1'b0;1:return 1'b1;2:return 1'bx;default:return 1'bz;endcase
    endfunction
    task automatic check_request;
        #1;
        if(reference_request_result !== current_request_result)
            $fatal(1,"Request qualification differs controls=%h reference=%b current=%b",controls,reference_request_result,current_request_result);
        request_checks++;
    endtask
    task automatic check_traversal;
        #1;
        if(reference_traversal_result !== current_traversal_result)
            $fatal(1,"Traversal differs width=%0d boundaries=%b reference=%h current=%h",W,boundaries,reference_traversal_result,current_traversal_result);
        traversal_checks++;
    endtask
    initial begin
        controls='0;values='0;boundaries='0;
        for(integer pattern=0;pattern<65536;pattern++)begin
            controls=16'(pattern);check_request();
        end
        for(integer sample_i=0;sample_i<4096;sample_i++)begin
            controls=16'($urandom);
            for(integer digit=0;digit<6;digit++)
                controls[digit<2 ? digit : digit+8]=state_bit((sample_i>>(2*digit))&3);
            check_request();
        end
        for(integer pattern=0;pattern<64;pattern++)begin
            controls=16'($urandom);
            for(integer bit_i=0;bit_i<16;bit_i++)begin
                controls[bit_i]=1'bx;check_request();
                controls[bit_i]=1'bz;check_request();
                controls[bit_i]=pattern[bit_i%6];
            end
        end
        for(integer sample_i=0;sample_i<4096;sample_i++)begin
            for(integer bit_i=0;bit_i<V;bit_i++)values[bit_i]=$urandom;
            for(integer bit_i=0;bit_i<4;bit_i++)boundaries[bit_i]=state_bit((sample_i>>(2*bit_i))&3);
            if(sample_i>=256)values[sample_i%V]=state_bit(2+(sample_i%2));
            check_traversal();
        end
{scheduler_test}
        $display("KERNEL_ISSUE_FOUR_STATE_PASS request=%0d traversal=%0d arithmetic=%0d",request_checks,traversal_checks,arithmetic_checks);
        $finish;
    end
endmodule
''')
        binary = folder / 'test.vvp'
        with (folder / 'build.log').open('w') as stream:
            subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(binary), str(models), str(tb)],
                           stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=60)
        result = subprocess.run(['vvp', str(binary)], capture_output=True, text=True, timeout=120)
        log = folder / 'run.log'
        log.write_text(result.stdout + result.stderr)
        match = re.search(r'KERNEL_ISSUE_FOUR_STATE_PASS request=(\d+) traversal=(\d+) arithmetic=(\d+)', result.stdout)
        if result.returncode or match is None:
            raise RuntimeError(f'四态验证未通过：{log}')
        reports.append({'width': width, 'size': size, 'passed': True,
                        'request_checks': int(match[1]), 'traversal_checks': int(match[2]),
                        'arithmetic_checks': int(match[3]), 'log_sha256': digest(log)})
        print(json.dumps(reports[-1]), flush=True)
    if hashes != {name: digest(Path(name)) for name in hashes}:
        raise RuntimeError('验证期间输入源文件发生变化')
    report = {'passed': True, 'strict_four_state': True, 'source_sha256': hashes,
              'model_sha256': digest(models), 'profiles': reports,
              'checks': sum(row['request_checks'] + row['traversal_checks'] + row['arithmetic_checks'] for row in reports)}
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
