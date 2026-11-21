#!/usr/bin/env python3
"""验证物理槽号完整模加、掩码及四态传播。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    source = args.source_root / 'rtl/npu/loaders/ia_loader.sv'
    text = source.read_text()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    sum_expression = re.search(r'assign request_slot_sum\s*=\s*([^;]+);', text).group(1)
    slot_expression = re.search(r'request_descriptor\.slot\s*=\s*([^;]+);', text).group(1)
    sv = args.out / 'request_slot.sv'
    sv.write_text('''module proof #(parameter int CACHE_SLOT_W=6)(
 input logic [CACHE_SLOT_W-1:0] request_slot,cache_slot_base_q,cache_slot_mask,
 output logic equivalent);
 (* use_dsp="yes" *) logic [CACHE_SLOT_W-1:0] request_slot_sum;
 logic [CACHE_SLOT_W-1:0] slot_current,slot_reference;
''' + f'assign request_slot_sum={sum_expression};\n' +
                  f'assign slot_current={slot_expression};\n' + '''
 assign slot_reference=(request_slot+cache_slot_base_q)&cache_slot_mask;
 assign equivalent=slot_current===slot_reference;
endmodule
''')
    formal = []
    for width in range(1, 13):
        script, log = args.out / f'w{width}.ys', args.out / f'w{width}.log'
        script.write_text('read_slang --top proof -DSYNTHESIS=1 -DXILINX_FPGA=1 ' +
                          f'-GCACHE_SLOT_W={width} ' + shlex.quote(str(sv)) +
                          '\nprep -top proof -flatten\ncheck -assert\n' +
                          'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            run = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                  '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                                 timeout=120)
        if run.returncode or 'SUCCESS!' not in log.read_text():
            raise RuntimeError(str(log))
        formal.append({'slot_width': width, 'passed': True,
                       'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
    tb = args.out / 'four_state.sv'
    tb.write_text('''module tb;
 parameter int WIDTH=6;
 logic [WIDTH-1:0] request_slot,cache_slot_base_q,cache_slot_mask;
 logic [3*WIDTH-1:0] pattern;
 wire equivalent;
 proof #(WIDTH) dut(.*);
 integer checks;
 initial begin
  checks=WIDTH<=3 ? (1<<(6*WIDTH)) : 20000;
  for(integer sample=0;sample<checks;sample++)begin
   for(integer bit_index=0;bit_index<3*WIDTH;bit_index++)begin
    if(WIDTH<=3)case((sample>>(2*bit_index))&3)
     0:pattern[bit_index]=1'b0;
     1:pattern[bit_index]=1'b1;
     2:pattern[bit_index]=1'bx;
     3:pattern[bit_index]=1'bz;
    endcase
    else pattern[bit_index]=$urandom_range(0,1);
   end
   if(WIDTH>3)begin
    if(sample%3==0)pattern[sample%(3*WIDTH)]=1'bx;
    if(sample%5==0)pattern[(sample*7)%(3*WIDTH)]=1'bz;
   end
   {request_slot,cache_slot_base_q,cache_slot_mask}=pattern;
   #1;if(equivalent!==1'b1)$fatal(1,"request slot four-state sample %0d",sample);
  end
  $display("REQUEST_SLOT_FOUR_STATE_PASS checks=%0d",checks);$finish;
 end
endmodule
''')

    def event(width):
        binary, log = args.out / f'w{width}.vvp', args.out / f'w{width}.event.log'
        subprocess.run(['/home/agent/.local/bin/iverilog', '-g2012', '-s', 'tb',
                        f'-Ptb.WIDTH={width}', '-o', str(binary), str(sv), str(tb)],
                       check=True, capture_output=True)
        run = subprocess.run(['/home/agent/.local/bin/vvp', str(binary)], check=True,
                             capture_output=True, text=True, timeout=120)
        log.write_text(run.stdout + run.stderr)
        checks = 1 << (6 * width) if width <= 3 else 20000
        if f'checks={checks}' not in run.stdout:
            raise RuntimeError(str(log))
        return {'slot_width': width, 'checks': checks, 'passed': True,
                'exhaustive_four_state': width <= 3,
                'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}

    with ThreadPoolExecutor(max_workers=3) as workers:
        events = list(workers.map(event, range(1, 13)))
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    report = {'passed': True, 'source_sha256': digest, 'binary_input_constraints': [],
              'synthesis_configuration': ['SYNTHESIS=1', 'XILINX_FPGA=1'],
              'formal': formal, 'event_simulations': events,
              'four_state_checks': sum(event['checks'] for event in events)}
    (args.out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'formal_profiles': len(formal),
                      'four_state_checks': report['four_state_checks']}))


if __name__ == '__main__':
    main()
