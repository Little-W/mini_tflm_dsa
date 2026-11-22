#!/usr/bin/env python3
"""比较 ASIC 预取关键字段存储的全部读取结果和四态行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/cache/conv_read_cache.sv')


def window_source(root: Path) -> Path:
    path = root / 'rtl/npu/dma/cache/conv_windowed_cache.sv'
    return path if path.exists() else root / SOURCE


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def storage_module(source: str, name: str) -> str:
    start = source.index("  assign prefetch_keys_i_wr_mask = 1'b1;")
    if 'logic [63:0] prefetch_key_entries [PF_DEPTH];' in source:
        start = source.rindex('`ifdef ASIC_SYNTHESIS', 0, start)
    end = source.index('  assign prefetch_payload_i_wr_en = pf_push;', start)
    body = source[start:end]
    selected_memory = ('prefetch_key_entries' if 'logic [63:0] prefetch_key_entries [PF_DEPTH];' in source
                       else 'u_prefetch_selected.mem')
    return f'''module {name} (
 input logic clk, prefetch_keys_i_wr_en,
 input logic [2:0] prefetch_keys_i_wr_addr, pf_read_slot,
 input logic [63:0] prefetch_keys_i_wr_data,
 output wire [7:0][63:0] prefetch_keys_o_rd_data,
 output wire [63:0] pf_selected_keys
);
localparam integer PF_DEPTH=8, PF_AW=3;
wire [0:0] prefetch_keys_i_wr_mask;
wire [7:0] prefetch_keys_i_rd_en;
wire [7:0][2:0] prefetch_keys_i_rd_addr;
for(genvar slot=0;slot<8;slot++)begin:g_address
 assign prefetch_keys_i_rd_addr[slot]=3'(slot);
end
{body}
`ifdef ASIC_SYNTHESIS
// 对比活动项副本的全部存储位置，状态对应关系覆盖每一位数据。
(* keep *) wire [7:0][63:0] selected_storage_state;
for(genvar slot=0;slot<8;slot++)begin:g_selected_state
 assign selected_storage_state[slot]={selected_memory}[slot];
end
`endif
endmodule
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    roots = {'reference': args.reference_root.resolve(), 'current': args.source_root.resolve()}
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    files, hashes = {}, {}
    for label, root in roots.items():
        files[label] = out / (label + '.sv')
        files[label].write_text(storage_module(window_source(root).read_text(), label))
        hashes[label] = sha(window_source(root))
    memory = out / 'regfile.v'
    memory.write_bytes((roots['current'] / 'rtl/common/regfile.v').read_bytes())
    commands = []
    for label, source in files.items():
        commands += [f'read_slang -DSYNTHESIS=1 -DASIC_SYNTHESIS=1 --top {label} ' +
                     shlex.join(map(str, [source, memory])), f'prep -top {label} -flatten',
                     'memory_map', 'opt -full', f'design -stash {label}']
    commands += ['design -copy-from reference -as reference reference',
                 'design -copy-from current -as current current',
                 'equiv_make reference current comparison', 'hierarchy -top comparison',
                 'equiv_simple -short -seq 1', 'opt_clean', 'equiv_induct -seq 2',
                 'equiv_status -assert']
    script, log = out / 'run.ys', out / 'formal.log'
    script.write_text('\n'.join(commands) + '\n')
    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True)
    matched = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', log.read_text())
    assert matched and int(matched[2]) == 0
    testbench = out / 'four_state.sv'
    testbench.write_text('''module four_state;
logic clk=0; always #5 clk=~clk;
logic prefetch_keys_i_wr_en;
logic [2:0] prefetch_keys_i_wr_addr,pf_read_slot;
logic [63:0] prefetch_keys_i_wr_data;
wire [7:0][63:0] old_entries,new_entries;
wire [63:0] old_selected,new_selected;
reference old_dut(.prefetch_keys_o_rd_data(old_entries),.pf_selected_keys(old_selected),.*);
current new_dut(.prefetch_keys_o_rd_data(new_entries),.pf_selected_keys(new_selected),.*);
integer checks=0,unknown_outputs=0;
task automatic compare_outputs;
 if(old_entries !== new_entries || old_selected !== new_selected)
  $fatal(1,"prefetch key storage mismatch check=%0d",checks);
 checks++;
 if($isunknown({old_entries,old_selected}))unknown_outputs++;
endtask
initial begin
 for(int cycle=0;cycle<8192;cycle++)begin
  @(negedge clk);
  prefetch_keys_i_wr_en=$urandom; prefetch_keys_i_wr_addr=$urandom;
  prefetch_keys_i_wr_data={$urandom,$urandom}; pf_read_slot=$urandom;
  case(cycle%19)
   0:prefetch_keys_i_wr_en=1'bx;
   1:prefetch_keys_i_wr_en=1'bz;
   2:prefetch_keys_i_wr_addr[cycle%3]=1'bx;
   3:prefetch_keys_i_wr_addr[cycle%3]=1'bz;
   4:prefetch_keys_i_wr_data[cycle%64]=1'bx;
   5:prefetch_keys_i_wr_data[cycle%64]=1'bz;
   6:pf_read_slot[cycle%3]=1'bx;
   7:pf_read_slot[cycle%3]=1'bz;
   8:pf_read_slot=prefetch_keys_i_wr_addr;
   default:begin end
  endcase
  #1;compare_outputs();
  @(posedge clk);#1;compare_outputs();
 end
 $display("PREFETCH_KEYS_PASS cycles=8192 checks=%0d unknown_outputs=%0d",checks,unknown_outputs);
 $finish;
end
endmodule
''')
    simulation_memory = out / 'regfile_sim.v'
    simulation_memory.write_text(memory.read_text().replace('parameter bit ', 'parameter ').replace(
        'parameter int ', 'parameter integer '))
    binary = out / 'four_state.vvp'
    with (out / 'compile.log').open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-DASIC_SYNTHESIS=1', '-s', 'four_state',
                        '-o', str(binary), str(testbench), *map(str, files.values()),
                        str(simulation_memory)], stdout=stream, stderr=subprocess.STDOUT, check=True)
    run = subprocess.run(['vvp', str(binary)], capture_output=True, text=True, check=True)
    (out / 'four_state.log').write_text(run.stdout + run.stderr)
    count = re.search(r'PREFETCH_KEYS_PASS cycles=(\d+) checks=(\d+) unknown_outputs=(\d+)', run.stdout)
    assert count and int(count[3]) > 0
    preprocessed = []
    for label, root in roots.items():
        target = out / (label + '_fpga.sv')
        subprocess.run(['iverilog', '-g2012', '-E', '-DSYNTHESIS=1', '-DXILINX_FPGA=1',
                        '-o', str(target), str(files[label])], check=True)
        value = re.sub(r'//[^\n]*|/\*.*?\*/', '', target.read_text(), flags=re.S)
        value = re.sub(r'\bmodule\s+(?:reference|current)\b', 'module storage', value)
        preprocessed.append(re.findall(r'\w+|[^\s\w]', value))
    assert preprocessed[0] == preprocessed[1]
    assert all(hashes[label] == sha(window_source(root)) for label, root in roots.items())
    report = dict(passed=True, external_inputs_constrained=False, source_sha256=hashes,
                  regfile_sha256=sha(memory), compared_outputs_bits=576,
                  equivalent_bits=int(matched[1]), four_state_cycles=int(count[1]),
                  four_state_checks=int(count[2]), unknown_output_checks=int(count[3]),
                  fpga_identical_storage_tokens=len(preprocessed[0]),
                  logical_storage_bits=512, prefetch_entries=8,
                  checker_sha256=sha(Path(__file__)))
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
