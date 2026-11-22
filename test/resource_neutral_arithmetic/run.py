#!/usr/bin/env python3
"""验证公共算术的完整二值等价及统一四态传播。"""
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
MODULES = ('add_equal', 'unsigned_compare', 'onehot_check', 'parallel_prefix_add')
PROFILES = [(1, 1, 0), (3, 3, 1), (8, 3, 0), (17, 8, 1), (24, 3, 1),
            (32, 8, 0), (33, 3, 1), (47, 8, 1), (48, 3, 0), (64, 8, 1)]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


MITER = '''module arithmetic_comparison #(
 parameter integer W=32,G=8,P=0
)(input logic [W-1:0] a,b,target,input logic carry,
 output logic equivalent,output logic [W+6:0] original,updated);
localparam integer L=W<=4 ? W-1 : W==33 ? 6 : W==48 ? 16 : 4;
logic [W-1:0] old_sum,new_sum;
logic old_carry,new_carry,old_add,new_add,old_less,new_less,old_equal,new_equal;
logic [1:0] old_onehot,new_onehot;
logic old_coordinate,new_coordinate;
parallel_prefix_add_ref #(.p_width(W),.p_group_width(G),.p_preserve_groups(P)) old_adder(
 .i_a(a),.i_b(b),.i_carry(carry),.o_sum(old_sum),.o_carry(old_carry));
parallel_prefix_add #(.p_width(W),.p_group_width(G),.p_preserve_groups(P)) new_adder(
 .i_a(a),.i_b(b),.i_carry(carry),.o_sum(new_sum),.o_carry(new_carry));
add_equal_ref #(.p_width(W)) old_add_compare(
 .i_a(a),.i_b(b),.i_target(target),.i_carry_in(carry),.o_equal(old_add));
add_equal #(.p_width(W)) new_add_compare(
 .i_a(a),.i_b(b),.i_target(target),.i_carry_in(carry),.o_equal(new_add));
unsigned_compare_ref #(.p_width(W)) old_compare(.i_a(a),.i_b(b),.o_less(old_less),.o_equal(old_equal));
unsigned_compare #(.p_width(W)) new_compare(.i_a(a),.i_b(b),.o_less(new_less),.o_equal(new_equal));
for(genvar mode=0;mode<2;mode++)begin:g_onehot
 onehot_check_ref #(.p_width(W),.p_allow_zero(mode)) old_check(.i_value(a),.o_valid(old_onehot[mode]));
 onehot_check #(.p_width(W),.p_allow_zero(mode)) new_check(.i_value(a),.o_valid(new_onehot[mode]));
end
ia_ordered_coordinate_equal_ref #(.p_width(W),.p_low_width(L)) old_coordinate_compare(
 .i_a(a),.i_b(b),.i_target(target[W-L-1:0]),.o_equal(old_coordinate));
ia_ordered_coordinate_equal #(.p_width(W),.p_low_width(L)) new_coordinate_compare(
 .i_a(a),.i_b(b),.i_target(target[W-L-1:0]),.o_equal(new_coordinate));
assign original={old_sum,old_carry,old_add,old_less,old_equal,old_onehot,old_coordinate};
assign updated={new_sum,new_carry,new_add,new_less,new_equal,new_onehot,new_coordinate};
assign equivalent=original==updated;
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
    sources, hashes = [], {}
    for label, root in roots.items():
        hashes[label] = {}
        for module in MODULES:
            source = root / f'rtl/common/{module}.sv'
            value = source.read_text()
            if label == 'reference':
                for old in MODULES:
                    value = re.sub(r'\b' + old + r'\b', old+'_ref', value)
            target = out / f'{label}_{module}.sv'
            target.write_text(value)
            hashes[label][module] = sha(source)
            sources.append(target)
    coordinate_sources = {}
    for label, root in roots.items():
        source = root / 'rtl/npu/loaders/ia_ordered_coordinate_equal.sv'
        if not source.exists():
            source = root / 'rtl/npu/loaders/ia_loader.sv'
        coordinate_sources[label] = source
        value = re.search(r'module ia_ordered_coordinate_equal\b[\s\S]*?endmodule', source.read_text())[0]
        if label == 'reference':
            for module in (*MODULES, 'ia_ordered_coordinate_equal'):
                value = re.sub(r'\b'+module+r'\b', module+'_ref', value)
        target = out / (label+'_ia_ordered_coordinate_equal.sv')
        target.write_text(value+'\n')
        sources.append(target)
        hashes[label]['ia_ordered_coordinate_equal'] = sha(source)
    miter = out / 'miter.sv'
    miter.write_text(MITER)
    records = []
    for mode, defines in [('generic', []), ('asic', ['-DASIC_SYNTHESIS=1']),
                          ('fpga', ['-DXILINX_FPGA=1'])]:
        for width, group, preserve in PROFILES:
            name = f'{mode}_w{width}_g{group}_p{preserve}'
            script, log = out / (name+'.ys'), out / (name+'.log')
            commands = ['read_slang --top arithmetic_comparison -DSYNTHESIS=1 '+
                        shlex.join(defines+[f'-GW={width}', f'-GG={group}', f'-GP={preserve}',
                                           str(miter), *map(str, sources)]),
                        'prep -top arithmetic_comparison -flatten', 'check -assert',
                        'sat -verify -prove equivalent 1 -show-inputs -show-outputs']
            script.write_text('\n'.join(commands)+'\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                                '--worker', str(script)], stdout=stream,
                               stderr=subprocess.STDOUT, check=True, timeout=180)
            assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
            records.append(dict(mode=mode, width=width, group_width=group,
                                preserve_groups=preserve, passed=True, log_sha256=sha(log)))
        print(json.dumps(dict(mode=mode, passed=True, cases=len(PROFILES))), flush=True)
    declarations, instances, comparisons = [], [], []
    for index, (width, group, preserve) in enumerate(PROFILES):
        declarations.append(f'wire [{width+6}:0] original_{index},updated_{index}; wire eq_{index};')
        instances.append(f'''arithmetic_comparison #(.W({width}),.G({group}),.P({preserve})) u_{index}(
 .a(a[{width-1}:0]),.b(b[{width-1}:0]),.target(target[{width-1}:0]),.carry(carry),
 .equivalent(eq_{index}),.original(original_{index}),.updated(updated_{index}));''')
        comparisons.append(f'''if(original_{index} !== updated_{index})
 $fatal(1,"arithmetic four-state mismatch profile={index} cycle=%0d old=%h new=%h",cycle,original_{index},updated_{index});
