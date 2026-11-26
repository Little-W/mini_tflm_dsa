#!/usr/bin/env python3
"""验证帧分块数、条件加一及矩阵模块中的完整组合替换。"""
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
PROFILES = [(0, 0), (1, 0), (2, 1), (3, 2), (7, 3), (8, 3), (16, 4),
            (32, 5), (64, 6), (1024, 10), (65536, 16), (2147483648, 31),
            (16, 0), (16, 3), (16, 5)]
WIDTHS = (1, 2, 4, 7, 16, 28, 32, 64)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tokens(text):
    return re.sub(r'\s+', '', re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='HEAD')
    args = parser.parse_args()
    reference = subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT/'rtl/npu/top/npu_frame_row_tiles.sv'
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolve([source], ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    parent = ROOT/'rtl/npu/top/npu_matrix_engine.sv'
    original = subprocess.check_output(['git', 'show', reference+':'+str(parent.relative_to(ROOT))],
                                       cwd=ROOT, text=True)
    current = parent.read_text()
    pattern = r'npu_frame_row_tiles\s*#\(\.p_tile_size\(p_size\),\s*\.p_tile_shift\(p_size_shift\)\)\s*u_frame_row_tiles\s*\((.*?)\);'
    instance = re.search(pattern, current, re.S)
    assert instance and tokens(instance[1]) == '.i_rows(frame_exec_rows),.o_tiles(exec_row_tiles)'
    reconstructed = current[:instance.start()] + "assign exec_row_rounded = frame_exec_rows + 32'(p_size-1);" + current[instance.end():]
    reconstructed = reconstructed.replace('logic [31:0] exec_row_tiles;', 'logic [31:0] exec_row_rounded;')
    reconstructed = reconstructed.replace('o_frame_mode_q ? exec_row_tiles : i_cfg_row_tail_tiles',
                                        'o_frame_mode_q ? (exec_row_rounded >> p_size_shift) : i_cfg_row_tail_tiles')
    reference_instance = re.search(pattern, original, re.S)
    if reference_instance:
        assert tokens(reference_instance[1]) == '.i_rows(frame_exec_rows),.o_tiles(exec_row_tiles)'
        assert tokens(current) == tokens(original), '矩阵模块存在分块数计算之外的功能变化'
    else:
        assert tokens(reconstructed) == tokens(original), '矩阵模块存在分块数计算之外的功能变化'

    formal = out/'formal.sv'
    formal.write_text('''// 检查全部输入下的帧分块数与条件加一结果。
module proof #(parameter SIZE=16, SHIFT=4, WIDTH=28)(
 input logic [31:0] rows, // 完整帧行数
 input logic [WIDTH-1:0] value, // 任意定宽数值
 input logic enable, // 条件加一使能
 output logic equal // 两项运算均与定宽算术一致
);
wire [31:0] tiles,reference_tiles;
wire [WIDTH-1:0] result;
assign reference_tiles=(rows+32'(SIZE-1))>>SHIFT;
npu_frame_row_tiles #(.p_tile_size(SIZE),.p_tile_shift(SHIFT)) u_tiles(rows,tiles);
conditional_increment #(.p_width(WIDTH)) u_increment(value,enable,result);
assign equal=(tiles==reference_tiles)&&(result==(value+WIDTH'(enable)));
endmodule
''')
    jobs = [(size, shift, WIDTHS[index % len(WIDTHS)]) for index, (size, shift) in enumerate(PROFILES)]

    def prove(job):
        size, shift, width = job
        stem = f'size_{size}_shift_{shift}_width_{width}'
        script, log = out/(stem+'.ys'), out/(stem+'.log')
        selected = out/(stem+'.sv')
        selected.write_text(formal.read_text().replace('parameter SIZE=16, SHIFT=4, WIDTH=28',
                            f"parameter SIZE=32'd{size}, SHIFT={shift}, WIDTH={width}"))
        flags = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']
        script.write_text('read_slang --top proof '+shlex.join(flags+list(map(str, sources))+[str(selected)])+
                          '\nprep -top proof -flatten\ncheck -assert\nsat -verify -prove equal 1 -show-inputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script],
                           stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=240)
        assert 'SUCCESS!' in log.read_text()
        return dict(tile_size=size, tile_shift=shift, increment_width=width, passed=True,
                    log_sha256=digest(log))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(prove, jobs))
    tb = ['// 帧分块数和条件加一的严格四态比较。',
          'module tb; reg [31:0] rows;reg [63:0] value;reg enable;integer checks=0;',
          "integer rng=32'h1137e2c9;",
          'function automatic [31:0] random_word; rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;endfunction']
    for index, (size, shift) in enumerate(PROFILES):
        tb += [f'wire [31:0] t{index},r{index};',
               f'npu_frame_row_tiles #(.p_tile_size(32\'d{size}),.p_tile_shift({shift})) u_t{index}(rows,t{index});',
               f"assign r{index}=(rows+32'(32'd{size}-1))>>{shift};"]
    for width in WIDTHS:
        tb += [f'wire [{width-1}:0] v{width},e{width};',
               f'conditional_increment #(.p_width({width})) u_v{width}(value[{width-1}:0],enable,v{width});',
               f"assign e{width}=value[{width-1}:0]+{width}'(enable);"]
    tb += ['initial begin for(integer sample=0;sample<32768;sample++)begin',
           'rows=random_word();value={random_word(),random_word()};enable=sample[0];',
           'case(sample%16)', '0:begin rows=0;value=0;end', "1:begin rows='1;value='1;end",
           '2:rows=16;', '3:rows=17;', "4:rows[0]=1'bx;", "5:rows[(sample/16)%32]=1'bz;",
           "6:value[(sample/16)%64]=1'bx;", "7:value[(sample/16)%64]=1'bz;",
           "8:enable=1'bx;", "9:enable=1'bz;", "10:rows='x;", "11:value='z;",
           'default:begin end endcase #1;']
    for index in range(len(PROFILES)):
        tb.append(f'if(t{index}!==r{index})$fatal(1,"Frame row tiles differ profile={index}");checks++;')
    for width in WIDTHS:
        tb.append(f'if(v{width}!==e{width})$fatal(1,"Conditional increment differs width={width}");checks++;')
    tb += ['end $display("FRAME_ROW_TILES_FOUR_STATE_PASS checks=%0d",checks);$finish;end endmodule']
    bench, binary = out/'tb.sv', out/'tb.vvp'
    bench.write_text('\n'.join(tb)+'\n')
    with (out/'compile.log').open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(binary), *map(str, sources), str(bench)],
                       stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.check_output(['vvp', str(binary)], text=True, timeout=240)
    (out/'four_state.log').write_text(result)
    total = (len(PROFILES)+len(WIDTHS))*32768
    assert f'PASS checks={total}' in result
    assert hashes == {str(path.relative_to(ROOT)): digest(path) for path in sources}
    assert current == parent.read_text()
    report = dict(passed=True, source_sha256=hashes, formal=results,
                  input_assumptions=[], four_state_comparisons=total,
                  four_state_log_sha256=digest(out/'four_state.log'),
                  parent_replacement=dict(reference=reference, source_sha256=digest(parent),
                                          ports_verified=True, complete_remaining_functional_tokens_identical=True),
                  test_sha256=digest(Path(__file__)))
    (out/'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('FRAME_ROW_TILES_PASS', len(results), total, flush=True)


if __name__ == '__main__':
    main()
