#!/usr/bin/env python3
"""证明四 DSP 完整 INT32 乘法的输入寄存、部分积及任意暂停行为。"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def input_values(a, b):
    """将完整 INT32 操作数分成十七位低段和十五位有符号高段。"""
    return ([a[:17] + ['0'] * 13, a[:17] + ['0'] * 13,
             a[17:] + [a[31]] * 15, a[17:] + [a[31]] * 15] +
            [b[:17] + ['0'], b[17:] + [b[31]] * 3,
             b[:17] + ['0'], b[17:] + [b[31]] * 3])


def run_formal(source: Path, out: Path) -> dict:
    root = ROOT
    out.mkdir(parents=True, exist_ok=True)
    spec=importlib.util.spec_from_file_location('proof',root/'test/requant_product/run_formal.py')
    proof=importlib.util.module_from_spec(spec);spec.loader.exec_module(proof)
    import pyosys
    library=Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    models=[]
    for name in ['DSP48E1','FDRE']:
     text=re.search(r'^module '+name+r'\b.*?^endmodule',library.read_text(),re.M|re.S)[0]
     models.append(re.sub(r'\bspecify\b.*?\bendspecify\b','',text,flags=re.S))
    model=out/'models.sv';model.write_text('\n'.join(models)+'\n')

    def run(stem,commands):
     code,text=proof.run_script(out,stem,commands)
     if code: raise RuntimeError(text[-10000:])
     return text

    def only_ports(module,label):
     for item in list(module['netnames'].values())+list(module['cells'].values()):
      item.get('attributes',{}).pop('keep',None)
     module['netnames']={name if name in module['ports'] else f'$formal_{label}_{i}':value
                         for i,(name,value) in enumerate(module['netnames'].items())}
     return module

    def compare(stem,modules):
     commands=[]
     for label,module in modules.items():
      module=only_ports(copy.deepcopy(module),label)
      module['attributes']['top']='1'
      path=out/(stem+'_'+label+'.json')
      path.write_text(json.dumps({'modules':{label:module}}))
      commands+=['read_json '+str(path),'wreduce','opt -full','design -stash '+label]
     commands+=['design -copy-from reference -as reference reference',
                'design -copy-from candidate -as candidate candidate',
                'equiv_make reference candidate equiv','hierarchy -top equiv','opt_clean','opt_merge',
                'equiv_simple -seq 2','equiv_induct -seq 2','equiv_status -assert']
     text=run(stem,commands)
     assert 'Equivalence successfully proven' in text
     result={'passed':True,'equivalent_bits':int(re.search(r'Of those cells (\d+) are proven',text)[1]),
             'log_sha256':hashlib.sha256((out/(stem+'.log')).read_bytes()).hexdigest()}
     print(stem,json.dumps(result),flush=True)
     return result

    summary={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
             'primitive_library_sha256':hashlib.sha256(library.read_bytes()).hexdigest(),
             'inputs_constrained':False,'clock_enable_constrained':False,
             'arithmetic_enabled_edges':2,'partial_stages':[]}
    all_modules={}
    for areg,breg in [(0,0),(0,1),(1,0),(1,1)]:
     prefix=f'a{areg}_b{breg}'
     wrapper=out/(prefix+'_reference.sv')
     wrapper.write_text('''module partial_reference(
    input logic clk,i_en,
    input logic signed [31:0] i_a,i_b,
    output logic [191:0] o_operands,
    output logic [176:0] o_partials
    );
    logic signed [31:0] operand_a,operand_b;
    ''' +(f'always_ff @(posedge clk) if(i_en) operand_a<=i_a;\n' if areg else 'assign operand_a=i_a;\n')+
     (f'always_ff @(posedge clk) if(i_en) operand_b<=i_b;\n' if breg else 'assign operand_b=i_b;\n')+'''
    logic [33:0] partial_0;
    logic signed [31:0] partial_1,partial_2;
    logic signed [29:0] partial_3;
    assign o_operands = {
      {3{operand_b[31]}},operand_b[31:17],
      1'b0,operand_b[16:0],
      {3{operand_b[31]}},operand_b[31:17],
      1'b0,operand_b[16:0],
      {15{operand_a[31]}},operand_a[31:17],
      {15{operand_a[31]}},operand_a[31:17],
      13'd0,operand_a[16:0],
      13'd0,operand_a[16:0]};
    always_ff @(posedge clk) begin
      if(i_en) begin
        partial_0 <= operand_a[16:0] * operand_b[16:0];
        partial_1 <= $signed({1'b0,operand_a[16:0]}) * $signed(operand_b[31:17]);
        partial_2 <= $signed(operand_a[31:17]) * $signed({1'b0,operand_b[16:0]});
        partial_3 <= $signed(operand_a[31:17]) * $signed(operand_b[31:17]);
      end
    end
    assign o_partials = {{13{partial_3[29]}},partial_3,
                        {11{partial_2[31]}},partial_2,
                        {11{partial_1[31]}},partial_1,14'd0,partial_0};
    endmodule
    ''')
     modules={}
     for label,path,top in [('reference',wrapper,'partial_reference'),('candidate',source,'registered_multiplier_s32')]:
      stem=prefix+'_'+label+'_elaborate'
      commands=['read_verilog -formal -sv -D VERIFIC '+str(path)+' '+str(model)]
      if label=='candidate': commands+=[f'chparam -set p_use_dsp 1 -set p_input_register {areg} -set p_b_input_register {breg} {top}']
      commands+=['prep -top '+top+' -flatten','wreduce','opt -full','write_json '+str(out/(stem+'.json'))]
      run(stem,commands)
      flattened=json.loads((out/(stem+'.json')).read_text())['modules']
      assert len(flattened)==1
      module=next(iter(flattened.values()))
      if label=='candidate':
       all_modules[(areg,breg)]=copy.deepcopy(module)
       module['ports'].pop('o_product')
       nets=module['netnames']
       operands=sum([nets[f'g_dsp.g_partial[{i}].u_multiply.u_dsp.{register}']['bits']
                     for register in ['Ar2','Br2'] for i in range(4)],[])
       partials=sum([nets[f'g_dsp.g_partial[{i}].u_multiply.u_dsp.'+('P' if i==0 else 'Mr')]['bits']
                     for i in range(4)],[])
       for name,bits in [('o_operands',operands),('o_partials',partials)]:
        module['ports'][name]={'direction':'output','bits':bits}
        module['netnames'][name]={'hide_name':0,'bits':bits,'attributes':{}}
      modules[label]=module
     input_result=None
     if areg or breg:
      inputs=copy.deepcopy(modules)
      for module in inputs.values():module['ports'].pop('o_partials')
      input_result=compare(prefix+'_inputs',inputs)
      for module in modules.values():
       a=module['ports']['i_a']['bits'];b=module['ports']['i_b']['bits']
       expected=(a[:17]+['0']*13+a[:17]+['0']*13+
                 a[17:]+[a[31]]*15+a[17:]+[a[31]]*15+
                 b[:17]+['0']+b[17:]+[b[31]]*3+
                 b[:17]+['0']+b[17:]+[b[31]]*3)
       mapping={}
       for old,new in zip(module['ports']['o_operands']['bits'],expected):
        if isinstance(old,int):
         assert old not in mapping or mapping[old]==new
         mapping[old]=new
        else:assert old==new
       primary={bit for port in module['ports'].values() if port['direction']=='input' for bit in port['bits']}
       removed=set()
       for name,cell in list(module['cells'].items()):
        q=cell['connections'].get('Q',[]) if 'dff' in cell['type'] else []
        if any(bit in mapping for bit in q):
         assert all(bit in mapping for bit in q)
         removed.update(q);del module['cells'][name]
       assert removed==set(mapping)-primary,(len(removed),len(set(mapping)-primary))
       for cell in module['cells'].values():
        for port,bits in cell['connections'].items():cell['connections'][port]=[mapping.get(bit,bit) for bit in bits]
       for net in module['netnames'].values():
        if any(bit in mapping for bit in net['bits']):net['attributes'].pop('init',None)
        net['bits']=[mapping.get(bit,bit) for bit in net['bits']]
       for port in module['ports'].values():port['bits']=[mapping.get(bit,bit) for bit in port['bits']]
     result=compare(prefix+'_partials',modules)
     result.update(areg=areg,breg=breg)
     if input_result:result['inputs']=input_result
     summary['partial_stages'].append(result)

    # 四个部分积已经证明，现在直接比较任意完整部分积组合的最终算术阶段。
    candidate=copy.deepcopy(all_modules[(1,1)])
    highest=max(bit for net in candidate['netnames'].values() for bit in net['bits'] if isinstance(bit,int))+1
    mapping={}
    for index,width in enumerate([34,32,32,30]):
     bits=list(range(highest,highest+width));highest+=width
     actual=candidate['netnames'][f'g_dsp.g_partial[{index}].u_multiply.u_dsp.'+('P' if index==0 else 'Mr')]['bits']
     expected=bits+(['0']*(len(actual)-width) if index==0 else [bits[-1]]*(len(actual)-width))
     for old,new in zip(actual,expected):
      if isinstance(old,int):
       assert old not in mapping or mapping[old]==new
       mapping[old]=new
      else: assert old==new,(index,old,new)
     name='partial_'+str(index)
     candidate['ports'][name]={'direction':'input','bits':bits}
     candidate['netnames'][name]={'hide_name':0,'bits':bits,'attributes':{}}
    removed=set()
    for name,cell in list(candidate['cells'].items()):
     q=cell['connections'].get('Q',[]) if 'dff' in cell['type'] else []
     if any(bit in mapping for bit in q):
      assert all(bit in mapping for bit in q),(name,len(q))
      removed.update(q);del candidate['cells'][name]
    assert removed==set(mapping),(len(removed),len(mapping))
    for cell in candidate['cells'].values():
     for port,bits in cell['connections'].items():cell['connections'][port]=[mapping.get(bit,bit) for bit in bits]
    for net in candidate['netnames'].values():
     if any(bit in mapping for bit in net['bits']):net['attributes'].pop('init',None)
     net['bits']=[mapping.get(bit,bit) for bit in net['bits']]
    for port in candidate['ports'].values():port['bits']=[mapping.get(bit,bit) for bit in port['bits']]
    reference=out/'arithmetic_reference.sv'
    reference.write_text('''module arithmetic_reference(
    input logic clk,i_en,
    input logic signed [31:0] i_a,i_b,
    input logic [33:0] partial_0,
    input logic signed [31:0] partial_1,partial_2,
    input logic signed [29:0] partial_3,
    output logic signed [63:0] o_product
    );
    logic signed [63:0] term_0,term_1,term_2,term_3,total;
    assign term_0 = {30'd0,partial_0};
    assign term_1 = {{32{partial_1[31]}},partial_1};
    assign term_2 = {{32{partial_2[31]}},partial_2};
    assign term_3 = {{34{partial_3[29]}},partial_3};
    assign total = term_0 + (term_1 <<< 17) + (term_2 <<< 17) + (term_3 <<< 34);
    always_ff @(posedge clk) if(i_en) o_product <= total;
    endmodule
    ''')
    run('arithmetic_reference_elaborate',['read_verilog -formal -sv '+str(reference),
        'prep -top arithmetic_reference -flatten','wreduce','opt -full',
        'write_json '+str(out/'arithmetic_reference.json')])
    ref=json.loads((out/'arithmetic_reference.json').read_text())['modules']['arithmetic_reference']
    summary['arithmetic']=compare('arithmetic',{'reference':ref,'candidate':candidate})
    summary['passed']=True
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=ROOT / 'rtl/npu/conv/vector_scalar_multiplier.sv')
    args = parser.parse_args()
    run_formal(args.source.resolve(), args.out.resolve())


if __name__ == '__main__':
    main()
