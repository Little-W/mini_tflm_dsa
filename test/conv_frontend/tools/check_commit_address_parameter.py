#!/usr/bin/env python3
"""验证两种描述符参数下的提交地址及定宽加法。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def run(command: list[str], log: Path) -> None:
    with log.open('w') as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=120)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-ref', default='2247144937c2fd04039b9b005151f371d6b51f8f')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = root / 'rtl/npu/conv/conv_im2col_descriptor.sv'
    arithmetic = root / 'rtl/common/parallel_prefix_add.sv'
    tracked = (source, arithmetic, Path(__file__).resolve())
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked}
    text = source.read_text()
    start = text.index('  for (genvar address_port = 0; address_port < 2; address_port++) begin : g_commit_address')
    stop = text.index('  always_comb begin\n    preparing_tile =', start)
    reference = subprocess.check_output(['git', 'show', args.reference_ref +
        ':rtl/npu/conv/conv_im2col_descriptor.sv'], cwd=root, text=True)
    reference_start = reference.index('  for (genvar address_port = 0; address_port < 2; address_port++) begin : g_commit_address')
    reference_stop = reference.index('  always_comb begin\n    preparing_tile =', reference_start)
    model = out / 'model.sv'
    model.write_text('''module proof #(parameter bit p_register_descriptor=1'b1)(
 input logic [31:0] address,group_address,committing_address_delta,
 input logic committing_address_carry,
 output logic equivalent);
 typedef struct packed {logic [31:0]address,group_address;} prepared_t;
 prepared_t prepared_tile_q;
 assign prepared_tile_q={address,group_address};
 logic [1:0][31:0] committing_address;
''' + text[start:stop] + '''
 wire [31:0] expected_address=address+committing_address_delta+32'(committing_address_carry);
 wire [31:0] expected_group=group_address+committing_address_delta+32'(committing_address_carry);
`ifdef SYNTHESIS
 assign equivalent=committing_address ===
   (p_register_descriptor?{expected_group,expected_address}:64'd0);
`else
 wire [1:0][31:0] reference_address;
 reference_commit u_reference(.*,.committing_address(reference_address));
 assign equivalent=committing_address === (p_register_descriptor?reference_address:64'd0);
`endif
endmodule
`ifndef SYNTHESIS
module reference_commit(
 input logic [31:0] address,group_address,committing_address_delta,
 input logic committing_address_carry,
 output logic [1:0][31:0] committing_address);
 typedef struct packed {logic [31:0]address,group_address;} prepared_t;
 prepared_t prepared_tile_q;
 assign prepared_tile_q={address,group_address};
''' + reference[reference_start:reference_stop] + '\nendmodule\n`endif\n')
    results = []
    for parameter in (0, 1):
        name = 'registered' + str(parameter)
        script = out / (name + '.ys')
        log = out / (name + '.formal.log')
        script.write_text(f'read_slang -DSYNTHESIS --top proof -Gp_register_descriptor={parameter} ' +
            shlex.join(map(str, (arithmetic, model))) + '\n' +
            'setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n' +
            'prep -top proof -flatten\ncheck -assert\n' +
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)], log)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise RuntimeError('Incomplete address proof: ' + str(log))
        bench = out / (name + '.tb.sv')
        bench.write_text(f'''module tb;
 logic [31:0]address,group_address,committing_address_delta;
 logic committing_address_carry,equivalent;
 logic [96:0]values;
 proof #(.p_register_descriptor(1'b{parameter})) dut(.*);
 initial begin
   for (integer sample=0;sample<1024;sample++) begin
     values={{$urandom,$urandom,$urandom,1'($urandom)}};
     if(sample<194)values[sample/2]=(sample%2)?1'bx:1'bz;
     {{address,group_address,committing_address_delta,committing_address_carry}}=values;
     #1;
     if(equivalent!==1'b1)$fatal(1,"Commit address mismatch parameter={parameter} sample=%0d",sample);
   end
   $display("COMMIT_ADDRESS_PARAMETER_PASS parameter={parameter} samples=1024");
   $finish;
 end
endmodule
''')
        binary = out / (name + '.vvp')
        run([shutil.which('iverilog') or 'iverilog', '-g2012', '-s', 'tb', '-o', str(binary),
             str(arithmetic), str(model), str(bench)], out / (name + '.build.log'))
        run([shutil.which('vvp') or 'vvp', str(binary)], out / (name + '.four_state.log'))
        results.append({'register_descriptor': parameter, 'formal_passed': True,
                        'four_state_samples': 1024})
        print('COMMIT_ADDRESS_PARAMETER_PASS', parameter, flush=True)
    if hashes != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked}:
        raise RuntimeError('Address sources changed during verification')
    (out / 'summary.json').write_text(json.dumps({'passed': True, 'runs': results,
        'source_sha256': hashes, 'reference_ref': args.reference_ref,
        'reference_sha256': hashlib.sha256(reference.encode()).hexdigest()}, indent=2) + '\n')


if __name__ == '__main__':
    main()
