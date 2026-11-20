#!/usr/bin/env python3
"""逐周期比较实际控制器，并穷举配置接收及总线错误表达式。"""
import argparse
import json
from pathlib import Path
import re
import subprocess

from extract import (ROOT,TOP,CTRL,ARB,ADD,REFERENCE,digest,source_at,
                     bias_module,controller_wrapper,observed_controller)


def execute(folder,name,sources,model,verilator=False):
    binary=(folder/(name+'_model')/'Vtest') if verilator else folder/(name+'.vvp')
    compile_log=folder/(name+'_compile.log')
    log=folder/(name+'.log')
    with compile_log.open('w') as stream:
        command=(['verilator-modern','--binary','--timing','-Wno-fatal','--top-module','testbench',
                  '--Mdir',str(binary.parent),'--prefix','Vtest','-j','1','-DXILINX_FPGA=1'] if verilator else
                 ['iverilog','-g2012','-DXILINX_FPGA=1','-s','testbench','-o',str(binary)])
        subprocess.run([*command,*map(str,sources),str(model)],cwd=ROOT,stdout=stream,
                       stderr=subprocess.STDOUT,check=True,timeout=240)
    with log.open('w') as stream:
        subprocess.run([str(binary)] if verilator else ['vvp',str(binary)],cwd=ROOT,stdout=stream,
                       stderr=subprocess.STDOUT,check=True,timeout=120)
    if 'PASS' not in log.read_text():raise RuntimeError('Numerical comparison did not finish')
    print(log.read_text().strip(),flush=True)
    return {'passed':True,'binary_sha256':digest(binary),'compile_log_sha256':digest(compile_log),
            'log_sha256':digest(log),'summary':log.read_text().splitlines()[0]}


