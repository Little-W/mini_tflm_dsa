#!/usr/bin/env python3
"""使用官方模型证明四通道算术的全部输出，并检查四态和通道独立性。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
MAPPING = ROOT / 'scripts/fpga/techmap/fpga_dsp_alu4.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parameters(config):
    return ', '.join('.'+name+'('+str(value)+')' for name, value in zip(
        ('A_WIDTH','B_WIDTH','Y_WIDTH','A_SIGNED','B_SIGNED'), config))


def equality_harness(configs):
    ports = ['input [3:0] CI', 'input BI']
    for lane, (a, b, width, sa, sb) in enumerate(configs):
        ports += [f'input [{a-1}:0] A{lane}', f'input [{b-1}:0] B{lane}']
    lines = ['module formal_alu4('+', '.join(ports)+');',
             'wire [39:0] packed_a,packed_b,actual_x,actual_y,actual_co;',
             'fpga_dsp_alu4 actual(.A(packed_a),.B(packed_b),.CI(CI),.BI(BI),',
             '    .X(actual_x),.Y(actual_y),.CO(actual_co));']
    for lane, config in enumerate(configs):
        a,b,width,sa,sb = config
        cast = '$signed' if sa and sb else '$unsigned'
        lines += [f'wire [{width-1}:0] a{lane}_extended,b{lane}_extended,reference_x{lane},reference_y{lane},reference_co{lane};',
                  f'assign a{lane}_extended={width}\'({cast}(A{lane}));',
                  f'assign b{lane}_extended={width}\'({cast}(B{lane}));',
                  f'assign packed_a[{10*lane}+:10]=10\'($unsigned(a{lane}_extended));',
                  f'assign packed_b[{10*lane}+:10]=10\'($unsigned(b{lane}_extended));',
                  f'reference_alu #({parameters(config)}) reference{lane}(.A(A{lane}),.B(B{lane}),.CI(CI[{lane}]),.BI(BI),',
                  f'    .X(reference_x{lane}),.Y(reference_y{lane}),.CO(reference_co{lane}));',
                  f'always @* begin assert(actual_x[{10*lane}+:{width}]==reference_x{lane});',
                  f'    assert(actual_y[{10*lane}+:{width}]==reference_y{lane});',
                  f'    assert(actual_co[{10*lane}+:{width}]==reference_co{lane}); end']
    return '\n'.join(lines)+'\nendmodule\n'


def independence_harness(lane):
    return f'''module formal_alu4(input [39:0] A,B,alternate_a,alternate_b,
input [3:0] CI,alternate_ci,input BI);
wire [39:0] changed_a,changed_b,first_x,first_y,first_co,second_x,second_y,second_co;
wire [3:0] changed_ci;
for(genvar part=0;part<4;part++) begin : g_lane
    assign changed_a[10*part+:10]=part=={lane} ? A[10*part+:10] : alternate_a[10*part+:10];
    assign changed_b[10*part+:10]=part=={lane} ? B[10*part+:10] : alternate_b[10*part+:10];
    assign changed_ci[part]=part=={lane} ? CI[part] : alternate_ci[part];
end
fpga_dsp_alu4 first(.A(A),.B(B),.CI(CI),.BI(BI),.X(first_x),.Y(first_y),.CO(first_co));
fpga_dsp_alu4 second(.A(changed_a),.B(changed_b),.CI(changed_ci),.BI(BI),.X(second_x),.Y(second_y),.CO(second_co));
always @* begin
    assert(first_x[{10*lane}+:10]==second_x[{10*lane}+:10]);
    assert(first_y[{10*lane}+:10]==second_y[{10*lane}+:10]);
    assert(first_co[{10*lane}+:10]==second_co[{10*lane}+:10]);
end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--iverilog',default='iverilog')
    parser.add_argument('--vvp',default='vvp')
    args = parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    import pyosys
    share=Path(pyosys.__file__).parent/'share'
    library=share/'xilinx/cells_sim.v';arithmetic=share/'simlib.v'
    dsp=re.search(r'^module DSP48E1\b.*?^endmodule',library.read_text(),re.M|re.S)[0]
    dsp=re.sub(r'\bspecify\b.*?\bendspecify\b','',dsp,flags=re.S)
    alu=re.search(r'^module \\\$alu\s.*?^endmodule',arithmetic.read_text(),re.M|re.S)[0]
    alu=alu.replace('module \\$alu ','module reference_alu ',1)
    models=out/'official_models.sv';models.write_text(dsp+'\n\n'+alu+'\n')
    hashes={str(p.relative_to(ROOT)):digest(p) for p in (MAPPING,Path(__file__).resolve(),HERE/'tb_four_state.sv')}
    report={'source_sha256':hashes,'primitive_library_sha256':digest(library),
            'arithmetic_library_sha256':digest(arithmetic),'official_models_sha256':digest(models),
            'method':'官方 $alu 与 DSP48E1 模型的全部已定义输入 SAT',
            'ports':{'operand_bits_per_lane':10,'lanes':4,'independent_carry_bits':4,'shared_invert_bits':1},
            'formal':[]}
    probe=out/'techmap_probe.sv'
    probe.write_text("module techmap_probe(input [39:0] A,B,input [3:0] CI,input BI,output [39:0] X,Y,CO);\n"
                     "\\$__FPGA_DSP_ALU4 u_helper(.A(A),.B(B),.CI(CI),.BI(BI),.X(X),.Y(Y),.CO(CO));\nendmodule\n")
    structure_script=out/'techmap.ys'
    structure_script.write_text('read_verilog -sv -icells '+shlex.quote(str(probe))+'\nverilog_defaults -push\nverilog_defaults -add -sv\ntechmap -map '+
                                shlex.quote(str(MAPPING))+'\nverilog_defaults -pop\nopt_clean\nwrite_json '+
                                shlex.quote(str(out/'techmap.json'))+'\n')
    with (out/'techmap.log').open('w') as stream:
        subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(structure_script)],
                       cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
    mapped=json.loads((out/'techmap.json').read_text())['modules']['techmap_probe']
    dsps=[cell for cell in mapped['cells'].values() if cell['type']=='DSP48E1']
    assert len(dsps)==1 and dsps[0]['parameters']['USE_SIMD']=='FOUR12'
    assert not any(cell['type']=='$__FPGA_DSP_ALU4' or 'dff' in cell['type'].lower()
                   for cell in mapped['cells'].values())
    registers=('AREG','ACASCREG','BREG','BCASCREG','CREG','DREG','ADREG','MREG','PREG',
               'INMODEREG','OPMODEREG','ALUMODEREG','CARRYINREG','CARRYINSELREG')
    assert all(int(dsps[0]['parameters'][name],2)==0 for name in registers)
    assert all(len(mapped['ports'][name]['bits'])==40 for name in ('A','B','X','Y','CO'))
    assert len(mapped['ports']['CI']['bits'])==4 and len(mapped['ports']['BI']['bits'])==1
    report['structure']={'passed':True,'dsp48e1':1,'use_simd':'FOUR12','internal_registers':0,
                         'techmap_log_sha256':digest(out/'techmap.log'),
                         'techmap_json_sha256':digest(out/'techmap.json')}
    configurations=[
        [(10,10,10,0,0)]*4,
        [(w,w,w,0,0) for w in (1,2,3,4)],
        [(w,w,w,0,0) for w in (5,6,7,8)],
        [(9,9,9,0,0),(10,10,10,1,1),(3,7,10,1,1),(3,7,10,1,0)],
        [(3,7,10,0,1),(13,17,10,0,0),(13,17,10,1,1),(1,12,1,1,1)],
        [(1,6,9,0,0),(8,2,6,1,1),(6,3,4,1,0),(2,9,5,0,1)],
    ]
    tasks=[('equality_'+str(index),equality_harness(configs),{'configurations':configs,'compared_bits':sum(3*x[2] for x in configs)})
           for index,configs in enumerate(configurations)]
    tasks += [('independence_'+str(lane),independence_harness(lane),{'observed_lane':lane,'compared_bits':30}) for lane in range(4)]
    for name,source,info in tasks:
        folder=out/name;folder.mkdir(exist_ok=True)
        harness=folder/'formal.sv';harness.write_text(source)
        script=folder/'formal.ys';log=folder/'formal.log'
        script.write_text('read_verilog -formal -sv -D VERIFIC '+
                          ' '.join(shlex.quote(str(p)) for p in (MAPPING,models,harness))+'\n'
                          'prep -top formal_alu4 -flatten\nchformal -lower\nopt -full\n'
                          'sat -prove-asserts -verify -set-def-inputs -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                           cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise RuntimeError('形式证明未完成：'+name)
        item={'name':name,'passed':True,**info,'log_sha256':digest(log)}
        report['formal'].append(item);print(json.dumps(item),flush=True)
    binary=out/'four_state.vvp'
    with (out/'compile.log').open('w') as stream:
        subprocess.run([args.iverilog,'-g2012','-DVERIFIC','-s','tb_four_state','-o',str(binary),
                        str(MAPPING),str(models),str(HERE/'tb_four_state.sv')],cwd=ROOT,
                       stdout=stream,stderr=subprocess.STDOUT,check=True)
    result=subprocess.run([args.vvp,str(binary)],cwd=ROOT,capture_output=True,text=True,check=True)
    log=out/'four_state.log';log.write_text(result.stdout+result.stderr)
    summaries=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    if len(summaries)!=1:
        raise RuntimeError('四态验证没有给出唯一的结果报告')
    summary=summaries[0];assert summary['passed']
    report['simulation']={**summary,'log_sha256':digest(log),'binary_sha256':digest(binary)}
    if hashes!={name:digest(ROOT/name) for name in hashes}:
        raise RuntimeError('验证期间源码发生变化')
    report['passed']=True
    (out/'summary.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':
    main()
