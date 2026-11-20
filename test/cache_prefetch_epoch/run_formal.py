#!/usr/bin/env python3
"""证明有效预取项的保存代次比较始终等于存储内容的直接比较。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/cache/conv_read_cache.sv')
DECLARATION = '  logic pf_offer_matches_work, pf_offer_matches_demand;\n'
GLOBAL = """  // 代次比较与需求接收及预取写入同时保存，选择活动项时直接读取比较结果。
  assign pf_offer_matches_work = pf_offer_epoch == work_request.epoch;
  assign pf_offer_matches_demand = pf_offer_epoch == demand_epoch;
"""
UPDATE = """        // 同周期接收新需求和新预取时，比较两份新代次；其余有效项跟随需求代次更新。
        if (pf_push && pf_push_slot == PF_AW'(slot))
          pf_epoch_matches[slot] <= req_fire ? pf_offer_matches_work : pf_offer_matches_demand;
        else if (req_fire)
          pf_epoch_matches[slot] <= prefetch_keys_o_rd_data[slot][31:0] == work_request.epoch;
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='2bd1d2b3')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(args.reference + ':' + str(SOURCE), cwd=ROOT, text=True)
    original_compare = '    assign pf_epoch_matches[slot] = prefetch_keys_o_rd_data[slot][31:0] == demand_epoch;\n'
    normalized = current.replace(DECLARATION, '', 1).replace(GLOBAL, '', 1).replace(UPDATE, '', 1)
    normalized = normalized.replace("        pf_epoch_matches[slot] <= 1'b0;\n", '')
    loop = '  for (genvar slot=0; slot<PF_DEPTH; slot++) begin : g_prefetch_valid\n'
    normalized = normalized.replace(loop, loop + original_compare, 1)
    assert normalized == reference
    for text in [DECLARATION, GLOBAL, UPDATE]:
        assert current.count(text) == 1
    assert "demand_epoch<=work_request.epoch;" in current
    assert "assign prefetch_keys_i_wr_en = pf_push;" in current
    assert "assign prefetch_keys_i_wr_data = {pf_offer_addr, pf_offer_epoch};" in current
    assert ".p_write_unit(64), .p_read_ports(PF_DEPTH), .p_sync_read(1'b0)" in current
    proof = args.out / 'proof.sv'
    proof.write_text("""module epoch_proof #(parameter int PROOF_SLOT=0) (
    input logic clk, rst_n, cfg_valid, cfg_ready, req_fire, pf_push, pf_pop,
    input logic [2:0] pf_push_slot, pf_pop_slot,
    input logic [31:0] work_epoch, pf_offer_epoch,
    output logic equivalent
);
  localparam int PF_DEPTH=8, PF_AW=3;
  typedef struct packed {logic [31:0] epoch;} request_t;
  request_t work_request;
  logic [31:0] demand_epoch;
  logic [7:0][31:0] stored_epochs;
  logic [7:0][63:0] prefetch_keys_o_rd_data;
  logic [7:0] pf_physical_valid_q, pf_epoch_matches, direct_matches;
""" + DECLARATION + GLOBAL + """
  assign work_request.epoch = work_epoch;
  initial begin
    demand_epoch = 32'b0;
    pf_physical_valid_q = 8'b0;
    pf_epoch_matches = 8'b0;
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) demand_epoch <= 32'b0;
    else if (!(cfg_valid && cfg_ready) && req_fire) demand_epoch <= work_request.epoch;
  end
  for (genvar slot=0; slot<PF_DEPTH; slot++) begin : g_slot
    assign prefetch_keys_o_rd_data[slot] = {32'b0, stored_epochs[slot]};
    assign direct_matches[slot] = prefetch_keys_o_rd_data[slot][31:0] == demand_epoch;
    always_ff @(posedge clk) begin
      if (pf_push && pf_push_slot == PF_AW'(slot)) stored_epochs[slot] <= pf_offer_epoch;
    end
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
        pf_physical_valid_q[slot] <= 1'b0;
        pf_epoch_matches[slot] <= 1'b0;
      end else if (cfg_valid && cfg_ready) begin
        pf_physical_valid_q[slot] <= 1'b0;
        pf_epoch_matches[slot] <= 1'b0;
      end else begin
        if (pf_pop && pf_pop_slot == PF_AW'(slot)) pf_physical_valid_q[slot] <= 1'b0;
        if (pf_push && pf_push_slot == PF_AW'(slot)) pf_physical_valid_q[slot] <= 1'b1;
""" + UPDATE + """
      end
    end
  end
  assign equivalent = !pf_physical_valid_q[PROOF_SLOT] ||
                      pf_epoch_matches[PROOF_SLOT] == direct_matches[PROOF_SLOT];
endmodule
""")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    cases = []
    for slot in range(8):
        script = args.out / f'slot{slot}.ys'
        script.write_text(f'read_slang --top epoch_proof -GPROOF_SLOT={slot} ' + shlex.quote(str(proof.resolve())) +
            '\nprep -top epoch_proof -flatten\nasync2sync\nopt_clean\n' +
            'sat -verify -seq 1 -tempinduct -maxsteps 8 -prove equivalent 1 -show-inputs -show-outputs\n')
        log = args.out / f'slot{slot}.log'
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script.resolve())],
                           cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        assert 'Induction step proven: SUCCESS!' in log.read_text()
        cases.append({'slot': slot, 'passed': True, 'script_sha256': digest(script), 'log_sha256': digest(log)})
        print(f'Slot {slot}: induction passed', flush=True)
    result = {'passed': True, 'reference': args.reference,
              'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
              'actual_source_assignments': True, 'unchanged_outside_saved_comparisons': True,
              'inputs_constrained': False, 'initial_control_state': 'reset state; stored epochs arbitrary',
              'physical_slots': 8, 'epoch_width': 32,
              'property': 'Every valid physical slot has the same saved and direct epoch equality',
              'proof_sha256': digest(proof), 'cases': cases}
    (args.out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
