#!/usr/bin/env python3
"""验证流式坐标、像素和地址组的写入条件与完整字段值。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file, resolve_reference
SOURCE = Path('rtl/npu/conv/conv_im2col_frontend.sv')
FIELDS = {'ix': 35, 'iy': 35, 'pixel_index': 32, 'pad_q': 1,
          'tap_group_base': 32, 'row_group_base': 32}
CONTROLS = ['chunk_reaches_end', 'row_last_q', 'row_base_valid', 'geometry_tile',
            'row_coordinate_valid', 'past_active_q', 'active_after_chunk',
            'group_end_o_equal', 'coordinate_address_valid']
INPUTS = {**{name: 1 for name in CONTROLS}, 'row_wrap': 1, 'tap_wrap': 1,
          'coordinate_payload': 70, 'pixel_payload': 32, 'tap_group_payload': 32,
          'row_group_payload': 32, 'next_row_padding': 1, 'next_tap_padding': 1,
          'previous_value': sum(FIELDS.values())}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def section(source: str) -> str:
    first = source.index('        stream_operation_accept: begin\n')
    last = source.index('        (!tile_commit && stream_response_error', first)
    text = source[first:last]
    assert text.startswith('        stream_operation_accept: begin\n')
    assert text.endswith('        end\n')
    return text[len('        stream_operation_accept: begin\n'):-len('        end\n')]


def filtered(source: str, prefix: str, enables: bool) -> str:
    def replace(match):
        name = match.group(1)
        if name not in FIELDS:
            return ';'
        return f'{prefix}_{name} = ' + ("1'b1;" if enables else match.group(2) + ';')
    return re.sub(r'\b([A-Za-z_][A-Za-z_0-9]*)\s*<=\s*([^;]+);', replace, source)


def module_text(current: str, reference: str) -> str:
    found = re.search(r'\bmodule conv_im2col_stream_position\b.*?endmodule', current, re.S)
    if found is None:
        raise ValueError('conv_im2col_stream_position')
    connection = re.search(r'  logic stream_row_coordinate_update, stream_row_data_update;.*?\n  \);', current, re.S)
    if connection is None:
        raise ValueError('stream position connection')
    declarations = []
    for name, width in INPUTS.items():
        shape = '[1:0][34:0]' if name == 'coordinate_payload' else f'[{width-1}:0]' if width > 1 else ''
        declarations.append(f'input logic {shape} {name}')
    width = sum(FIELDS.values())
    def remove_fields(text):
        for name in FIELDS:
            text = re.sub(r'\b'+name+r'\s*<=\s*[^;]+;', '', text)
        return re.sub(r'\s+', '', text)
    original_body = section(reference)
    changed_body = section(current)
    changed_body = changed_body[changed_body.index('          if (chunk_reaches_end) begin'): ]
    assert remove_fields(changed_body) == remove_fields(original_body), 'Other stream state assignments changed'
    model = '(* keep_hierarchy = "yes" *)\n' + found.group() + '\nmodule proof(\n' + ',\n'.join(declarations) + f''',
 output logic [{width-1}:0] actual_value, expected_value,
 output logic [5:0] actual_write, expected_write,
 output logic value_equal, write_equal
);
''' + connection.group() + '\n'
    for prefix, source, enables in [('actual', current, False), ('expected', reference, False),
                                    ('actual_en', current, True), ('expected_en', reference, True)]:
        fields = ','.join(prefix + '_' + name for name in FIELDS)
        for name, bits in FIELDS.items():
            shape = '' if enables or bits == 1 else f'[{bits-1}:0]'
            model += f'logic {shape} {prefix}_{name};\n'
        model += 'always_comb begin\n'
        model += '{' + fields + "}='0;\n" if enables else '{' + fields + '}=previous_value;\n'
        model += filtered(section(source), prefix, enables) + '\nend\n'
    for output, prefix in [('actual_value', 'actual'), ('expected_value', 'expected'),
                           ('actual_write', 'actual_en'), ('expected_write', 'expected_en')]:
        model += 'assign ' + output + '={' + ','.join(prefix+'_'+name for name in FIELDS) + '};\n'
    model += '''assign value_equal=actual_value===expected_value;
assign write_equal=actual_write===expected_write;
endmodule
'''
    return model


def bench() -> tuple[str, int]:
    bits = sum(INPUTS.values())
    checks = 4**len(CONTROLS) + 2*bits
    padded = ((bits+31)//32)*32
    declarations = []
    for name, width in INPUTS.items():
        shape = '[1:0][34:0]' if name == 'coordinate_payload' else f'[{width-1}:0]' if width > 1 else ''
        declarations.append(f'logic {shape} {name};')
    names = ','.join(INPUTS)
    controls = ','.join(CONTROLS)
    width = sum(FIELDS.values())
    return '\n'.join(declarations).join(['module tb;\n', f'''
logic [{width-1}:0]actual_value,expected_value;
logic [5:0]actual_write,expected_write;
logic value_equal,write_equal;
logic [{bits-1}:0]pattern,seen_x='0,seen_z='0;
logic [8:0]control_value;
integer value, digit;
proof dut(.*);
initial begin
 for(integer sample=0;sample<{checks};sample++)begin
  for(integer word_index=0;word_index<{padded//32};word_index++)pattern[32*word_index+:32]=$urandom;
  if(sample<{4**len(CONTROLS)})begin
   value=sample;
   for(integer position=0;position<9;position++)begin
    digit=value%4;value=value/4;
    case(digit)
     0:control_value[position]=1'b0;
     1:control_value[position]=1'b1;
     2:control_value[position]=1'bx;
     3:control_value[position]=1'bz;
    endcase
   end
  end else begin
   pattern[(sample-{4**len(CONTROLS)})/2]=((sample-{4**len(CONTROLS)})%2==0)?1'bx:1'bz;
  end
  {{{names}}}=pattern;
  if(sample<{4**len(CONTROLS)}) {{{controls}}}=control_value;
  pattern={{{names}}};
  for(integer bit_index=0;bit_index<{bits};bit_index++)begin
   if(pattern[bit_index]===1'bx)seen_x[bit_index]=1'b1;
   if(pattern[bit_index]===1'bz)seen_z[bit_index]=1'b1;
  end
  #1;
  if(value_equal!==1'b1||write_equal!==1'b1)
   $fatal(1,"Stream position mismatch sample=%0d actual=%h expected=%h write=%b/%b",sample,actual_value,expected_value,actual_write,expected_write);
 end
 if(!(&seen_x)||!(&seen_z))$fatal(1,"Input X/Z coverage incomplete");
 $display("STREAM_POSITION_PASS checks={checks} controls={4**len(CONTROLS)} input_bits={bits}");$finish;
end
endmodule
''']), checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--reference-ref', default='f1910d02')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current_data = (root/SOURCE).read_bytes()
    if args.reference_root:
        reference_data = (args.reference_root.resolve()/SOURCE).read_bytes()
        reference_commit = None
    else:
        reference_commit = resolve_reference(root, args.reference_ref)
        reference_data = read_reference_file(root, reference_commit, SOURCE)
    generated = out/'model.sv'
    generated.write_text(module_text(current_data.decode(), reference_data.decode()))
    (out/'reference.sv').write_bytes(reference_data)
    script = out/'proof.ys'
    script.write_text('read_slang --top proof '+shlex.quote(str(generated))+'\nprep -top proof -flatten\ncheck -assert\n'+
                      'sat -verify -prove value_equal 1 -show-inputs -show-outputs\n'+
                      'sat -verify -prove write_equal 1 -show-inputs -show-outputs\n')
    log = out/'proof.log'
    with log.open('w') as handle:
        subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                       stdout=handle, stderr=subprocess.STDOUT, check=True, timeout=300)
    assert log.read_text().count('SAT proof finished - no model found: SUCCESS!') == 2
    tb, checks = bench()
    (out/'tb.sv').write_text(tb)
    binary = out/'simulation.vvp'
    with (out/'build.log').open('w') as handle:
        subprocess.run([shutil.which('iverilog') or 'iverilog', '-g2012', '-s', 'tb', '-o', str(binary),
                        str(generated), str(out/'tb.sv')], stdout=handle, stderr=subprocess.STDOUT, check=True)
    started = time.monotonic()
    run_log = out/'four_state.log'
    with run_log.open('w') as handle:
        subprocess.run([shutil.which('vvp') or 'vvp', str(binary)], stdout=handle, stderr=subprocess.STDOUT,
                       check=True, timeout=300)
    assert f'PASS checks={checks}' in run_log.read_text()
    binary.unlink()
    assert sha(current_data) == sha((root/SOURCE).read_bytes()), 'Production source changed'
    report = {'passed': True, 'source_sha256': {str(SOURCE): sha(current_data)},
              'reference_commit': reference_commit, 'reference_sha256': {str(SOURCE): sha(reference_data)},
              'formal_properties': ['all_six_field_next_values', 'all_six_field_write_enables'],
              'formal_cases': 2, 'other_stream_assignments_identical': True, 'four_state_checks': checks, 'control_combinations': 4**len(CONTROLS),
              'input_bits_with_x_z': sum(INPUTS.values()), 'fields': FIELDS,
              'simulation_seconds': time.monotonic()-started,
              'logs_sha256': {p.name: sha(p.read_bytes()) for p in (log, run_log)}}
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print('STREAM_POSITION_WRITE_PASS', flush=True)


if __name__ == '__main__':
    main()