def controller_test(ports,width,cycles):
    declarations=['logic clk,rst_n;']
    inputs=[];outputs=[];old_conn=['.clk(clk)','.rst_n(rst_n)'];new_conn=list(old_conn)
    for name,port in ports.items():
        if name in ('clk','rst_n') or name.startswith('formal_state_'):continue
        bits=len(port['bits']);size=f'[{bits-1}:0] ' if bits>1 else ''
        if port['direction']=='input':
            declarations.append(f'logic {size}{name};');inputs.append((name,bits))
            old_conn.append(f'.{name}({name})');new_conn.append(f'.{name}({name})')
        else:
            declarations.append(f'wire {size}old_{name},new_{name};');outputs.append(name)
            old_conn.append(f'.{name}(old_{name})');new_conn.append(f'.{name}(new_{name})')
    comparison='{'+','.join('old_'+x for x in outputs)+'} !== {'+','.join('new_'+x for x in outputs)+'}'
    random_inputs='\n'.join(f'            {name}={bits}\'({{$urandom,$urandom}});' for name,bits in inputs)
    initialize='\n'.join(f"        {name}='0;" for name,_ in inputs)
    params=f'#(.REG_WIDTH({width}),.SIZE(16),.BUS_WIDTH(64),.p_admission_use_lut(1\'b1))'
    return '''module testbench;
'''+ '\n'.join(declarations)+f'''
    localparam integer REG_WIDTH={width};
    integer cycle,seed,samples,triggers,accepted,resets;
    logic [15:0] states_seen;
    controller_reference {params} u_ref('''+','.join(old_conn)+''');
    controller_current '''+params+' u_dut('+','.join(new_conn)+f''');
    initial begin
        clk=0;rst_n=0;samples=0;triggers=0;accepted=0;resets=0;states_seen=0;
        seed=32'h63b721e9;seed=$urandom(seed);
{initialize}
        #1;clk=1;#1;clk=0;#1;clk=1;#1;clk=0;
        for(cycle=0;cycle<{cycles};cycle=cycle+1) begin
{random_inputs}
            rst_n=((cycle%511)!=0);
            if(!rst_n)resets=resets+1;
            calc_start=((cycle%9)==0);
            cfg_tiling_error=((cycle%97)==0);
            lhs_base=REG_WIDTH'(32'h1000);rhs_base=REG_WIDTH'(32'h2000);dst_base=REG_WIDTH'(32'h3000);
            k=REG_WIDTH'(1+cycle%17);n=REG_WIDTH'(16+cycle%5);m=REG_WIDTH'(1+cycle%19);
            lhs_row_stride_b=REG_WIDTH'(64);rhs_col_stride_b=REG_WIDTH'(64);dst_row_stride_b=REG_WIDTH'(64);
            q_mult_pt=REG_WIDTH'(1234567);q_shift_pt=REG_WIDTH'(3);
            case(cycle%16)
                0: bias_base='0;
                1: begin bias_base=REG_WIDTH'(32'hffff_fffc);exec_channel=32'd1;
                    frame_mode_q=1;is_mode=1;frame_command_final=1;end
                2: begin bias_base='1;exec_channel=32'd0;end
                3: begin bias_base=REG_WIDTH'(1);exec_channel=32'h3fff_ffff;end
                4: begin bias_base=REG_WIDTH'(4);exec_channel=32'h3fff_ffff;
                    frame_mode_q=1;is_mode=1;frame_command_final=1;end
                5: begin bias_base=REG_WIDTH'(64'h0000_0001_0000_0000);exec_channel=32'd0;
                    frame_mode_q=1;is_mode=1;frame_command_final=1;end
                default: begin end
            endcase
            #1;
            if({comparison})$fatal(1,"controller mismatch before edge cycle=%0d",cycle);
            samples=samples+1;
            if(calc_start&&old_sa_ready)accepted=accepted+1;
            if(old_send_ia_trigger)triggers=triggers+1;
            clk=1;#1;
            if({comparison})$fatal(1,"controller mismatch after edge cycle=%0d",cycle);
            samples=samples+1;
            states_seen[ u_ref.u_controller.current_state ]=1'b1;
            clk=0;
        end
        if((states_seen&16'h01cf)!=16'h01cf||triggers==0||accepted==0)
            $fatal(1,"controller state coverage incomplete %h",states_seen);
        $display("PASS width={width} cycles={cycles} samples=%0d states=%h triggers=%0d accepted=%0d resets=%0d",samples,states_seen,triggers,accepted,resets);
        $finish;
    end
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--formal',type=Path,required=True)
    parser.add_argument('--cycles',type=int,default=20000)
    parser.add_argument('--reference',default=REFERENCE)
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    formal=args.formal.resolve();model=formal/'lut_models.v'
    hashes={str(p):digest(ROOT/p) for p in (TOP,CTRL,ARB,ADD)}
    source=out/'controller_pair.sv'
    controller=observed_controller(source_at(CTRL))
    pieces=[controller]
    for label in ('reference','current'):
        top=source_at(TOP,args.reference if label=='reference' else None)
        pieces.append(bias_module(top,'bias_'+label))
        pieces.append(controller_wrapper(controller,'controller_'+label).replace('bias_logic #','bias_'+label+' #'))
    source.write_text('\n'.join(pieces))
    report={'passed':False,'reference_commit':args.reference,'source_sha256':hashes,
            'primitive_models_sha256':digest(model),'controller':[]}
    for width in (16,32,64):
        name=f'controller_w{width}'
        profile=(formal/f'controller_w{width}_s16_b64_lut{0 if width==64 else 1}_reference.json')
        ports=json.loads(profile.read_text())['modules']['controller_compare']['ports']
        tb=out/(name+'.sv');tb.write_text(controller_test(ports,width,args.cycles))
        row=execute(out,name,[source,tb,ROOT/ADD],model,verilator=True)
        report['controller'].append({'width':width,'cycles':args.cycles,'samples':2*args.cycles,
            'all_register_bits':24,'all_public_outputs':True,'tb_sha256':digest(tb),**row})
    admission=out/'combinational_tb.sv'
    flags=('run_vector','vector_rejected','vector_engine_ready','ctrl_sa_ready',
        'frame_scheduler_ready','cfg_stage0_valid','cfg_stage1_valid','cfg_stage2_valid',
        'operand_cache_idle','ia_prefetch_idle','kernel_prefetch_idle','calc_start','cfg_vector_enable')
    connections=','.join('.'+name+f'(a_flags[{i}])' for i,name in enumerate(flags))
    admission.write_text('''module testbench;
    logic [14:0] a_flags;
    logic [11:0] b_flags;
    wire a_equal,b_equal;
    integer i;
    admission_miter u_a('''+connections+''',.abort_state(a_flags[14:13]),.equivalent(a_equal));
    bus_miter #(.p_lut(1'b1)) u_b(.flags(b_flags),.equivalent(b_equal));
    initial begin
        a_flags=0;b_flags=0;
        for(i=0;i<32768;i=i+1) begin
            a_flags=15'(i);#1;
            if(a_equal!==1'b1)$fatal(1,"admission mismatch %h",a_flags);
        end
        for(i=0;i<4096;i=i+1) begin
            b_flags=12'(i);#1;
            if(b_equal!==1'b1)$fatal(1,"bus error mismatch %h",b_flags);
        end
        $display("PASS admission_combinations=32768 bus_error_combinations=4096");
        $finish;
    end
endmodule
''')
    report['combinational']=execute(out,'combinational',[admission,formal/'admission.sv',
        formal/'admission_miter.sv',formal/'bus_error.sv'],model)
    report['combinational']['admission_combinations']=32768
    report['combinational']['bus_error_combinations']=4096
    if hashes!={str(p):digest(ROOT/p) for p in (TOP,CTRL,ARB,ADD)}:
        raise RuntimeError('RTL changed during numerical comparison')
    report['passed']=True
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
