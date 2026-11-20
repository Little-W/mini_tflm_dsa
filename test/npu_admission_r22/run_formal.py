#!/usr/bin/env python3
"""证明偏置零判断、配置接收、DMA错误和完整控制器状态。"""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from extract import (ROOT, TOP, CTRL, ARB, ADD, REFERENCE, digest, source_at,
                     bias_module, bus_error_module, controller_wrapper, observed_controller,
                     retain_public_and_state)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def run(out, name, commands, expected='SAT proof finished - no model found: SUCCESS!'):
    script, log = out / (name + '.ys'), out / (name + '.log')
    script.write_text('\n'.join(commands) + '\n')
    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=180)
    if expected not in log.read_text():
        raise RuntimeError('Formal check did not complete: '+str(log))
    return {'passed': True, 'script_sha256': digest(script), 'log_sha256': digest(log)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    parser.add_argument('--skip-arbiter', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = (TOP, CTRL, ARB, ADD)
    source_hash = {str(p): digest(ROOT/p) for p in sources}
    old = {p: source_at(p, args.reference) for p in sources}
    current = {p: source_at(p) for p in sources}
    if old[CTRL] != current[CTRL] or old[ADD] != current[ADD]:
        raise RuntimeError('The complete controller and arithmetic helper must be unchanged')
    uses = [line.strip() for line in re.sub(r'//[^\n]*', '', current[CTRL]).splitlines()
            if re.search(r'\bbias_base\b', line)]
    if len(uses) != 2 or "(bias_base == '0)" not in uses[1]:
        raise RuntimeError('Controller bias input has an additional semantic use')
    import pyosys
    library = Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    model = out/'lut_models.v'
    bodies = []
    for name in ('LUT1','LUT2','LUT3','LUT4','LUT5','LUT6','LUT6_2'):
        body = re.search(r'^module '+name+r'\b.*?^endmodule', library.read_text(), re.M|re.S)[0]
        bodies.append(re.sub(r'\bspecify\b.*?\bendspecify\b', '', body, flags=re.S))
    model.write_text('\n\n'.join(bodies)+'\n')
    report = {'passed': False, 'reference_commit': args.reference,
              'source_sha256': source_hash, 'input_constraints': False,
              'controller_bias_uses': uses, 'primitive_library_sha256': digest(library),
              'primitive_models_sha256': digest(model), 'bias': [], 'admission': [],
              'bus_error': [], 'controller': []}
    paths = {}
    for label, values in (('reference', old), ('current', current)):
        folder = out/label
        folder.mkdir(exist_ok=True)
        path = folder/'bias.sv'
        path.write_text(bias_module(values[TOP]))
        paths[label] = path
    miter = out/'bias_miter.sv'
    joined = out/'bias_combined.sv'
    joined.write_text(bias_module(old[TOP], 'bias_reference')+bias_module(current[TOP], 'bias_current'))
    miter.write_text('''module bias_miter #(parameter integer REG_WIDTH=32, parameter bit p_lut=1'b1)(
    input logic [REG_WIDTH-1:0] bias_base, input logic [31:0] exec_channel,
    input logic frame_mode_q,is_mode,ws_final_bias,frame_command_final,frame_command_init,
    output logic equivalent);
    logic [31:0] old_address,new_address;
    logic [REG_WIDTH-1:0] old_bias,new_bias;
    bias_reference #(.REG_WIDTH(REG_WIDTH),.p_admission_use_lut(p_lut)) u_ref(
        .bias_base(bias_base),.exec_channel(exec_channel),.frame_mode_q(frame_mode_q),
        .is_mode(is_mode),.ws_final_bias(ws_final_bias),.frame_command_final(frame_command_final),
        .frame_command_init(frame_command_init),.address(old_address),.controller_bias(old_bias));
    bias_current #(.REG_WIDTH(REG_WIDTH),.p_admission_use_lut(p_lut)) u_dut(
        .bias_base(bias_base),.exec_channel(exec_channel),.frame_mode_q(frame_mode_q),
        .is_mode(is_mode),.ws_final_bias(ws_final_bias),.frame_command_final(frame_command_final),
        .frame_command_init(frame_command_init),.address(new_address),.controller_bias(new_bias));
    assign equivalent=(old_address==new_address)&&((old_bias=='0)==(new_bias=='0));
endmodule
''')
    for width in (1,2,8,16,31,32,33,64):
        for lut in (0,1):
            name=f'bias_w{width}_lut{lut}'
            proof=run(out,name,[f'read_slang --top bias_miter -GREG_WIDTH={width} -Gp_lut={lut} '
                f'{joined} {miter} {ROOT/ADD} {model}', 'prep -top bias_miter -flatten',
                'check -assert','sat -verify -prove equivalent 1 -show-inputs -show-outputs'])
            report['bias'].append({'width':width,'fpga_lut':bool(lut),**proof})
            print(name,'PASS',flush=True)
    admission = load_module('original_admission', ROOT/'test/npu_admission/run_formal.py')
    admission_file=out/'admission.sv'
    admission_file.write_text(admission.admission(old[TOP],'admission_reference')+
                              admission.admission(current[TOP],'admission_current'))
    admission_miter=out/'admission_miter.sv'
    connections=','.join('.'+name+'('+name+')' for name in admission.FLAGS+('abort_state',))
    admission_miter.write_text('module admission_miter(input logic '+','.join(admission.FLAGS)+''',
        input logic [1:0] abort_state,output logic equivalent);
        logic a,b,c,d;
        admission_reference u_ref('''+connections+''',.sa_ready(a),.cfg_start_event(b));
        admission_current u_dut('''+connections+''',.sa_ready(c),.cfg_start_event(d));
        assign equivalent={a,b}=={c,d};
    endmodule
''')
    for lut in (0,1):
        define='XILINX_FPGA=1' if lut else 'ASIC_SYNTHESIS=1'
        proof=run(out,f'admission_lut{lut}',[f'read_slang -D {define} --top admission_miter '
            f'{admission_file} {admission_miter} {model}','prep -top admission_miter -flatten',
            'check -assert','sat -verify -prove equivalent 1 -show-inputs -show-outputs'])
        report['admission'].append({'fpga_lut':bool(lut),'input_bits':15,**proof})
        print('admission',lut,'PASS',flush=True)
    bus=out/'bus_error.sv'
    bus.write_text(bus_error_module(old[ARB],'bus_reference')+bus_error_module(current[ARB],'bus_current')+'''
module bus_miter #(parameter bit p_lut=1'b1)(input logic [11:0] flags,output logic equivalent);
    logic a,b;
    bus_reference #(.p_fpga_control(p_lut)) u_ref(
        .m_axi_rready(flags[0]),.m_axi_rvalid(flags[1]),.m_axi_bready(flags[2]),.m_axi_bvalid(flags[3]),
        .m_axi_rresp(flags[5:4]),.m_axi_bresp(flags[7:6]),.rd_dma_done(flags[8]),.dma_rd_error(flags[9]),
        .wr_dma_done(flags[10]),.dma_wr_error(flags[11]),.bus_error(a));
    bus_current #(.p_fpga_control(p_lut)) u_dut(
        .m_axi_rready(flags[0]),.m_axi_rvalid(flags[1]),.m_axi_bready(flags[2]),.m_axi_bvalid(flags[3]),
        .m_axi_rresp(flags[5:4]),.m_axi_bresp(flags[7:6]),.rd_dma_done(flags[8]),.dma_rd_error(flags[9]),
        .wr_dma_done(flags[10]),.dma_wr_error(flags[11]),.bus_error(b));
    assign equivalent=a==b;
endmodule
''')
    for lut in (0,1):
        proof=run(out,f'bus_lut{lut}',[f'read_slang --top bus_miter -Gp_lut={lut} {bus} {model}',
            'prep -top bus_miter -flatten','check -assert',
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs'])
        report['bus_error'].append({'fpga_lut':bool(lut),'input_bits':12,**proof})
        print('bus',lut,'PASS',flush=True)
    controller_source=out/'controller_observed.sv'
    controller_source.write_text(observed_controller(current[CTRL]))
    wrapper=out/'controller_wrapper.sv'
    wrapper.write_text(controller_wrapper(controller_source.read_text()))
    report['observed_controller_sha256']=digest(controller_source)
    profiles=((1,1,32,False),(8,4,32,True),(16,16,64,True),(31,3,32,True),
              (32,16,64,True),(33,16,128,True),(64,16,64,False))
    for width,size,bus_width,lut in profiles:
        name=f'controller_w{width}_s{size}_b{bus_width}_lut{int(lut)}'
        observed={}
        for label in ('reference','current'):
            netlist=out/(name+'_'+label+'.json')
            run(out,name+'_'+label,[f'read_slang --top controller_compare -GREG_WIDTH={width} '
                f'-GSIZE={size} -GBUS_WIDTH={bus_width} -Gp_admission_use_lut={int(lut)} '
                f'{paths[label]} {wrapper} {controller_source} {ROOT/ADD} {model}',
                'prep -top controller_compare -flatten','memory_map','opt_clean',
                f'write_json {netlist}'],'Executing JSON backend.')
            observed[label]=retain_public_and_state(netlist,'controller_compare')
        if observed['reference'] != observed['current']:
            raise RuntimeError('Complete controller state observation differs')
        commands=[]
        for label in ('reference','current'):
            commands += [f'read_json {out/(name+"_"+label+".json")}',
                'prep -top controller_compare','async2sync',f'rename controller_compare {label}',
                f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
            'design -copy-from current -as current current','equiv_make reference current equivalent',
            'hierarchy -top equivalent','equiv_simple -short -seq 1','opt_clean',
            'equiv_induct -seq 2','equiv_status -assert']
        proof=run(out,name,commands,'Equivalence successfully proven')
        report['controller'].append({'width':width,'size':size,'bus_width':bus_width,
            'fpga_lut':lut,**observed['current'],**proof})
        print(name,'PASS',flush=True)
    if not args.skip_arbiter:
        arbiter=load_module('original_arbiter',ROOT/'test/dma_return_admission/run_arbiter_formal.py')
        original_expand=arbiter.expand_dma_ports
        records=[]
        def expand(path,output):
            ports=original_expand(path,output)
            records.append({'file':output.name,**retain_public_and_state(output,arbiter.TOP)})
            return ports
        arbiter.expand_dma_ports=expand
        saved_argv=sys.argv
        try:
            sys.argv=['run_arbiter_formal.py','--out',str(out/'arbiter'),'--reference-rev',args.reference]
            arbiter.main()
        finally:
            sys.argv=saved_argv
        report['arbiter']=json.loads((out/'arbiter/summary.json').read_text())
        report['arbiter']['state_observation']=records
    if source_hash != {str(p):digest(ROOT/p) for p in sources}:
        raise RuntimeError('RTL changed during formal verification')
    report['passed']=True
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('all formal checks PASS',flush=True)


if __name__=='__main__':
    main()
