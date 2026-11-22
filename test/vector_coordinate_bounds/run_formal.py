#!/usr/bin/env python3
"""比较向量坐标范围判断的全部输入编码。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/conv/vector_engine.sv'


def span(source):
    if '  logic input_x_fits_interval' in source:
        first = source.index('  logic input_x_fits_interval')
        return first, source.index('  always_ff @(posedge clk) begin', first)
    marker = '  logic [16:0] next_column_low' if '  logic [16:0] next_column_low' in source else '  wire next_column_valid='
    return source.index(marker), source.index('  logic soft_ready', source.index(marker))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='ef0dc75')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = read_rtl_source(args.reference_rev + ':' + SOURCE, cwd=ROOT, text=True)
    candidate = (ROOT / SOURCE).read_text()
    packages = [ROOT/'rtl/npu/conv/conv_im2col_pkg.sv', ROOT/'rtl/npu/conv/vector_engine_pkg.sv',
                ROOT/'rtl/common/parallel_prefix_add.sv']
    dependency_hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in packages}
    header = '''module coordinate_bounds (
      input logic signed [33:0] input_x, input_y, input_origin_x, input_origin_y,
      input vector_engine_pkg::vector_engine_cfg_t c,
      output logic o_column_valid, o_row_valid, o_current_valid,
      output logic o_origin_column_valid, o_origin_row_valid
    );
      wire signed [33:0] next_column_x=input_x+$signed(34'(c.image.dilation_w));
      wire signed [33:0] next_row_y=input_y+$signed(34'(c.image.dilation_h));
    '''
    commands = []
    for label, source in [('reference', reference), ('candidate', candidate)]:
        first, last = span(source)
        path = out/(label+'.sv')
        interval_context = ''
        origin_outputs = '''
          logic signed [33:0] next_origin_x, next_origin_y;
          assign next_origin_x = input_origin_x + $signed(34'(c.image.stride_w));
          assign next_origin_y = input_origin_y + $signed(34'(c.image.stride_h));
          assign o_origin_column_valid = next_origin_x >= 0 &&
              next_origin_x < $signed(34'(c.image.input_w)) && input_origin_y >= 0 &&
              input_origin_y < $signed(34'(c.image.input_h));
          assign o_origin_row_valid = c.image.pad_left == 0 && c.image.input_w != 0 &&
              next_origin_y >= 0 && next_origin_y < $signed(34'(c.image.input_h));
        '''
        if '  logic input_x_fits_interval' in source:
            interval_context = '''
              logic origin_column_in_bounds, origin_row_in_bounds;
              logic next_origin_column_valid, next_origin_row_valid;
              logic signed [16:0] dilation_x_min, dilation_x_max, dilation_y_min, dilation_y_max;
              logic signed [16:0] stride_x_min, stride_x_max, stride_y_min, stride_y_max;
            '''
            # 配置完成后区间寄存器保持这些值；形式比较覆盖全部坐标、尺寸和增量。
            captures = re.search(r'if \(state == CHECK_WAIT && config_check_done\) begin(.*?)\n    end', source, re.S)[1]
            for line in captures.splitlines():
                if re.match(r'\s*(dilation|stride)_[xy]_(min|max)\s*<=', line):
                    interval_context += 'assign ' + line.strip().replace('<=', '=') + '\n'
            origin_outputs = '''
              assign o_origin_column_valid = next_origin_column_valid;
              assign o_origin_row_valid = next_origin_row_valid;
            '''
        if 'vector_coordinate_bound u_input_column_bound' in source:
            current_logic = 'logic input_column_in_bounds, input_row_in_bounds;\n'
            for instance in ('u_input_column_bound', 'u_input_row_bound',
                             'u_origin_column_bound', 'u_origin_row_bound'):
                current_logic += re.search(r'  vector_coordinate_bound ' + instance +
                                           r' \(.*?\);', source, re.S)[0] + '\n'
            current_logic += 'assign in_bounds = input_column_in_bounds && input_row_in_bounds;\n'
            helper = ''
            for module in ('vector_coordinate_bound', 'vector_interval_bound'):
                block = re.search(r'^module ' + module + r'\b.*?^endmodule', source, re.M | re.S)
                helper += (block[0] if block else (ROOT/'rtl/npu/conv'/f'{module}.sv').read_text()) + '\n'
        else:
            current_logic = re.search(r'  assign in_bounds\s*=.*?;', source, re.S)[0]
            helper = ''
        path.write_text(header+interval_context+'''
          logic in_bounds;
        '''+current_logic+source[first:last]+'''
          assign o_column_valid = next_column_valid;
          assign o_row_valid = next_row_valid;
          assign o_current_valid = in_bounds;
        '''+origin_outputs+'''
        endmodule
        '''+helper+'\n')
        commands += ['read_slang --top coordinate_bounds ' + ' '.join(shlex.quote(str(p)) for p in packages+[path]),
                     'prep -top coordinate_bounds -flatten', 'opt -full',
                     'rename coordinate_bounds '+label, 'design -stash '+label]
    commands += ['design -copy-from reference -as reference reference',
                 'design -copy-from candidate -as candidate candidate',
                 'equiv_make reference candidate comparison', 'hierarchy -top comparison',
                 'equiv_simple', 'equiv_status -assert']
    script = out/'run.ys'
    script.write_text('\n'.join(commands)+'\n')
    log = out/'formal.log'
    with log.open('w') as stream:
        result = subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],
                                stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT)
    report = {'reference_rev':args.reference_rev,
              'source_sha256':hashlib.sha256(candidate.encode()).hexdigest(),
              'dependency_sha256':dependency_hashes,
              'reference_sha256':hashlib.sha256(reference.encode()).hexdigest(),
              'proof_scope':'Current coordinates, next kernel coordinates and next output origins; captured intervals equal the checked configuration values',
              'inputs_constrained':False,
              'coordinate_width':34,'dimension_width':16,
              'formal_log_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),
              'passed':result.returncode==0 and 'Equivalence successfully proven' in log.read_text()}
    if dependency_hashes != {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in packages} or (ROOT/SOURCE).read_text() != candidate:
        raise RuntimeError('验证期间坐标源码或公共依赖发生变化')
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)
    if not report['passed']:
        raise RuntimeError(log.read_text()[-8000:])


if __name__ == '__main__':
    main()
