#!/usr/bin/env python3
"""检查窗口接收计数的完整位宽加法、回绕及四态传播。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'rtl/npu/conv/vector_window_count_add.sv'
PROFILES = ((32, 1), (32, 4), (32, 5), (64, 9), (8, 8), (8, 12))
REFERENCE = '8b3728c008e6093095c8ade34aa4516145bc6005'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log):
    with log.open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=180)


def prove_address(out, reader):
    relative = Path('rtl/npu/conv/vector_engine_address.sv')
    original = out/'address_reference.sv'
    original.write_bytes(subprocess.check_output(['git', 'show', f'{REFERENCE}:{relative}'], cwd=ROOT))
    options = ('-Gp_tile=16 -Gp_bus_width=64 -Gp_dma_size=64 -Gp_pe_count=8 '
               '-Gp_window_lanes=8 -Gp_shared_quant_enable=1 -Gp_shared_storage_enable=1 '
               '-Gp_registered_read_phase=1')
    commands = []
    for label, source in [('reference', original), ('candidate', ROOT/relative)]:
        dependencies = reader['with_dependencies']([source], ROOT)
        commands += ['read_slang --top vector_engine_address -D SYNTHESIS=1 '+options+' '+
                     shlex.join(map(str, dependencies)),
                     'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                     'prep -top vector_engine_address -flatten', 'async2sync', 'opt -full',
                     'opt_clean -purge', f'rename vector_engine_address {label}',
                     f'design -stash {label}']
    commands += ['design -copy-from reference -as reference reference',
                 'design -copy-from candidate -as candidate candidate',
                 'equiv_make reference candidate equivalent', 'hierarchy -top equivalent',
                 'equiv_simple -seq 2', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert']
    script = out/'address_formal.ys'
    script.write_text('\n'.join(commands)+'\n')
    log = out/'address_formal.log'
    execute([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)], log)
    assert 'Equivalence successfully proven' in log.read_text()
    return {'reference_commit': REFERENCE, 'passed': True, 'inputs_constrained': False,
            'source_sha256': digest(ROOT/relative), 'log_sha256': digest(log)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reader = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
    sources = reader['with_dependencies']([SOURCE], ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    reports = []
    for width, increment in PROFILES:
        folder = out/f'width{width}_increment{increment}'
        folder.mkdir(exist_ok=True)
        checker = folder/'checker.sv'
        checker.write_text(f'''module count_comparison(
input logic [{width-1}:0] value,
input logic [{increment-1}:0] amount,
output logic [{width-1}:0] expected,actual,
output logic equal);
logic unused_carry;
parallel_prefix_add #(.p_width({width})) reference_add(
.i_a(value),.i_b({width}'(amount)),.i_carry(1'b0),.o_sum(expected),.o_carry(unused_carry));
vector_window_count_add #(.p_width({width}),.p_increment_width({increment})) candidate_add(
.i_value(value),.i_increment(amount),.o_sum(actual));
assign equal=actual==expected;
endmodule
''')
        script = folder/'formal.ys'
        script.write_text('read_slang -D SYNTHESIS=1 --top count_comparison '+
            shlex.join(map(str,sources+[checker]))+
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'+
            'prep -top count_comparison -flatten\nsat -verify -prove equal 1 -show-inputs -show-outputs\n')
        execute([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],folder/'formal.log')
        bench = folder/'tb.sv'
        bench.write_text(f'''module tb;
logic[{width-1}:0] value,saved_value;
logic[{increment-1}:0] amount,saved_amount;
wire[{width-1}:0] expected,actual;
wire equal;
integer checks=0;
count_comparison dut(.value(value),.amount(amount),.expected(expected),.actual(actual),.equal(equal));
task verify;
#1;if(actual!==expected)$fatal(1,"窗口计数结果不一致");checks++;
endtask
initial begin
for(int sample=0;sample<10000;sample++)begin
value={{$random,$random}};amount={{$random,$random}};
case(sample%5)
0:value='0;1:value='1;2:amount='0;3:amount='1;default:begin end
endcase
verify();saved_value=value;saved_amount=amount;
value[sample%{width}]=1'bx;verify();value=saved_value;
amount[sample%{increment}]=1'bz;verify();amount=saved_amount;
end
$display("PASS %0d four-state comparisons",checks);$finish;
end
endmodule
''')
        for synthesis in (False,True):
            name = 'synthesis' if synthesis else 'generic'
            binary = folder/(name+'.vvp')
            command=['iverilog','-g2012','-s','tb','-o',str(binary)]
            if synthesis:
                command+=['-D','SYNTHESIS=1']
            execute(command+list(map(str,sources+[checker,bench])),folder/(name+'_build.log'))
            execute(['vvp',str(binary)],folder/(name+'.log'))
            assert 'PASS 30000' in (folder/(name+'.log')).read_text()
        reports.append({'width':width,'increment_width':increment,'passed':True,
                        'formal_log_sha256':digest(folder/'formal.log'),
                        'four_state_comparisons':60000})
        print(f'width={width} increment={increment} PASS',flush=True)
    address_report = prove_address(out, reader)
    assert hashes == {str(path.relative_to(ROOT)):digest(path) for path in sources}
    (out/'summary.json').write_text(json.dumps({'passed':True,'inputs_constrained':False,
        'source_sha256':hashes,'profiles':reports,'address_equivalence':address_report},indent=2)+'\n')


if __name__=='__main__':
    main()
