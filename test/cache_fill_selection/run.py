#!/usr/bin/env python3
"""验证缓存填充选择条件的组合等价性与四态行为。"""
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

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/dma/cache/conv_read_cache.sv")


def selection_blocks(source: str) -> tuple[str, str]:
    start = source.index('  (* keep = "true" *) logic select_common_ready,') \
        if 'logic select_common_ready,' in source else \
        source.index('  (* keep = "true" *) logic select_fill_capacity_ready,')
    end = source.index('  assign select_prefetch_ready =', start)
    qualifiers = source[start:end]
    start = source.index('    select_launch = ', end)
    end = source.index('    select_way_next=', start)
    launch = source[start:end]
    return qualifiers, launch


PORTS = """
  input logic select_stage_valid, select_decision_valid,
  input logic req_fire, hint_pending_q, hint_effective_valid,
  input logic fill_success, metadata_fill, lookup_hit,
  input logic select_prefetch, select_prefetch_ready, select_demand_ready,
  input logic select_victim_conflict,
  input logic [1:0] fill_state,
  input logic [SI-1:0] lookup_set, select_set, hint_set, fill_set,
"""


def helper(source: str, name: str) -> str:
    qualifiers, launch = selection_blocks(source)
    qualifiers = qualifiers.replace(', select_prefetch_ready, select_demand_ready;', ';')
    qualifiers = qualifiers.replace('  (* keep = "true" *) logic select_victim_conflict;\n', '')
    suppress_start = source.index('    if (select_launch && select_victim_conflict) begin')
    suppress_end = source.index('    ram_ren=', suppress_start)
    suppress = source[suppress_start:suppress_end]
    metadata = re.search(r'  assign select_metadata_busy = .*?;', source, re.S).group(0)
    return f"""module {name} #(parameter int SI=7) (
{PORTS}
  output logic select_launch
);
  localparam logic [1:0] F_IDLE=2'd0;
  logic select_metadata_busy;
{metadata}
{qualifiers}
  always_comb begin
{launch}
{suppress}
  end
endmodule
"""


INSTANCES = """
  logic reference_launch, current_launch;
  reference_selection #(.SI(SI)) u_reference (.select_launch(reference_launch), .*);
  current_selection #(.SI(SI)) u_current (.select_launch(current_launch), .*);
"""


BENCH = """module tb;
  localparam int SI=7;
  logic select_stage_valid, select_decision_valid, req_fire;
  logic hint_pending_q, hint_effective_valid, fill_success, metadata_fill, lookup_hit;
  logic select_prefetch, select_prefetch_ready, select_demand_ready, select_victim_conflict;
  logic [1:0] fill_state;
  logic [SI-1:0] lookup_set, select_set, hint_set, fill_set;
  logic [8:0] controls;
  logic [41:0] arbitrary;
  integer checks=0;
""" + INSTANCES + """
  function automatic logic digit(input int value);
    case (value & 3)
      0: return 1'b0;
      1: return 1'b1;
      2: return 1'bx;
      3: return 1'bz;
    endcase
  endfunction
  task automatic check;
    #1;
    if (reference_launch !== current_launch)
      $fatal(1, "selection differs check=%0d ref=%b current=%b", checks,
             reference_launch, current_launch);
    checks++;
  endtask
  initial begin
    fill_state=0; fill_success=0; metadata_fill=0;
    lookup_set=0; select_set=0; hint_set=0; fill_set=0;
    select_victim_conflict=0;
    for (int address_case=0; address_case<2; address_case++) begin
      lookup_set=7'(address_case); hint_set=7'(address_case);
      for (int vector=0; vector<262144; vector++) begin
        for (int bit_index=0; bit_index<9; bit_index++)
          controls[bit_index]=digit(vector>>(2*bit_index));
        {select_stage_valid,select_decision_valid,req_fire,hint_pending_q,
         hint_effective_valid,lookup_hit,select_prefetch,
         select_prefetch_ready,select_demand_ready}=controls;
        select_victim_conflict=digit(vector>>10);
        check();
      end
    end
    for (int vector=0; vector<65536; vector++) begin
      for (int bit_index=0; bit_index<42; bit_index++)
        arbitrary[bit_index]=digit($urandom);
      {select_stage_valid,select_decision_valid,req_fire,hint_pending_q,
       hint_effective_valid,fill_success,metadata_fill,lookup_hit,
       select_prefetch,select_prefetch_ready,select_demand_ready,
       select_victim_conflict,fill_state,lookup_set,select_set,hint_set,fill_set}=arbitrary;
      check();
    end
    $display("FOUR_STATE_PASS checks=%0d", checks);
    $finish;
  end
endmodule
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='ef0dc75')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--iverilog', default=shutil.which('iverilog') or 'iverilog')
    parser.add_argument('--vvp', default=shutil.which('vvp') or 'vvp')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(
        ['git', 'show', f'{args.reference}:{SOURCE}'], cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    normalized = current
    for current_block, reference_block in zip(selection_blocks(current), selection_blocks(reference)):
        normalized = normalized.replace(current_block, reference_block, 1)
    if normalized != reference:
        raise RuntimeError('缓存填充选择以外存在未覆盖的源码变化')
    helpers = helper(reference, 'reference_selection') + helper(current, 'current_selection')
    proof = out / 'proof.sv'
    proof.write_text(helpers + f"""module proof #(parameter int SI=7) (
{PORTS}
  output logic equivalent
);
{INSTANCES}
  assign equivalent=reference_launch==current_launch;
endmodule
""")
    proofs = []
    for width in (1, 3, 7, 8):
        script = out / f'formal_{width}.ys'
        log = out / f'formal_{width}.log'
        script.write_text(f'read_slang -D SYNTHESIS=1 --top proof -GSI={width} ' +
            shlex.quote(str(proof)) + '\nprep -top proof -flatten\n' +
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=120)
        if 'SUCCESS!' not in log.read_text():
            raise RuntimeError(f'组合证明未完成: {log}')
        proofs.append({'set_width': width, 'passed': True, 'inputs_constrained': False})
    bench = out / 'tb.sv'
    bench.write_text(helpers + BENCH)
    binary = out / 'simulation'
    with (out / 'compile.log').open('w') as stream:
        subprocess.run([args.iverilog, '-g2012', '-s', 'tb', '-o', str(binary), str(bench)],
                       stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
    simulation = subprocess.run([args.vvp, str(binary)], capture_output=True, text=True,
                                check=True, timeout=120)
    (out / 'simulation.log').write_text(simulation.stdout + simulation.stderr)
    checks = int(re.search(r'FOUR_STATE_PASS checks=(\d+)', simulation.stdout).group(1))
    sha = lambda data: hashlib.sha256(data).hexdigest()
    result = {'passed': True, 'reference': args.reference,
              'source_sha256': sha(current.encode()), 'reference_sha256': sha(reference.encode()),
              'only_fill_selection_changed': True, 'actual_rtl_expressions': True,
              'formal': proofs, 'four_state_checks': checks,
              'proof_sha256': sha(proof.read_bytes()), 'testbench_sha256': sha(bench.read_bytes())}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
