#!/usr/bin/env python3
"""验证向量请求准备、地址进位与配置范围检查的完整接口等价。"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = '548bda54'
NAMES = ('vector_engine_address', 'vector_read_address_add', 'vector_config_check')
ADDED = ('vector_window_bounds', 'vector_window_request_qualify')
MODES = [('generic', []), ('synthesis', ['-DSYNTHESIS=1']),
         ('fpga', ['-DXILINX_FPGA=1']), ('fpga_synthesis', ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'])]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=900)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    base = ROOT/'rtl/npu/conv'
    reference = out/'reference'
    reference.mkdir(exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', REFERENCE+'^{commit}'], cwd=ROOT, text=True).strip()
    for name in NAMES:
        (reference/(name+'.sv')).write_text(subprocess.check_output(
            ['git', 'show', revision+':rtl/npu/conv/'+name+'.sv'], cwd=ROOT, text=True))
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    dependencies = resolve([base/'vector_engine.sv'], ROOT)
    hashes = {str(path.relative_to(ROOT)): sha(path) for path in dependencies}

    def formal(job):
        label, flags, kind, variant = job
        top = {'address': 'vector_engine_address', 'add': 'vector_read_address_add', 'config': 'vector_config_check'}[kind]
        key = label+'_'+kind+'_'+str(variant)
        if kind == 'address':
            options = ['-Gp_tile=16', '-Gp_bus_width='+('64' if variant else '32'),
                       '-Gp_dma_size=64', '-Gp_pe_count=8', '-Gp_window_lanes='+('8' if variant else '4'),
                       '-Gp_shared_storage_enable='+str(variant), '-Gp_shared_quant_enable=0']
        elif kind == 'add':
            options = ['-Gp_preserve_groups='+str(variant)]
        else:
            options = ['-GTILE=16']
        formal_flags = flags if '-DSYNTHESIS=1' in flags else ['-USYNTHESIS', *flags]
        commands = []
        for side in ('reference', 'candidate'):
            sources = [reference/(top+'.sv')] if side == 'reference' else [base/(top+'.sv')]
            if kind == 'address' and side == 'reference':
                sources.append(reference/'vector_read_address_add.sv')
            files = resolve(sources, ROOT)
            commands += ['read_slang --top '+top+' '+shlex.join([*formal_flags, *options, *map(str, files)]),
                'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
                'prep -top '+top+' -flatten', 'memory_map', 'async2sync', 'opt -full']
            if kind == 'address':
                # 步长算术以完整输入输出关系证明，组合内部信号不单独匹配。
                commands.append('rename -hide w:u_parameter_stride.*')
            commands += ['rename -top '+side, 'design -stash '+side]
        commands += ['design -copy-from reference -as reference reference',
            'design -copy-from candidate -as candidate candidate',
            'equiv_make reference candidate proof', 'hierarchy -top proof',
            'equiv_simple -short -seq 2', 'opt_clean', 'equiv_induct -seq 3', 'equiv_status -assert']
        script, log = out/(key+'.ys'), out/(key+'.log')
        script.write_text('\n'.join(commands)+'\n')
        execute([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        assert 'Equivalence successfully proven!' in log.read_text()
        print(key+' PASS', flush=True)
        return {'mode': label, 'top': top, 'variant': variant, 'passed': True,
                'all_public_outputs_compared': True, 'external_inputs_constrained': False,
                'formal_flags': formal_flags, 'log_sha256': sha(log)}

    add_reference = out/'add_reference.sv'
    add_reference.write_text((reference/'vector_read_address_add.sv').read_text().replace(
        'module vector_read_address_add #(', 'module add_reference #(', 1))
    def explicit_signed_members(text):
        # 按成员声明的位宽和符号展开显式类型转换，保持 packed struct 的标准读出语义。
        fields = [('image.input_offset', 16)]
        fields += [(name, 32) for name in ('output_offset', 'activation_min', 'activation_max')]
        fields += [('add.'+name, 32) for name in ('input1_offset', 'input2_offset', 'input1_multiplier',
            'input1_shift', 'input2_multiplier', 'input2_shift', 'left_shift', 'output_multiplier', 'output_shift')]
        for field, width in fields:
            text = re.sub(r"\bcfg\."+re.escape(field)+r"(?!\s*\[)",
                          "$signed("+str(width)+"'(cfg."+field+"))", text)
        return text
    config_reference = out/'config_reference.sv'
    config_reference.write_text(explicit_signed_members((reference/'vector_config_check.sv').read_text()).replace(
        'module vector_config_check #(', 'module config_reference #(', 1))
    config_candidate = out/'config_candidate.sv'
    config_candidate.write_text(explicit_signed_members((base/'vector_config_check.sv').read_text()))
    parameter_sources = []
    for name, source in [('reference', reference/'vector_engine_address.sv'), ('candidate', base/'vector_engine_address.sv')]:
        text = source.read_text()
        first = text.index('  assign parameter_stride_i_b =')
        last = text.index('  // 配置检查期间', first)
        target = out/(name+'_parameter.sv')
        target.write_text('module '+name+'''_parameter(input logic[31:0]shift_base,multiplier_base,bias_base,
output logic[31:0]parameter_row_stride_next,output logic parameter_two_rows_next,parameter_three_rows_next);
vector_engine_pkg::vector_engine_cfg_t c;
logic[31:0]parameter_stride_i_b;logic unused_parameter_stride_carry,parameter_stride_carry;
logic parameter_stride_equal,parameter_bias_before_multiplier,unused_parameter_bias_equal;
always_comb begin c='0;c.shift_base=shift_base;c.multiplier_base=multiplier_base;c.bias_base=bias_base;end
'''+text[first:last]+'endmodule\n')
        parameter_sources.append(target)
    benches = {}
    benches['add'] = '''module tb;
reg clk=0;reg[31:0]i_base,i_offset;reg[15:0]i_channel;
wire[33:0]expected[2],actual[2];integer checks=0;
for(genvar preserve=0;preserve<2;preserve++)begin:g_mode
add_reference #(.p_preserve_groups(preserve)) ref_dut(.*,.o_address(expected[preserve][31:0]),.o_carry(expected[preserve][33:32]));
vector_read_address_add #(.p_preserve_groups(preserve)) dut(.*,.o_address(actual[preserve][31:0]),.o_carry(actual[preserve][33:32]));
end
initial begin
for(integer sample=0;sample<131072;sample++)begin
 i_base=$urandom;i_offset=$urandom;i_channel=16'($urandom);
 case(sample%16)
 0:begin i_base='1;i_offset='1;i_channel='1;end
 1:begin i_base=32'hffffffff;i_offset=1;i_channel=0;end
 2:begin i_base=32'h0003ffff;i_offset=1;i_channel=0;end
 3:begin i_base=0;i_offset=0;i_channel=0;end
 4:i_base[(sample>>4)%32]=1'bx;
 5:i_offset[(sample>>4)%32]=1'bz;
 6:i_channel[(sample>>4)%16]=1'bx;
 7:begin i_base='x;i_offset='z;end
 default:begin end
 endcase
 #1;for(integer preserve=0;preserve<2;preserve++)begin
 if(actual[preserve]!==expected[preserve])$fatal(1,"读地址结果不同 sample=%0d mode=%0d",sample,preserve);checks++;
 end
end
$display("PASS comparisons=%0d",checks);$finish;end
endmodule
'''
    benches['qualify'] = '''module tb;
reg available,fault,ready,reserved,release_fire,last_group,same_bank;
wire idle=available&&!fault&&!reserved&&!ready;
wire release_enabled=available&&!fault&&!reserved&&last_group&&same_bank;
wire expected=available&&!fault&&(!ready||(release_fire&&last_group&&same_bank))&&!reserved;
wire actual;integer checks=0;
vector_window_request_qualify dut(.i_idle(idle),.i_release_enabled(release_enabled),.i_release(release_fire),.o_valid(actual));
function automatic reg symbol(input integer value);
case(value%4)0:symbol=0;1:symbol=1;2:symbol=1'bx;default:symbol=1'bz;endcase
endfunction
initial begin
for(integer sample=0;sample<16384;sample++)begin
available=symbol(sample);fault=symbol(sample>>2);ready=symbol(sample>>4);reserved=symbol(sample>>6);
release_fire=symbol(sample>>8);last_group=symbol(sample>>10);same_bank=symbol(sample>>12);
#1;if(actual!==expected)$fatal(1,"窗口资格结果不同 sample=%0d",sample);checks++;
end
$display("PASS comparisons=%0d",checks);$finish;end
endmodule
'''
    benches['bounds'] = '''module tb;
reg signed[33:0]i_x,i_y;reg[15:0]i_width,i_height;wire actual;
wire expected=i_x>=0&&i_y>=0&&i_x<$signed(34'(i_width))&&i_y<$signed(34'(i_height));
integer checks=0;vector_window_bounds dut(.*,.o_in_bounds(actual));
initial begin
for(integer sample=0;sample<131072;sample++)begin
 i_x={$urandom,$urandom};i_y={$urandom,$urandom};i_width=16'($urandom);i_height=16'($urandom);
 if(sample%16<12)begin i_x={18'd0,16'($urandom)};i_y={18'd0,16'($urandom)};end
 case(sample%16)
 0:begin i_x=0;i_y=0;end
 1:begin i_x=34'(i_width);i_y=34'(i_height);end
 2:begin i_x=34'(i_width)-1;i_y=34'(i_height)-1;end
 3:i_x=-1;
 4:i_y=65536;
 5:i_x[(sample>>4)%34]=1'bx;
 6:i_y[(sample>>4)%34]=1'bz;
 7:i_width[(sample>>4)%16]=1'bx;
 8:i_height[(sample>>4)%16]=1'bz;
 9:begin i_x='x;i_y=-1;end
 10:begin i_x='x;i_width=0;end
 11:begin i_x='x;i_y='z;end
 default:begin end
 endcase
 #1;if(actual!==expected)$fatal(1,"窗口范围结果不同 sample=%0d",sample);checks++;
end
$display("PASS comparisons=%0d",checks);$finish;end
endmodule
'''
    benches['parameter'] = '''module tb;
reg[31:0]shift_base,multiplier_base,bias_base;wire[33:0]expected,actual;integer checks=0;
reference_parameter ref_dut(.*,.parameter_row_stride_next(expected[31:0]),.parameter_two_rows_next(expected[32]),.parameter_three_rows_next(expected[33]));
candidate_parameter dut(.*,.parameter_row_stride_next(actual[31:0]),.parameter_two_rows_next(actual[32]),.parameter_three_rows_next(actual[33]));
initial begin
for(integer sample=0;sample<65536;sample++)begin
 shift_base=$urandom;multiplier_base=$urandom;bias_base=$urandom;
 case(sample%8)
 0:shift_base=multiplier_base;
 1:begin bias_base=0;shift_base=multiplier_base+1;end
 2:shift_base=2*multiplier_base-bias_base;
 3:shift_base[(sample>>3)%32]=1'bx;
 4:multiplier_base[(sample>>3)%32]=1'bz;
 5:bias_base[(sample>>3)%32]=1'bx;
 6:begin shift_base='x;multiplier_base='z;end
 default:begin end
 endcase
 #1;if(actual!==expected)$fatal(1,"参数地址关系不同 sample=%0d",sample);checks++;
end
$display("PASS comparisons=%0d",checks);$finish;end
endmodule
'''
    benches['config'] = '''module tb;
reg clk=0,rst_n=0,start=0,i_input_range=0;
vector_engine_pkg::vector_engine_cfg_t cfg;
localparam integer CFG_WORDS=($bits(cfg)+31)/32;
reg[32*CFG_WORDS-1:0]random_cfg;
wire er,ed,ee,ar,ad,ae;wire[31:0]ek,ep,ak,ap;
wire[63:0]ei,eo,ew,ai,ao,aw;wire[32:0]e_end[4],a_end[4];integer checks=0;
function automatic[31:0]inject_symbol(input logic[31:0]value,input integer index,input logic symbol);
begin inject_symbol=value;inject_symbol[index]=symbol;end
endfunction
config_reference ref_dut(.*,.ready(er),.done(ed),.error(ee),.kernel_count(ek),.position_count(ep),.input_bytes(ei),.output_bytes(eo),.weight_bytes(ew),.o_read_end(e_end));
vector_config_check dut(.*,.ready(ar),.done(ad),.error(ae),.kernel_count(ak),.position_count(ap),.input_bytes(ai),.output_bytes(ao),.weight_bytes(aw),.o_read_end(a_end));
task check;begin
if({ar,ad,ae,ak,ap,ai,ao,aw,a_end[0],a_end[1],a_end[2],a_end[3],dut.static_fields_ok}!==
   {er,ed,ee,ek,ep,ei,eo,ew,e_end[0],e_end[1],e_end[2],e_end[3],ref_dut.static_fields_ok})$fatal(1,"配置检查不同 sample=%0d",checks);
checks++;end endtask
initial begin
cfg='0;#1;clk=1;#1;clk=0;
for(integer sample=0;sample<16384;sample++)begin
 for(integer word_index=0;word_index<CFG_WORDS;word_index++)random_cfg[32*word_index+:32]=$urandom;
 cfg=random_cfg;
 if(sample%16<14)begin
 cfg='0;cfg.op=4'(sample%11);cfg.length=16;cfg.image.input_h=16;cfg.image.input_w=16;cfg.image.input_c=16;
 cfg.image.kernel_h=3;cfg.image.kernel_w=3;cfg.image.output_h=14;cfg.image.output_w=14;
 cfg.image.stride_h=1;cfg.image.stride_w=1;cfg.image.dilation_h=1;cfg.image.dilation_w=1;
 cfg.activation_min=-128;cfg.activation_max=127;
 cfg.image.input_offset=16'(sample%260-130);cfg.output_offset=sample%260-130;
 cfg.add.input1_offset=sample%260-130;cfg.add.input2_offset=sample%260-130;
 cfg.add.input1_shift=sample%66-33;cfg.add.input2_shift=sample%66-33;
 cfg.add.output_shift=sample%66-33;cfg.add.left_shift=sample%26-1;
 end
 case(sample%16)
 3:cfg.image.input_offset=inject_symbol(cfg.image.input_offset,(sample>>4)%16,1'bx);
 4:cfg.output_offset=inject_symbol(cfg.output_offset,(sample>>4)%32,1'bz);
 5:cfg.add.input1_offset=inject_symbol(cfg.add.input1_offset,(sample>>4)%32,1'bx);
 6:cfg.add.input2_offset=inject_symbol(cfg.add.input2_offset,(sample>>4)%32,1'bz);
 7:cfg.add.input1_shift=inject_symbol(cfg.add.input1_shift,(sample>>4)%32,1'bx);
 8:cfg.add.input2_shift=inject_symbol(cfg.add.input2_shift,(sample>>4)%32,1'bz);
 9:cfg.add.left_shift=inject_symbol(cfg.add.left_shift,(sample>>4)%32,1'bx);
 10:cfg.add.output_shift=inject_symbol(cfg.add.output_shift,(sample>>4)%32,1'bz);
 11:cfg.op=4'bx001;
 default:begin end
 endcase
 rst_n=sample%128!=0;start=sample%64<2;i_input_range=1'(sample);
 #1;check();clk=1;#1;check();clk=0;
end
$display("PASS comparisons=%0d",checks);$finish;end
endmodule
'''
    expected_counts = {'add': 262144, 'qualify': 16384, 'bounds': 131072, 'parameter': 65536, 'config': 32768}
    files_by_kind = {'add': [add_reference, base/'vector_read_address_add.sv'],
                     'qualify': [base/'vector_window_request_qualify.sv'],
                     'bounds': [base/'vector_window_bounds.sv'], 'parameter': parameter_sources,
                     'config': [config_reference, config_candidate]}
    for kind, text in benches.items():
        (out/(kind+'_tb.sv')).write_text(text)

    def four_state(job):
        label, flags, kind = job
        key = label+'_'+kind
        files = resolve(files_by_kind[kind], ROOT)
        simulation = out/(key+'_simulation')
        execute(['iverilog', '-g2012', *flags, '-s', 'tb', '-o', simulation,
                 *files, out/(kind+'_tb.sv')], out/(key+'_compile.log'))
        log = out/(key+'_four_state.log')
        execute(['vvp', simulation], log)
        assert 'PASS comparisons='+str(expected_counts[kind]) in log.read_text()
        print(key+' four-state PASS', flush=True)
        return {'mode': label, 'kind': kind, 'passed': True,
                'comparisons': expected_counts[kind], 'log_sha256': sha(log)}

    jobs = [(label, flags, kind, variant) for label, flags in MODES
            for kind, variant in [('address', 0), ('address', 1), ('add', 0), ('add', 1), ('config', 0)]]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        proofs = list(pool.map(formal, jobs))
        four = list(pool.map(four_state, [(label, flags, kind) for label, flags in MODES for kind in benches
            if kind != 'add' or '-DSYNTHESIS=1' in flags]))
    # 未定义 SYNTHESIS 时，未知输入由逐字相同的三位分组回退和选择表达式处理。
    # 已知输入由完整接口的任意输入二态等价覆盖；其余模式直接比较全部四态输出。
    old_add = (reference/'vector_read_address_add.sv').read_text()
    new_add = (base/'vector_read_address_add.sv').read_text()
    assert old_add[old_add.index('`ifndef SYNTHESIS'):] == new_add[new_add.index('`ifndef SYNTHESIS'):]
    modified = {'rtl/npu/conv/'+name+'.sv' for name in (*NAMES, *ADDED)}
    unchanged = {}
    for source in dependencies:
        relative = str(source.relative_to(ROOT))
        if relative in modified:
            continue
        assert subprocess.check_output(['git', 'show', revision+':'+relative], cwd=ROOT) == source.read_bytes(), relative
        unchanged[relative] = sha(source)
    assert hashes == {name: sha(ROOT/name) for name in hashes}
    report = {'passed': True, 'reference_commit': revision, 'formal': proofs,
              'four_state': four, 'four_state_comparisons': sum(row['comparisons'] for row in four),
              'source_sha256': hashes, 'test_sha256': sha(Path(__file__)),
              'production_composition': {'passed': True, 'method': 'complete_module_interface_equivalence',
                  'modified_modules_proven': list(NAMES), 'all_other_dependencies_unchanged': unchanged,
                  'generic_address_unknown_fallback_and_selection_unchanged': True,
                  'generic_address_binary_interfaces_proven_for_both_group_modes': True,
                  'all_external_inputs_unconstrained': True, 'all_public_cycle_behaviors_preserved': True}}
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'passed': True, 'formal_proofs': len(proofs),
                      'four_state_comparisons': report['four_state_comparisons']}), flush=True)

if __name__ == '__main__':
    main()
