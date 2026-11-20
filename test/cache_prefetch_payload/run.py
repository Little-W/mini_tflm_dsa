#!/usr/bin/env python3
"""验证预取描述同步存储的完整状态关系与四态周期行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import resource
import shlex
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/cache/conv_read_cache.sv')
STORAGE_START = '  assign prefetch_payload_i_wr_en = pf_push;'
STORAGE_END = '  // 从队首开始循环查找第一个代次匹配项'
CAPTURE = 'if (!pf_active_valid && pf_count != 0 && !clearing) begin'
FIELDS = (
    '          pf_index<=prefetch_payload_o_rd_data[63:32];\n',
    '          pf_retire<=prefetch_payload_o_rd_data[31:0];\n',
    '          pf_index_valid<=prefetch_payload_o_rd_data[64];\n',
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def storage(source):
    return source[source.index(STORAGE_START):source.index(STORAGE_END)]


def boundaries(source):
    marker = '  logic prefetch_retire_i_wr_en;'
    if marker not in source:
        return ''
    return source[source.index(marker):source.index('  logic pf_push, pf_pop,')]


def helper(source, name):
    assert source.count(CAPTURE) == 1
    assert all(source.count(field) == 1 for field in FIELDS)
    sequential = '''
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
    end else if (cfg_valid && cfg_ready) begin
    end else begin
      ''' + CAPTURE + '\n' + ''.join(FIELDS) + '''
      end
    end
  end
'''
    memory = ('{u_prefetch_index.mem[row], u_prefetch_retire.mem[row]}'
              if 'u_prefetch_retire (' in source else 'u_prefetch_payload.mem[row]')
    return f'''module {name} (
  input logic clk, rst_n, cfg_valid, cfg_ready, pf_active_valid, clearing,
  input logic [3:0] pf_count,
  input logic pf_push, pf_offer_index_valid,
  input logic [2:0] pf_push_slot, pf_read_slot,
  input logic [31:0] pf_offer_index, pf_offer_retire,
  output logic [64:0] payload,
  output logic [519:0] contents
);
  localparam int PF_DEPTH=8, PF_AW=3;
  logic prefetch_payload_i_wr_en, prefetch_payload_i_wr_mask;
  logic prefetch_payload_i_rd_en;
  logic [2:0] prefetch_payload_i_wr_addr, prefetch_payload_i_rd_addr;
  logic [64:0] prefetch_payload_i_wr_data, prefetch_payload_o_rd_data;
  logic [31:0] pf_index, pf_retire;
  logic pf_index_valid;
{boundaries(source)}
{storage(source)}
{sequential}
  assign payload = {{pf_index_valid, pf_index, pf_retire}};
  for (genvar row=0; row<8; row++) begin : g_observe
    assign contents[row*65+:65] = {memory};
  end
endmodule
'''


PORTS = '''
  input logic clk, rst_n, cfg_valid, cfg_ready, pf_active_valid, clearing,
  input logic [3:0] pf_count,
  input logic pf_push, pf_offer_index_valid,
  input logic [2:0] pf_push_slot, pf_read_slot,
  input logic [31:0] pf_offer_index, pf_offer_retire,
'''
INSTANCES = '''
  logic [64:0] reference_payload, current_payload;
  logic [519:0] reference_contents, current_contents;
  reference_payload u_reference (.payload(reference_payload), .contents(reference_contents), .*);
  current_payload u_current (.payload(current_payload), .contents(current_contents), .*);
'''

TESTBENCH = '''module tb;
  logic clk=0, rst_n=0, cfg_valid=0, cfg_ready=0, pf_active_valid=0, clearing=0;
  logic [3:0] pf_count=0;
  logic pf_push=0, pf_offer_index_valid=0;
  logic [2:0] pf_push_slot=0, pf_read_slot=0;
  logic [31:0] pf_offer_index=0, pf_offer_retire=0;
  logic [8:0] controls;
  logic [64:0] data_value;
  int cycles=0;
''' + INSTANCES + '''
  function automatic logic four_digit(input int value);
    case (value & 3)
      0: four_digit=1'b0;
      1: four_digit=1'b1;
      2: four_digit=1'bx;
      3: four_digit=1'bz;
    endcase
  endfunction
  task automatic cycle;
    #1;
    if (reference_payload !== current_payload || reference_contents !== current_contents)
      $fatal(1,"asynchronous event differs cycle=%0d",cycles);
    clk=1; #1;
    if (reference_payload !== current_payload || reference_contents !== current_contents)
      $fatal(1,"payload or memory differs cycle=%0d ref=%h current=%h", cycles,
             reference_payload,current_payload);
    clk=0; #1; cycles++;
  endtask
  initial begin
    cycle();
    // 全部地址先保存已知内容，控制输入的四态检查持续观察确定的数据。
    for (int row=0;row<8;row++) begin
      pf_push=1; pf_push_slot=3'(row);
      pf_offer_index=32'h12345678+32'(row);
      pf_offer_retire=32'hac024680^32'(row*71);
      pf_offer_index_valid=1; cycle();
    end
    rst_n=1; pf_count=1;
    // 同一边沿读写每个地址，输出读取更新前的内容。
    for (int row=0;row<8;row++) begin
      pf_read_slot=3'(row);pf_push_slot=3'(row);
      pf_offer_index=32'hff001122-32'(row);
      pf_offer_retire=32'h76543210+32'(row);cycle();
    end
    pf_push=0;
    // 五个控制输入和四位计数的全部四态组合。
    for (int vector=0;vector<262144;vector++) begin
      for (int bit_index=0;bit_index<9;bit_index++)
        controls[bit_index]=four_digit(vector>>(2*bit_index));
      {rst_n,cfg_valid,cfg_ready,pf_active_valid,clearing,pf_count}=controls;
      pf_read_slot=3'(vector);cycle();
    end
    rst_n=1;cfg_valid=0;cfg_ready=0;pf_active_valid=0;clearing=0;pf_count=1;
    // 地址的全部四态组合覆盖未知地址的读取语义。
    for (int vector=0;vector<64;vector++) begin
      for (int bit_index=0;bit_index<3;bit_index++)
        pf_read_slot[bit_index]=four_digit(vector>>(2*bit_index));
      cycle();
    end
    // 数据和写使能包含 X/Z；读取暂停后继续读取同一内容。
    for (int vector=0;vector<1024;vector++) begin
      data_value={$urandom,$urandom,1'b1};
      data_value[vector%65]=1'bx;
      data_value[(vector+17)%65]=1'bz;
      {pf_offer_index_valid,pf_offer_index,pf_offer_retire}=data_value;
      pf_push=four_digit(vector);pf_push_slot=3'(vector);
      pf_read_slot=3'(vector+1);pf_active_valid=vector%3==0;cycle();
    end
    $display("FOUR_STATE_PASS cycles=%0d controls=262144 addresses=64",cycles);
    $finish;
  end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='8720e2c7')
    parser.add_argument('--iverilog', default=shutil.which('iverilog') or 'iverilog')
    parser.add_argument('--vvp', default=shutil.which('vvp') or 'vvp')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT, text=True)
    for prefix in ('prefetch_retire', 'prefetch_index'):
        instance = re.search(r'\) u_' + prefix + r' \((.*?)\n  \);', current, re.S)
        assert instance is not None
        for port, signal in re.findall(r'\.(\w+)\(([^()]*)\)', instance[1]):
            assert re.fullmatch(r'[a-zA-Z_]\w*', signal)
            assert signal == 'clk' if port == 'clk' else signal.startswith(prefix + '_')
    normalized = current.replace(storage(current), storage(reference), 1)
    normalized = normalized.replace(boundaries(current), boundaries(reference), 1)
    if normalized != reference:
        raise ValueError('预取描述的存储实例以外存在未覆盖的修改')
    outer = reference[reference.rindex('  always_ff @(posedge clk or negedge rst_n) begin'):]
    assert outer.index('    if (!rst_n) begin') < outer.index('      if (cfg_valid && cfg_ready) begin')
    assert outer.index('      end else begin') < outer.index(CAPTURE)
    helpers = helper(reference, 'reference_payload') + helper(current, 'current_payload')
    proof = out / 'proof.sv'
    proof.write_text(helpers + 'module proof (\n' + PORTS +
        '  output logic equivalent_state\n);\n' + INSTANCES +
        '  assign equivalent_state = {reference_contents,reference_payload} ==\n' +
        '                            {current_contents,current_payload};\nendmodule\n')
    regfile = ROOT / 'rtl/common/regfile.v'
    script = out / 'run.ys'
    script.write_text('read_slang --top proof ' +
        ' '.join(shlex.quote(str(path)) for path in (proof, regfile)) + '\n' +
        'prep -top proof -flatten\nasync2sync\nmemory_map\nopt_clean\n' +
        'sat -seq 2 -set-at 1 equivalent_state 1 -prove-skip 1 ' +
        '-prove equivalent_state 1 -show-inputs -show-outputs -verify\n')
    formal_log = out / 'formal.log'
    with formal_log.open('w') as log:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], cwd=ROOT, stdout=log,
                       stderr=subprocess.STDOUT, check=True, timeout=120)
    assert 'SAT proof finished - no model found: SUCCESS!' in formal_log.read_text()
    bench = out / 'tb.sv'
    bench.write_text(helpers + TESTBENCH)
    sim_regfile = out / 'regfile.sv'
    sim_regfile.write_text(regfile.read_text().replace('parameter string p_ram_style',
                                                     'parameter p_ram_style'))
    executable = out / 'simulation'
    compile_log = out / 'compile.log'
    with compile_log.open('w') as log:
        subprocess.run([args.iverilog, '-g2012', '-s', 'tb', '-o', str(executable),
                        str(bench), str(sim_regfile)], stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=120)
    run = subprocess.run([args.vvp, str(executable)], capture_output=True, text=True,
                         check=True, timeout=120)
    sim_log = out / 'simulation.log'
    sim_log.write_text(run.stdout + run.stderr)
    passed = next(line for line in run.stdout.splitlines() if line.startswith('FOUR_STATE_PASS'))
    cases = int(re.search(r'cycles=(\d+)', passed)[1])
    result = {'passed': True, 'reference_ref': args.reference,
        'source_sha256': sha(ROOT / SOURCE),
        'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
        'regfile_sha256': sha(regfile),
        'unchanged_outside_payload_storage_and_boundaries': True,
        'named_instance_boundary_signals': True,
        'memory_bits': 520, 'output_state_bits': 65,
        'formal': {'method': 'arbitrary equal memory/output state; one-step induction',
                   'inputs_constrained': False, 'passed': True, 'log_sha256': sha(formal_log)},
        'four_state': {'cycles': cases, 'control_vectors': 262144, 'read_address_vectors': 64,
                       'checks_before_and_after_clock_edge': True,
                       'passed': True, 'log_sha256': sha(sim_log),
                       'regfile_type_normalization': 'string parameter type omitted for Icarus parser'},
        'proof_sha256': sha(proof), 'testbench_sha256': sha(bench),
        'maximum_child_rss_kib': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss}
    if hashlib.sha256(current.encode()).hexdigest() != result['source_sha256']:
        raise RuntimeError('验证期间 RTL 内容变化')
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
