#!/usr/bin/env python3
"""逐周期比较写入分页模块在二值、未知值和高阻值输入下的输出。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/axi_write_page_guard.sv')
sys.path.insert(0, str(ROOT / 'test'))
from four_state_inputs import packed_width, coverage_declarations, coverage_tasks, parse_coverage


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='c9614d3f52d8cdb7baafeebffa26325d05d5a40d')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (args.source_root / SOURCE).read_text()
    reference_commit = subprocess.check_output(['git','rev-parse',args.reference],cwd=ROOT,text=True).strip()
    reference = subprocess.check_output(['git', 'show', f'{reference_commit}:{SOURCE}'],
                                        cwd=ROOT, text=True)
    paths = []
    for label, text in [('current', current), ('reference', reference)]:
        path = out / (label + '.sv')
        path.write_text(text.replace('module axi_write_page_guard #(', f'module guard_{label} #(', 1))
        paths.append(path)
    header = re.sub(r'/\*[\s\S]*?\*/|//[^\n]*', '', current[:current.index(');')])
    ports = []
    for match in re.finditer(r'(input|output)\s+logic\s*(\[[^]]*\])?\s*'
                            r'([A-Za-z_]\w*(?:\s*,\s*(?!input\b|output\b)[A-Za-z_]\w*)*)', header):
        for name in re.sub(r'\s+', '', match[3]).split(','):
            ports.append((match[1], match[2] or '', name))
    if len(ports) != 31:
        raise RuntimeError('写入分页端口提取结果与实际接口不同')
    declarations, current_ports, reference_ports = [], [], []
    inputs, outputs_current, outputs_reference = [], [], []
    for direction, width, name in ports:
        if direction == 'input':
            declarations.append(f'    reg {width} {name};')
            current_ports.append(f'.{name}({name})')
            reference_ports.append(f'.{name}({name})')
            if name not in ('clk', 'rst_n'):
                inputs.append(name)
        else:
            declarations.append(f'    wire {width} current_{name}, reference_{name};')
            current_ports.append(f'.{name}(current_{name})')
            reference_ports.append(f'.{name}(reference_{name})')
            outputs_current.append('current_' + name)
            outputs_reference.append('reference_' + name)
    input_concat = '{' + ','.join(inputs) + '}'
    input_width = ' + '.join(packed_width(width) for direction, width, name in ports
                             if direction == 'input' and name not in ('clk', 'rst_n'))
    current_concat = '{' + ','.join(outputs_current) + '}'
    reference_concat = '{' + ','.join(outputs_reference) + '}'
    bench = out / 'four_state.sv'
    bench.write_text('module four_state #(parameter ADDR_W=32, DATA_W=64, WRITE_OUTSTANDING=4);\n' +
        '\n'.join(declarations) + '\n' +
        '    guard_current #(.ADDR_W(ADDR_W), .DATA_W(DATA_W), .WRITE_OUTSTANDING(WRITE_OUTSTANDING)) current_dut(' +
        ','.join(current_ports) + ');\n' +
        '    guard_reference #(.ADDR_W(ADDR_W), .DATA_W(DATA_W), .WRITE_OUTSTANDING(WRITE_OUTSTANDING)) reference_dut(' +
        ','.join(reference_ports) + ');\n' + f'''
    localparam INPUT_BITS = {input_width};
    localparam BYTES=DATA_W/8, SIZE=$clog2(BYTES);
    reg [INPUT_BITS-1:0] samples;
    reg [31:0] random_state = 32'h924fad31;
    integer cycle=0, bit_index, choice;
    integer direct_addresses=0, split_addresses=0, physical_addresses=0;
    integer physical_data=0, physical_responses=0, logical_responses=0, stalled_cycles=0;
    bit count_events=0;
    {coverage_declarations('INPUT_BITS')}
    {coverage_tasks('INPUT_BITS', input_concat)}
    function automatic [31:0] step(input [31:0] value);
        reg [31:0] next_value;
        begin
            next_value = value ^ (value << 13);
            next_value = next_value ^ (next_value >> 17);
            step = next_value ^ (next_value << 5);
        end
    endfunction
    task automatic compare_outputs;
        if ({current_concat} !== {reference_concat})
            $fatal(1, "Write page output mismatch at cycle %0d", cycle);
    endtask
    task automatic tick;
    begin
        clk=0;observe_inputs();#1;compare_outputs();
        if(count_events && rst_n===1'b1)begin
            if(s_awvalid===1'b1 && current_s_awready===1'b1)begin
                if(current_dut.page_local===1'b1)direct_addresses++;
                else if(current_dut.page_local===1'b0)split_addresses++;
            end
            if(current_m_awvalid===1'b1 && m_awready===1'b1)physical_addresses++;
            if(current_m_wvalid===1'b1 && m_wready===1'b1)physical_data++;
            if(m_bvalid===1'b1 && current_m_bready===1'b1)physical_responses++;
            if(current_s_bvalid===1'b1 && s_bready===1'b1)logical_responses++;
            if((current_m_awvalid===1'b1 && m_awready===1'b0) ||
               (current_m_wvalid===1'b1 && m_wready===1'b0))stalled_cycles++;
        end
        clk=1;#1;compare_outputs();clk=0;cycle++;
    end
    endtask
    initial begin
        initialize_input_coverage();
        clk=0;rst_n=0;{input_concat}='0;tick();rst_n=1;
        // 单拍页内请求与三拍跨页请求覆盖直接传输及两段响应合并。
        count_events=1;m_awready=1;m_wready=1;s_bready=1;
        s_awaddr=ADDR_W'(128);s_awlen=0;s_awsize=3'(SIZE);s_awburst=1;
        s_awvalid=1;s_wstrb='1;s_wdata='1;s_wlast=1;tick();
        s_awvalid=0;s_wvalid=1;tick();s_wvalid=0;m_bvalid=1;tick();m_bvalid=0;tick();
        s_awaddr=ADDR_W'(4096-BYTES);s_awlen=2;s_awvalid=1;tick();s_awvalid=0;
        begin : split_transfer
            integer remaining=3;
            for(integer step_index=0;step_index<80;step_index++)begin
                m_awready=step_index%3!=0;m_wready=step_index%4!=0;
                s_wvalid=remaining!=0;s_wlast=remaining==1;
                m_bvalid=current_dut.state==current_dut.RESPONSE;
                m_bresp=2'b10;
                #1;if(s_wvalid===1'b1 && current_s_wready===1'b1)remaining--;
                tick();
            end
            if(remaining!=0 || current_idle!==1'b1)$fatal(1,"Directed split transfer did not complete");
        end
        if(direct_addresses!=1 || split_addresses!=1 || physical_addresses!=3 ||
           physical_data!=4 || physical_responses!=3 || logical_responses!=2 || stalled_cycles==0)
            $fatal(1,"Directed write transaction coverage incomplete");
        count_events=0;
        // 每个输入位独立经历 0、1、X、Z，其他输入保持已知。
        for(integer selected=0;selected<INPUT_BITS;selected++)begin
            rst_n=0;{input_concat}='0;tick();rst_n=1;
            for(integer state_index=0;state_index<4;state_index++)begin
                samples='0;
                case(state_index)
                    0:samples[selected]=1'b0;1:samples[selected]=1'b1;
                    2:samples[selected]=1'bx;3:samples[selected]=1'bz;
                endcase
                {input_concat}=samples;tick();
            end
        end
        for (integer sample=0;sample<16384;sample++) begin
            rst_n = sample % 37 != 0;
            for (bit_index = 0; bit_index < INPUT_BITS; bit_index = bit_index + 1) begin
                random_state = step(random_state);
                choice = sample < 8192 ? int'(random_state[0]) : int'(random_state[1:0]);
                case (choice)
                    0: samples[bit_index] = 1'b0;
                    1: samples[bit_index] = 1'b1;
                    2: samples[bit_index] = 1'bx;
                    3: samples[bit_index] = 1'bz;
                endcase
            end
            {input_concat} = samples;
            tick();
        end
        check_input_coverage();
        $display("WRITE_PAGE_EVENTS direct=%0d split=%0d addresses=%0d data=%0d physical_responses=%0d logical_responses=%0d stalls=%0d",
            direct_addresses,split_addresses,physical_addresses,physical_data,physical_responses,logical_responses,stalled_cycles);
        $display("WRITE_PAGE_FOUR_STATE_PASS cycles=%0d comparisons=%0d",cycle,2*cycle);
        $finish;
    end
endmodule
''')
    report = {'passed': False, 'reference_commit': reference_commit,
              'source_sha256': digest(args.source_root / SOURCE),
              'test_source_sha256': digest(Path(__file__)), 'profiles': []}
    for address_width, data_width in [(32, 32), (32, 64), (12, 8), (40, 128)]:
        name = f'address{address_width}_data{data_width}'
        binary = out / (name + '.vvp')
        run(['iverilog', '-g2012', '-s', 'four_state', f'-Pfour_state.ADDR_W={address_width}',
             f'-Pfour_state.DATA_W={data_width}', '-o', str(binary),
             *(str(p) for p in paths), str(bench)], out / (name + '_build.log'))
        log = out / (name + '.log')
        run(['vvp', str(binary)], log)
        result=log.read_text()
        count=re.search(r'WRITE_PAGE_FOUR_STATE_PASS cycles=(\d+) comparisons=(\d+)',result)
        events=re.search(r'WRITE_PAGE_EVENTS direct=(\d+) split=(\d+) addresses=(\d+) data=(\d+) '
                         r'physical_responses=(\d+) logical_responses=(\d+) stalls=(\d+)',result)
        if not count or not events:
            raise RuntimeError('写入分页四态比较未完成')
        report['profiles'].append({'address_width': address_width, 'data_width': data_width,
                                  'passed': True, 'cycles': int(count[1]), 'comparisons': int(count[2]),
                                  'input_coverage':parse_coverage(result),
                                  'directed_events':dict(zip(('direct_addresses','split_addresses','physical_addresses',
                                      'physical_data','physical_responses','logical_responses','stalled_cycles'),map(int,events.groups()))),
                                  'log_sha256': digest(log)})
    if report['source_sha256']!=digest(args.source_root/SOURCE):
        raise RuntimeError('验证期间生产源码发生变化')
    report['coverage_helper_sha256']=digest(ROOT/'test/four_state_inputs.py')
    report['passed'] = True
    report['comparisons'] = sum(row['comparisons'] for row in report['profiles'])
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
