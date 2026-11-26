#!/usr/bin/env python3
"""验证偏置地址检查的全部输入及四态传播，并核对矩阵模块中的组合替换。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
WIDTHS = (1, 2, 3, 7, 16, 31, 32, 33, 64)
SOURCE = 'rtl/npu/top/npu_bias_address_zero.sv'
PARENT = 'rtl/npu/top/npu_matrix_engine.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code(text):
    return re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='HEAD')
    args = parser.parse_args()
    args.reference = subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolve([ROOT/SOURCE], ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    original = code(subprocess.check_output(['git', 'show', args.reference+':'+PARENT], cwd=ROOT, text=True))
    current = code((ROOT/PARENT).read_text())
    instance = re.search(r'npu_bias_address_zero\s*#\(\.p_width\(p_controller_bias_w\)\)\s*u_bias_zero\s*\((.*?)\);', current, re.S)
    if instance is None:
        raise RuntimeError('未找到矩阵模块中的偏置检查实例')
    expected = ".i_base(p_controller_bias_w'(i_bias_base)),.i_ws_channel(frame_exec_column),.i_is_channel(frame_exec_p0),.i_is_mode(o_is_mode),.o_zero(bias_zero_o_equal)"
    if re.sub(r'\s+', '', instance[1]) != expected:
        raise RuntimeError('矩阵模块中的偏置检查端口连接不同')
    current = current[:instance.start()]+current[instance.end():]
    reference_instance = re.search(r'npu_bias_address_zero\s*#\(\.p_width\(p_controller_bias_w\)\)\s*u_bias_zero\s*\((.*?)\);', original, re.S)
    if reference_instance is not None:
        if re.sub(r'\s+', '', reference_instance[1]) != expected:
            raise RuntimeError('参考矩阵模块中的偏置检查端口连接不同')
        original = original[:reference_instance.start()]+original[reference_instance.end():]
    else:
        original = re.sub(r'\s*logic\s+(?:\[p_controller_bias_w-1:0\]\s+)?bias_zero_i_\w+\s*;', '', original)
        original, count = re.subn(r'assign bias_zero_i_base =.*?\.o_equal\(bias_zero_o_equal\)\s*\n\s*\);', '', original, flags=re.S)
        if count != 1:
            raise RuntimeError('未找到完整偏置零地址检查')
    if re.sub(r'\s+', '', original) != re.sub(r'\s+', '', current):
        raise RuntimeError('矩阵模块存在组合检查之外的功能变更')

    formal = out/'formal.sv'
    formal.write_text('''module proof #(parameter WIDTH=32)(
input logic[WIDTH-1:0]base,input logic[31:0]ws,is_channel,input logic mode,output logic equal);
logic candidate,reference_zero;logic[31:0]offset;
assign offset=(mode?is_channel:ws)<<2;
npu_bias_address_zero #(.p_width(WIDTH)) u_candidate(.i_base(base),.i_ws_channel(ws),.i_is_channel(is_channel),.i_is_mode(mode),.o_zero(candidate));
add_equal #(.p_width(WIDTH),.p_preserve_bits(1)) u_reference(.i_a(base),.i_b(WIDTH'(offset)),.i_target(WIDTH'(0)),.i_carry_in(1'b0),.o_equal(reference_zero));
assign equal=(candidate===reference_zero)&&(candidate==((base+WIDTH'(offset))==WIDTH'(0)));
endmodule
''')

    def prove(width):
        script, log = out/f'w{width}.ys', out/f'w{width}.log'
        script.write_text(f'read_slang --top proof -GWIDTH={width} '+
            shlex.join(list(map(str, sources))+[str(formal)])+
            '\nprep -top proof -flatten\ncheck -assert\n'+
            'sat -verify -prove equal 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script],
                check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=180)
        if 'SUCCESS!' not in log.read_text():
            raise RuntimeError('形式检查未完成：'+str(log))
        print(width, 'PASS', flush=True)
        return {'width': width, 'inputs_constrained': False, 'passed': True, 'log_sha256': digest(log)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        checks = list(pool.map(prove, WIDTHS))
    tb = ['module tb;logic[63:0] base;logic[31:0] ws,is_channel,offset;logic mode;integer checks=0;',
          'assign offset=(mode?is_channel:ws)<<2;']
    for width in WIDTHS:
        tb += [f'wire c{width},r{width};',
            f'npu_bias_address_zero #(.p_width({width})) u_c{width}(.i_base(base[{width-1}:0]),.i_ws_channel(ws),.i_is_channel(is_channel),.i_is_mode(mode),.o_zero(c{width}));',
            f"add_equal #(.p_width({width}),.p_preserve_bits(1)) u_r{width}(.i_a(base[{width-1}:0]),.i_b({width}'(offset)),.i_target({width}'(0)),.i_carry_in(1'b0),.o_equal(r{width}));"]
    tb += ['initial begin for(integer sample=0;sample<32768;sample++)begin',
        'base={$urandom,$urandom};ws=$urandom;is_channel=$urandom;mode=sample[0];',
        'case(sample%12)', "0:base[(sample/12)%64]=1'bx;", "1:base[(sample/12)%64]=1'bz;",
        "2:ws[(sample/12)%32]=1'bx;", "3:is_channel[(sample/12)%32]=1'bz;",
        "4:mode=1'bx;", "5:mode=1'bz;", "6:begin base=0;ws=0;is_channel=0;end",
        "7:base=64'(-32'(is_channel<<2));", "8:begin ws='x;is_channel='x;end",
        'default:begin end', 'endcase', '#1;']
    for width in WIDTHS:
        tb += [f'if(c{width}!==r{width})$fatal(1,"偏置检查四态结果不同 width={width}");checks++;']
    tb += ['end $display("PASS checks=%0d",checks);$finish;end endmodule']
    bench, binary = out/'tb.sv', out/'tb.vvp'
    bench.write_text('\n'.join(tb)+'\n')
    with (out/'compile.log').open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(binary), *map(str, sources), str(bench)],
            check=True, stdout=stream, stderr=subprocess.STDOUT)
    result = subprocess.check_output(['vvp', str(binary)], text=True, timeout=180)
    (out/'four_state.log').write_text(result)
    total = len(WIDTHS)*32768
    if f'PASS checks={total}' not in result:
        raise RuntimeError('四态检查数量不足')
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in sources}:
        raise RuntimeError('检查期间源文件发生变化')
    report = {'passed': True, 'source_sha256': hashes, 'formal': checks,
        'four_state_comparisons': total, 'parent_replacement': {'source': PARENT,
            'source_sha256': digest(ROOT/PARENT), 'reference': args.reference,
            'complete_remaining_functional_tokens_identical': True, 'ports_verified': True}}
    (out/'validation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(total, 'four-state comparisons PASS', flush=True)


if __name__ == '__main__':
    main()
