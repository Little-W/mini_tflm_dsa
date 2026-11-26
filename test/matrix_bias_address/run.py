#!/usr/bin/env python3
"""验证执行偏置地址的完整输入空间、位宽转换与四态传播。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.rtl.source_files import with_dependencies

WIDTHS = (1, 8, 16, 19, 29, 32, 40, 64)
SOURCE = ROOT / 'rtl/npu/top/npu_bias_execution_address.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=240)
    return log.read_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = with_dependencies([SOURCE], ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    parent = ROOT / 'rtl/npu/top/npu_matrix_engine.sv'
    parent_text = re.sub(r'\s+', '', parent.read_text())
    binding = ('npu_bias_execution_address#(.p_base_width(p_reg_width))u_bias_execution_address('
               '.i_base(bias_execution_address_i_base),.i_channel(bias_execution_address_i_channel),'
               '.o_address(bias_execution_address_o_address));')
    connections = ('assignbias_execution_address_i_base=i_bias_base;',
                   'assignbias_execution_address_i_channel=exec_channel;',
                   'assignexec_bias_address=bias_execution_address_o_address;')
    if binding not in parent_text or any(item not in parent_text for item in connections):
        raise RuntimeError('矩阵偏置地址模块的实际参数或连接不同')
    model = out / 'proof.sv'
    model.write_text('''// 比较实际地址模块与完整偏置地址表达式。
module proof #(parameter W=32)(
    input wire [W-1:0] base, // 任意偏置字节基址
    input wire [31:0] channel, // 任意执行通道编号
    output wire [31:0] actual, // 实际地址输出
    output wire [31:0] expected, // 完整表达式的地址输出
    output wire equivalent // 两种地址表达式逐位相同
);
    npu_bias_execution_address #(.p_base_width(W)) u_current(
        .i_base(base), .i_channel(channel), .o_address(actual));
    assign expected = base + (channel << 2);
    assign equivalent = actual == expected;
endmodule
''')
    bench = out / 'tb.sv'
    bench.write_text('''// 覆盖完整未知输入、逐位未知输入和左移移出位段。
module tb;
    parameter W=32;
    localparam BITS=W+32;
    reg [BITS-1:0] value, known;
    wire [31:0] actual, expected;
    wire equivalent;
    integer seed=32'h72c9513d, checks=0, choice;
    proof #(.W(W)) u_test(.base(value[0+:W]), .channel(value[W+:32]),
        .actual(actual), .expected(expected), .equivalent(equivalent));
    function automatic [31:0] random_word;
        seed=seed^(seed<<13); seed=seed^(seed>>17); seed=seed^(seed<<5);
        return seed;
    endfunction
    task check;
        begin
            #1; checks++;
            if(actual!==expected) $fatal(1,"Bias address W=%0d value=%h expected=%h actual=%h",W,value,expected,actual);
        end
    endtask
    initial begin
        value='0; check(); value='1; check();
        for(integer sample=0;sample<8192;sample++) begin
            for(integer bit_index=0;bit_index<BITS;bit_index++) begin
                choice=random_word()%(sample<4096?2:4);
                case(choice)
                    0:value[bit_index]=0; 1:value[bit_index]=1;
                    2:value[bit_index]=1'bx; 3:value[bit_index]=1'bz;
                endcase
            end
            check();
        end
        for(integer sample=0;sample<64;sample++) begin
            for(integer bit_index=0;bit_index<BITS;bit_index++) known[bit_index]=1'(random_word());
            for(integer bit_index=0;bit_index<BITS;bit_index++) begin
                value=known; value[bit_index]=1'bx; check();
                value=known; value[bit_index]=1'bz; check();
            end
        end
        value='x; check(); value='z; check();
        $display("BIAS_ADDRESS_PASS checks=%0d",checks); $finish;
    end
endmodule
''')
    records = []
    for mode in ('generic', 'fpga'):
        definitions = ['-USYNTHESIS', '-UXILINX_FPGA'] if mode == 'generic' else ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']
        for width in WIDTHS:
            name = f'{mode}_{width}'
            script, log = out / (name+'.ys'), out / (name+'_formal.log')
            script.write_text('read_slang --top proof '+shlex.join(
                [*definitions, f'-GW={width}', *map(str, sources), str(model)])+
                '\nprep -top proof -flatten\ncheck -assert\nsat -verify -prove equivalent 1\n')
            text = execute([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
            if 'SUCCESS!' not in text:
                raise RuntimeError('完整地址输入证明未完成：'+name)
            binary = out / (name+'.vvp')
            flags = [] if mode == 'generic' else definitions
            execute(['iverilog', '-g2012', '-s', 'tb', f'-Ptb.W={width}', *flags,
                     '-o', binary, *sources, model, bench], out / (name+'_compile.log'))
            four_log = out / (name+'_four_state.log')
            text = execute(['vvp', binary], four_log)
            count = re.search(r'BIAS_ADDRESS_PASS checks=(\d+)', text)
            if not count:
                raise RuntimeError('地址四态检查未完成：'+name)
            binary.unlink()
            records.append(dict(mode=mode, base_width=width, passed=True,
                                four_state_checks=int(count[1]),
                                formal_log_sha256=digest(log), four_state_log_sha256=digest(four_log)))
            print(name, 'PASS', count[1], flush=True)
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in sources}:
        raise RuntimeError('检查期间地址模块发生变化')
    report = dict(passed=True, input_constraints=[], profiles=records,
                  four_state_checks=sum(row['four_state_checks'] for row in records),
                  source_sha256=hashes, matrix_binding_checked=True,
                  matrix_sha256=digest(parent), runner_sha256=digest(Path(__file__)))
    (out/'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
