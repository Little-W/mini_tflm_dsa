#!/usr/bin/env python3
"""检查 IA 配置范围、容量和预取槽号的综合等价及四态传播。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def between(text, start, stop):
    first = text.index(start)
    return text[first:text.index(stop, first)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.source_root/'rtl/npu/loaders/ia_loader.sv'
    text = path.read_text()
    source_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    capacity = between(text, '    logic compact_offset_valid;', '    wire [CACHE_SLOT_W-1:0] incoming_slot_mask =')
    slots = between(text, '    logic [CACHE_SLOT_W-1:0] context_current_slot,', '    wire prefetch_context_matches =')
    first = text.index('        (cfg_global_reduction == global_reduction_q))) &&')
    first += len('        (cfg_global_reduction == global_reduction_q))) &&')
    last = re.search(r'^\s*(?:\(\*[^\n]*\*\) )?wire \[REG_WIDTH-1:0\] next_q0',
                     text[first:], re.M).start() + first
    slot_selection = text[first:last]
    source = args.out/'configuration.sv'
    source.write_text('''module proof #(parameter int REG_WIDTH=32,CACHE_SLOT_W=6)(
 input logic signed[REG_WIDTH-1:0]cfg_compact_offset,
 input logic[REG_WIDTH-1:0]ia_reuse_num,cfg_cache_slot_base,
 input logic[31:0]incoming_cache_blocks,
 input logic[CACHE_SLOT_W-1:0]incoming_slot_mask,prefetch_group_slot,
 input logic context_mode,cfg_compact,output logic equivalent);
 localparam int COMPACT_S8=1,DATA_WIDTH=16;
 logic[4:0]context_equal;
 assign context_equal={3'b000,context_mode,1'b0};
''' + capacity + slots + '''
 wire selected_slot_match=
''' + slot_selection + '''
 wire reference_compact=cfg_compact&&($signed(cfg_compact_offset)>=-127)&&
   ($signed(cfg_compact_offset)<=128);
 wire reference_capacity=ia_reuse_num<=REG_WIDTH'(reference_compact?
   incoming_cache_blocks<<1:incoming_cache_blocks)/2;
 wire reference_slot=(((CACHE_SLOT_W'(cfg_cache_slot_base)+
   (context_mode?CACHE_SLOT_W'(0):CACHE_SLOT_W'(ia_reuse_num)))&incoming_slot_mask)==prefetch_group_slot);
 assign equivalent=(compact_config_valid===reference_compact)&&
   (prefetch_reuse_fits===reference_capacity)&&(selected_slot_match===reference_slot);
endmodule
''')
    rows = []
    for width in (8, 9, 16, 32, 64):
        for slots_width in (1, 6):
            name = f'w{width}_s{slots_width}'
            script, log = args.out/(name+'.ys'), args.out/(name+'.log')
            script.write_text('read_slang --top proof -DSYNTHESIS=1 -GREG_WIDTH=' + str(width) +
                              ' -GCACHE_SLOT_W=' + str(slots_width) + ' ' + shlex.quote(str(source)) +
                              '\nprep -top proof -flatten\ncheck -assert\n'
                              'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            with log.open('w') as stream:
                run = subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                                      '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                                     timeout=120)
            if run.returncode or 'SUCCESS!' not in log.read_text():
                raise RuntimeError(str(log))
            rows.append({'register_width': width, 'slot_width': slots_width, 'passed': True,
                         'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
    tb = args.out/'four_state.sv'
    tb.write_text('''module tb #(parameter int REG_WIDTH=32,CACHE_SLOT_W=6);
 logic signed[REG_WIDTH-1:0]cfg_compact_offset;
 logic[REG_WIDTH-1:0]ia_reuse_num,cfg_cache_slot_base;
 logic[31:0]incoming_cache_blocks;
 logic[CACHE_SLOT_W-1:0]incoming_slot_mask,prefetch_group_slot;
 logic context_mode,cfg_compact;
 wire equivalent;
 proof #(.REG_WIDTH(REG_WIDTH),.CACHE_SLOT_W(CACHE_SLOT_W))dut(.*);
 localparam int WIDTH=3*REG_WIDTH+32+2*CACHE_SLOT_W+2;
 reg[WIDTH-1:0]pattern;
 integer checks=0;
 initial begin
  for(integer sample=0;sample<20000;sample++)begin
   pattern={$random,$random,$random,$random,$random,$random,$random,$random};
   if(sample%3==0)pattern[sample%WIDTH]=1'bx;
   if(sample%5==0)pattern[(sample*7)%WIDTH]=1'bz;
   {cfg_compact_offset,ia_reuse_num,cfg_cache_slot_base,incoming_cache_blocks,
    incoming_slot_mask,prefetch_group_slot,context_mode,cfg_compact}=pattern;
   #1;
   if(equivalent!==1'b1)$fatal(1,"configuration propagation");
   checks++;
  end
  $display("IA_CONFIGURATION_FOUR_STATE_PASS checks=%0d",checks);$finish;
 end
endmodule
''')
    simulations = []
    for width in (8, 9, 16, 32, 64):
        binary = args.out/(f'four_state{width}.vvp')
        subprocess.run(['/home/agent/.local/bin/iverilog', '-g2012', '-s', 'tb',
                        '-Ptb.REG_WIDTH='+str(width), '-o', str(binary), str(source), str(tb)],
                       capture_output=True, check=True)
        run = subprocess.run(['/home/agent/.local/bin/vvp', str(binary)],
                             capture_output=True, text=True, check=True, timeout=30)
        log = args.out/(f'four_state{width}.log')
        log.write_text(run.stdout + run.stderr)
        if 'checks=20000' not in run.stdout:
            raise RuntimeError('Four-state coverage')
        simulations.append({'register_width': width, 'slot_width': 6, 'passed': True,
                            'samples': 20000, 'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
    if source_sha != hashlib.sha256(path.read_bytes()).hexdigest():
        raise RuntimeError('Source changed during verification')
    report = {'passed': True, 'source_sha256': source_sha, 'binary_input_constraints': [],
              'synthesis_define_enabled_in_formal': True, 'binary_proofs': rows,
              'four_state_simulations': simulations, 'four_state_samples': 100000}
    (args.out/'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print('IA_CONFIGURATION_PASS', len(rows), len(simulations))


if __name__ == '__main__':
    main()