checks++; if($isunknown(original_{index})) unknown_checks++;''')
    testbench = out / 'four_state.sv'
    testbench.write_text('''module four_state;
logic [63:0] a,b,target; logic carry;
integer checks=0,unknown_checks=0;
'''+ '\n'.join(declarations+instances)+'''
initial begin
 for(int cycle=0;cycle<20000;cycle++)begin
  a={$urandom,$urandom};b={$urandom,$urandom};carry=$urandom;
  target=cycle%3 ? {$urandom,$urandom} : a+b+64'(carry);
  case(cycle%13)
   0:a[cycle%64]=1'bx;
   1:a[cycle%64]=1'bz;
   2:b[(cycle*7)%64]=1'bx;
   3:b[(cycle*7)%64]=1'bz;
   4:carry=1'bx;
   5:carry=1'bz;
   6:target[(cycle*11)%64]=1'bx;
   7:target[(cycle*11)%64]=1'bz;
   8:a='0;
   9:a=64'(1)<<(cycle%64);
   default:begin end
  endcase
  #1;
'''+ '\n'.join(comparisons)+'''
 end
 $display("ARITHMETIC_FOUR_STATE_PASS checks=%0d unknown_checks=%0d",checks,unknown_checks);
 $finish;
end
endmodule
''')
    simulation_sources = []
    for source in sources+[miter]:
        target_file = out / ('sim_'+source.name)
        value = source.read_text().replace('parameter int unsigned ', 'parameter integer ')
        value = value.replace('localparam int unsigned ', 'localparam integer ')
        target_file.write_text(value)
        simulation_sources.append(target_file)
    binary = out/'four_state.vvp'
    with (out/'four_state_compile.log').open('w') as stream:
        subprocess.run(['iverilog','-g2012','-s','four_state','-o',str(binary),str(testbench),
                        *map(str,simulation_sources)], stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run(['vvp',str(binary)], capture_output=True, text=True, check=True)
    (out/'four_state.log').write_text(result.stdout+result.stderr)
    count = re.search(r'checks=(\d+) unknown_checks=(\d+)', result.stdout)
    assert count and int(count[2])>0
    for label, root in roots.items():
        assert all(sha(root/f'rtl/common/{module}.sv')==hashes[label][module] for module in MODULES)
        assert sha(coordinate_sources[label]) == hashes[label]['ia_ordered_coordinate_equal']
    report = dict(passed=True, external_inputs_constrained=False, source_sha256=hashes,
                  binary_formal=records, four_state_checks=int(count[1]),
                  unknown_result_checks=int(count[2]),
                  four_state_reference='generic grouped arithmetic and carry-consistency comparison',
                  checker_sha256=sha(Path(__file__)))
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True, formal_cases=len(records),
                         four_state_checks=int(count[1]), unknown_result_checks=int(count[2]))),flush=True)


if __name__=='__main__':
    main()
