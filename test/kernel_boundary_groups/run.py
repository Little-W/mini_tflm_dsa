#!/usr/bin/env python3
"""验证分组边界比较的完整控制状态、任意输入及四态行为。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/loaders/kernel_loader_ctrl.sv'
HELPER = 'rtl/npu/loaders/kernel_count_next_reaches.sv'
PROFILES = ((4, 4), (16, 16), (16, 29), (32, 32))



def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='a27aa04564960d0284fc3aadf53a9c4e838ab980')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference, candidate = out/'reference.sv', out/'candidate.sv'
    reference.write_bytes(subprocess.check_output(['git', 'show', args.reference+':'+SOURCE], cwd=ROOT))
    candidate.write_bytes((ROOT/SOURCE).read_bytes())
    reference_helper = out/'reference_count.sv'
    reference_helper.write_bytes(subprocess.check_output(['git', 'show', args.reference+':'+HELPER], cwd=ROOT))
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in resolve([ROOT/SOURCE], ROOT)}

    def prove(job):
        (size, count), synthesis = job
        name = f'n{size}_c{count}_fpga{int(synthesis)}'
        options = [f'-GSIZE={size}', f'-GCOUNT_WIDTH={count}']
        if synthesis:
            options += ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']
        else:
            options += ['-USYNTHESIS', '-UXILINX_FPGA']
        commands = []
        for label, path in (('reference', reference), ('candidate', candidate)):
            commands += ['read_slang --top kernel_loader_ctrl '+shlex.join(options+list(map(str, resolve([path]+([reference_helper] if label == 'reference' else []), ROOT)))),
                'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                'prep -top kernel_loader_ctrl -flatten', 'async2sync', 'opt_clean',
                'rename kernel_loader_ctrl '+label, 'design -stash '+label]
        commands += ['design -copy-from reference -as reference reference',
            'design -copy-from candidate -as candidate candidate',
            'equiv_make reference candidate proof', 'hierarchy -top proof',
            'equiv_simple -seq 1', 'equiv_induct -seq 2', 'equiv_status -assert']
        script, log = out/(name+'.ys'), out/(name+'.log')
        script.write_text('\n'.join(commands)+'\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script],
                check=True, stdout=stream, stderr=subprocess.STDOUT, timeout=240)
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', log.read_text())
        if not match or int(match[2]) or 'Equivalence successfully proven!' not in log.read_text():
            raise RuntimeError('完整权重控制模块形式检查未完成：'+name)
        print(name, match[1], 'PASS', flush=True)
        return {'size': size, 'count_width': count, 'synthesis': synthesis,
            'passed': True, 'proven_points': int(match[1]), 'log_sha256': digest(log)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        checks = list(pool.map(prove, [(p, s) for p in PROFILES for s in (False, True)]))
    ctrl = candidate.read_text()
    start = ctrl.index('  (* keep_hierarchy = "yes" *) increment_equal #(')
    end = ctrl.index("  add_equal #(.p_width(CNT_W), .p_preserve_bits(1'b1)) u_following_two_equal", start)
    actual = ctrl[start:end]
    model = out/'arithmetic.sv'
    model.write_text("""// 生产边界比较与完整模宽表达式的比较模型。
module arithmetic #(parameter CNT_W=29)(
 input logic [CNT_W-1:0] value, // 当前计数
 input logic [CNT_W-1:0] limit, // 完成边界
 output logic equal // 两项边界条件均保持完整语义
);
typedef logic [CNT_W-1:0] count_t;
wire [CNT_W-1:0] load_l2=value,l2_groups_total=limit;
logic following_one_equal,following_one_parallel,following_one_reference;
wire reference_equal,reaches;
"""+actual+"""
add_equal #(.p_width(CNT_W),.p_preserve_bits(1'b1)) u_reference(
 .i_a(value),.i_b(CNT_W'(1)),.i_target(limit),.i_carry_in(1'b0),.o_equal(reference_equal));
kernel_count_next_reaches #(.p_width(CNT_W)) u_reaches(
 .i_value(value),.i_limit(limit),.o_reaches(reaches));
assign equal=(following_one_equal===reference_equal)&&
 (reaches===((value+CNT_W'(1))>=limit));
endmodule
""")
    arithmetic_sources = resolve([model], ROOT)
    arithmetic = []
    for width in (1, 2, 4, 16, 29, 32, 64):
        for synthesis in (False, True):
            name = f'w{width}_fpga{int(synthesis)}'
            flags = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if synthesis else ['-USYNTHESIS', '-UXILINX_FPGA']
            script, log = out/(name+'.ys'), out/(name+'_formal.log')
            script.write_text('read_slang --top arithmetic '+shlex.join([f'-GCNT_W={width}', *flags, *map(str, arithmetic_sources)])+
                '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'+
                'prep -top arithmetic -flatten\nsat -verify -prove equal 1 -show-inputs\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script],
                    stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=180)
            assert 'SUCCESS!' in log.read_text()
            bench, binary = out/(name+'_tb.sv'), out/(name+'.vvp')
            bench.write_text(f"""// 随机、回绕及逐位未知输入的严格比较。
module tb;
reg [{width-1}:0] value,limit;wire equal;
arithmetic #(.CNT_W({width})) u_dut(value,limit,equal);
initial begin
 for(integer sample=0;sample<8192;sample++)begin
  value={{$urandom,$urandom}};limit={{$urandom,$urandom}};
  case(sample%10)
   0:value[(sample/10)%{width}]=1'bx;
   1:value[(sample/10)%{width}]=1'bz;
   2:limit[(sample/10)%{width}]=1'bx;
   3:limit[(sample/10)%{width}]=1'bz;
   4:begin value='1;limit=0;end
   5:begin value=0;limit='1;end
   6:limit=value+{width}'(1);
   7:begin value='x;limit='z;end
   default:begin end
  endcase
  #1;if(equal!==1'b1)$fatal(1,"Kernel boundary differs width={width} sample=%0d",sample);
 end
 $display("KERNEL_BOUNDARY_FOUR_STATE_PASS checks=8192");$finish;
end
endmodule
""")
            simulation_flags = flags if synthesis else []
            with (out/(name+'_compile.log')).open('w') as stream:
                subprocess.run(['iverilog','-g2012','-s','tb',*simulation_flags,'-o',str(binary),
                                *map(str,arithmetic_sources),str(bench)],stdout=stream,stderr=subprocess.STDOUT,check=True)
            result = subprocess.check_output(['vvp',str(binary)],text=True,timeout=180)
            (out/(name+'_four_state.log')).write_text(result)
            assert 'PASS checks=8192' in result
            arithmetic.append(dict(width=width,synthesis=synthesis,passed=True,
                                   formal_log_sha256=digest(log),four_state_comparisons=8192,
                                   four_state_log_sha256=digest(out/(name+'_four_state.log'))))
    assert hashes == {name:digest(ROOT/name) for name in hashes}
    report = dict(passed=True,reference=args.reference,source_sha256=hashes,
                  input_assumptions=[],all_public_outputs_and_common_state_compared=True,
                  parent_proofs=checks,arithmetic=arithmetic,four_state_comparisons=114688,
                  test_sha256=digest(Path(__file__)))
    (out/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('KERNEL_BOUNDARY_ALL_PASS',len(checks),len(arithmetic),114688,flush=True)



if __name__ == '__main__':
    main()
