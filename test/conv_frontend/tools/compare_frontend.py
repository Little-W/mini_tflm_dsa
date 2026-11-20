#!/usr/bin/env python3
"""使用独立数值与控制测试，逐周期比较前端的所有公开输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rtl_reference import read_rtl_source

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TEST_ROOT = HERE.parent
SOURCE = 'rtl/npu/conv/conv_im2col_frontend.sv'
OUTPUTS = ('cfg_ready', 'tile_ready', 'wr_valid', 'wr_slot', 'wr_row', 'wr_col',
           'wr_data', 'wr_mask', 'wr_last', 'tile_done', 'tile_error', 'error', 'busy',
           'arvalid', 'araddr', 'arlen', 'arsize', 'arburst', 'rready')


def compare_bench(source):
    match = re.search(r'conv_im2col_frontend\s+#\(.*?\)\s+dut\s*\(.*?\);', source, re.S)
    if match is None:
        raise ValueError('frontend instance missing')
    original = match.group(0)
    reference = original.replace('conv_im2col_frontend', 'reference_conv_im2col_frontend', 1)
    reference = reference.replace(' dut (', ' u_reference (', 1)
    declarations = ['integer compared_cycles=0;']
    current = {}
    for name in OUTPUTS:
        connection = re.search(r'\.' + name + r'\s*\(([^)]*)\)', original)
        current[name] = connection.group(1) if connection else name
        if name == 'wr_data':
            declarations.append(f'logic signed [15:0] ref_{name}[$size({current[name]})];')
        else:
            declarations.append(f'logic [$bits({current[name]})-1:0] ref_{name};')
        if connection:
            reference = re.sub(r'\.' + name + r'\s*\([^)]*\)', f'.{name}(ref_{name})', reference)
        elif re.search(r'\.' + name + r'(?=\s*[,\)])', reference):
            reference = re.sub(r'\.' + name + r'(?=\s*[,\)])', f'.{name}(ref_{name})', reference)
        elif '.*' in reference:
            reference = reference.replace('.*', f'.{name}(ref_{name}),.*')
        else:
            raise ValueError(f'frontend output connection missing: {name}')
    scalar = [name for name in OUTPUTS if name != 'wr_data']
    lhs = ','.join(current[name] for name in scalar)
    rhs = ','.join('ref_' + name for name in scalar)
    check = f'''
always @(posedge clk) begin
  #1;
  if (rst_n) begin
    compared_cycles++;
    if ({{{lhs}}} !== {{{rhs}}})
      $fatal(1,"frontend public output mismatch cycle=%0d",compared_cycles);
    for (int lane=0; lane<$size({current['wr_data']}); lane++)
      if ({current['wr_data']}[lane] !== ref_wr_data[lane])
        $fatal(1,"frontend write data mismatch cycle=%0d lane=%0d",compared_cycles,lane);
  end
end
final $display("FRONTEND_COMPARE_PASS instance=%m cycles=%0d",compared_cycles);
'''
    replacement = original + '\n' + '\n'.join(declarations) + '\n' + reference + '\n' + check
    return source[:match.start()] + replacement + source[match.end():]


def widen_memory(source):
    source = source.replace('parameter int SIZE=16, LANES=2, CACHE_POLICY=3;',
        'parameter int SIZE=16, LANES=2, CACHE_POLICY=3, BUS_WIDTH=32;\n'
        '  localparam int BUS_BYTES=BUS_WIDTH/8, BUS_SHIFT=$clog2(BUS_BYTES);')
    source = source.replace('logic [31:0] araddr,rdata;', 'logic [31:0] araddr;\n  logic [BUS_WIDTH-1:0] rdata;')
    source = source.replace('conv_im2col_frontend #(.SIZE(SIZE),', 'conv_im2col_frontend #(.BUS_WIDTH(BUS_WIDTH),.SIZE(SIZE),')
    source = source.replace('arsize==0 || arsize==2', "arsize==0 || arsize==3'(BUS_SHIFT)")
    source = source.replace("rdata<=32'ha5b6c7d8;", "rdata<=BUS_WIDTH'(64'ha5b6c7d8_9aaabcdd);")
    source = source.replace('mem_size==4 && mem_addr[1:0]!=0', 'mem_size==BUS_BYTES && (mem_addr&(BUS_BYTES-1))!=0')
    source = source.replace('for (int b=0;b<4;b++)', 'for (int b=0;b<BUS_BYTES;b++)')
    source = source.replace('(mem_addr&3)', '(mem_addr&(BUS_BYTES-1))')
    return source


def run(command, log, timeout=240):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=TEST_ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)


def reviewed_warnings(log):
    warnings = [line for line in log.read_text().splitlines() if line.startswith('%Warning')]
    reviewed = {'UNUSEDSIGNAL', 'UNUSEDPARAM', 'BLKSEQ', 'PROCASSINIT', 'SYNCASYNCNET'}
    unexpected = [line for line in warnings
                  if line.split(':', 1)[0].removeprefix('%Warning-') not in reviewed
                  and not (line.startswith('%Warning-PINMISSING:') and
                           '/rtl/npu/conv/conv_ia_tile_path.sv:' in line and
                           line.endswith("pin: 'wr_last'"))]
    if unexpected:
        raise AssertionError(f'unreviewed RTL diagnostics: {unexpected}')
    return warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default='f5b7573')
    parser.add_argument('--verilator', default=shutil.which('verilator') or 'verilator')
    parser.add_argument('--lanes', nargs='+', type=int, choices=(1, 2, 4), default=[2, 4])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    content = read_rtl_source(f'{args.reference_ref}:{SOURCE}', cwd=ROOT, text=True)
    reference = out / 'reference_frontend.sv'
    reference.write_text(content.replace('module conv_im2col_frontend', 'module reference_conv_im2col_frontend', 1))
    common = runpy.run_path(str(HERE / 'run_rtl.py'))['FILES']
    common = [Path(path) for path in common if not str(path).startswith('tests/')]
    bench = out / 'tb_conv_im2col_frontend.sv'
    bench.write_text(compare_bench(widen_memory((TEST_ROOT / 'tests/tb_conv_im2col_frontend.sv').read_text())))
    control = out / 'tb_conv_control.sv'
    control.write_text(compare_bench((TEST_ROOT / 'tests/tb_conv_control.sv').read_text()))
    simulator = args.verilator
    results = []
    cases = [(size, width, window, lanes) for lanes in args.lanes for size, width, window in
             [(4, 32, 0), (8, 64, 0), (16, 64, 0), (16, 64, 1)]]
    compile_options = ['--output-groups', '0', '--output-split', '12000', '-CFLAGS', '-std=c++20 -O1',
                       '-MAKEFLAGS', 'OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E']
    for size, width, window, lanes in cases:
        case = out / f's{size}_b{width}_l{lanes}_window{window}'
        case.mkdir(exist_ok=True)
        vectors = case / 'vectors.txt'
        run([sys.executable, TEST_ROOT / 'tests/gen_rtl_vectors.py', '--size', size, '--out', vectors], case / 'vectors.log')
        top = 'tb_conv_im2col_frontend'
        sources = [*common, reference, bench]
        hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
        run([simulator, '--binary', '--timing', '--assert', '-DNPU_SIM_ASSERT', '-DCONV_ASSERT', '-Wno-fatal',
             '--top-module', top, f'-GSIZE={size}', f'-GBUS_WIDTH={width}', f'-GLANES={lanes}', '-GCACHE_SETS=16',
             f"-GWINDOWED=1'b{window}", f"-GPREFETCH=1'b{window}", '--Mdir', case / 'obj', '-j', '2',
             *compile_options, *sources], case / 'build.log')
        warnings = reviewed_warnings(case / 'build.log')
        run([case / 'obj' / f'V{top}', f'+VECTORS={vectors}'], case / 'run.log')
        output = (case / 'run.log').read_text()
        if 'RTL_FRONTEND_PASS' not in output or 'FRONTEND_COMPARE_PASS' not in output:
            raise AssertionError(f'frontend success marker missing: {case}')
        for path, digest in hashes.items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
                raise AssertionError(f'source changed during comparison: {path}')
        results.append({'SIZE': size, 'BUS_WIDTH': width, 'LANES': lanes, 'windowed_prefetch': window, 'passed': True,
                        'source_sha256': hashes, 'warnings': warnings, 'summary': [line for line in output.splitlines()
                            if line.startswith(('RTL_FRONTEND_PASS', 'FRONTEND_COMPARE_PASS'))]})
        print(results[-1]['summary'], flush=True)
        for temporary in (case / 'obj').iterdir():
            if temporary.suffix in ('.o', '.gch'):
                temporary.unlink()
    case = out / 'control'
    case.mkdir(exist_ok=True)
    top = 'tb_conv_control'
    run([simulator, '--binary', '--timing', '--assert', '-DNPU_SIM_ASSERT', '-DCONV_ASSERT', '-Wno-fatal',
         '--top-module', top, '--Mdir', case / 'obj', '-j', '2', *compile_options,
         *common, reference, control], case / 'build.log')
    warnings = reviewed_warnings(case / 'build.log')
    run([case / 'obj' / f'V{top}'], case / 'run.log')
    output = (case / 'run.log').read_text()
    if 'RTL_CONTROL_PASS' not in output or 'FRONTEND_COMPARE_PASS' not in output:
        raise AssertionError('control success marker missing')
    results.append({'control': True, 'passed': True, 'warnings': warnings, 'summary': [line for line in output.splitlines()
                    if line.startswith(('RTL_CONTROL_PASS', 'FRONTEND_COMPARE_PASS'))]})
    for temporary in (case / 'obj').iterdir():
        if temporary.suffix in ('.o', '.gch'):
            temporary.unlink()
    report = {'passed': True, 'reference_ref': args.reference_ref, 'configurations': results}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print('FRONTEND_COMPARISON_PASS', out / 'summary.json')


if __name__ == '__main__':
    main()
