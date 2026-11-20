#!/usr/bin/env python3
"""实际选择和改写 JSON，再导入 Yosys 比较各算术单元的完整输出。"""
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
HERE = Path(__file__).resolve().parent
PARAMETERS = ('A_WIDTH','B_WIDTH','Y_WIDTH','A_SIGNED','B_SIGNED')


def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as source:
        while block:=source.read(1024*1024):
            value.update(block)
    return value.hexdigest()


def integer(value):
    return int(value,2) if isinstance(value,str) else value


def make_module(configs, polarities=None, dependency=False, repeated=False):
    """每项保留完整公开输入输出，连接编号同时用于原设计和改写后的设计。"""
    module={'attributes':{},'ports':{},'cells':{},'netnames':{}}
    next_bit=2
    def port(name,width,direction):
        nonlocal next_bit
        bits=list(range(next_bit,next_bit+width));next_bit+=width
        module['ports'][name]={'direction':direction,'bits':bits}
        module['netnames'][name]={'hide_name':0,'bits':bits,'attributes':{}}
        return bits
    polarity_bits={}
    polarities=polarities or ['shared']*len(configs)
    for index,(config,polarity) in enumerate(zip(configs,polarities)):
        a,b,width,sa,sb=config
        if polarity in ('0','1'):
            invert=[polarity]
        else:
            if polarity not in polarity_bits:
                polarity_bits[polarity]=port('BI_'+polarity,1,'input')
            invert=polarity_bits[polarity]
        connections={'A':port('A'+str(index),a,'input'),'B':port('B'+str(index),b,'input'),
                     'CI':port('CI'+str(index),1,'input'),'BI':invert,
                     'X':port('X'+str(index),width,'output'),'Y':port('Y'+str(index),width,'output'),
                     'CO':port('CO'+str(index),width,'output')}
        if repeated:
            connections['A']=[connections['A'][i//2] for i in range(a)]
            connections['B']=connections['B'][:]
            connections['B'][0]='1'
            if b>1:
                connections['B'][-1]='0'
        if dependency and index==1:
            prior=module['cells']['alu0']['connections']['Y']
            connections['A']=prior[:a]+['0']*max(0,a-len(prior))
        module['cells']['alu'+str(index)]={
            'hide_name':0,'type':'$alu',
            'parameters':{name:format(value,'032b') for name,value in zip(PARAMETERS,config)},
            'attributes':{},'port_directions':{name:'input' if name in ('A','B','CI','BI') else 'output'
                                               for name in connections},'connections':connections}
    # 未使用的公开信号也占据编号，改写时的补位必须使用独立新编号。
    module['netnames']['reserved_signal']={'hide_name':0,'bits':[next_bit+1000],'attributes':{}}
    return module


def cases():
    mixed=[(3,7,10,1,1),(13,17,6,0,0),(9,2,4,1,1),(2,8,7,0,0)]
    empty_unsigned=[(0,7,10,0,0),(8,0,7,0,0),(0,0,1,0,0),(0,15,8,0,0)]
    empty_signed=[(0,7,10,1,1),(8,0,7,1,1),(0,0,9,1,1),(15,0,8,1,1)]
    return [
        ('mixed',mixed,1,0,None,False,False,4),
        ('empty_unsigned',empty_unsigned,1,0,None,False,False,4),
        ('empty_signed',empty_signed,1,0,None,False,False,4),
        ('widths1_4',[(w,w,w,0,0) for w in (1,2,3,4)],1,0,None,False,False,4),
        ('widths5_8',[(w,w,w,1,1) for w in (5,6,7,8)],1,0,None,False,False,4),
        ('widths9_10',[(1,3,9,1,1),(3,1,10,0,0),(12,7,9,1,1),(10,10,10,1,1)],1,0,None,False,False,4),
        ('partial_two',mixed[:2],1,0,None,False,False,2),
        ('partial_three',mixed[:3],1,0,None,False,False,3),
        ('single',[(13,11,7,1,1)],1,0,None,False,False,1),
        ('five_cells',mixed+[(1,1,2,1,1)],2,0,None,False,False,5),
        ('limited_budget',mixed+[(1,1,2,1,1),(4,7,5,0,0)],1,0,None,False,False,4),
        ('zero_budget',mixed,0,0,None,False,False,0),
        ('reserved_budget',mixed+[(1,1,2,1,1),(4,7,5,0,0)],2,1,None,False,False,4),
        ('distinct_polarities',mixed*2,2,0,['first']*4+['second']*4,False,False,8),
        ('constant_polarities',mixed,2,0,['0','0','1','1'],False,False,4),
        ('wide_and_small',[(17,13,32,1,1)]+mixed,2,0,None,False,False,5),
        ('dependent_cells',[(8,8,8,0,0)]*4,1,0,None,True,False,3),
        ('constant_and_repeated',mixed,1,0,None,False,True,4),
    ]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--mapper',type=Path,default=ROOT/'scripts/fpga/map_wide_alu.py')
    parser.add_argument('--selection',type=Path)
    parser.add_argument('--selected-netlist',type=Path)
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    if bool(args.selection)!=bool(args.selected_netlist):
        parser.error('--selection 与 --selected-netlist 必须同时提供')
    snapshot=out/'mapper';snapshot.mkdir(exist_ok=True)
    for name in ('map_wide_alu.py','lut_dependencies.py'):
        (snapshot/name).write_bytes((args.mapper.resolve().parent/name).read_bytes())
    sys.path.insert(0,str(snapshot))
    spec=importlib.util.spec_from_file_location('tested_alu_mapper',snapshot/'map_wide_alu.py')
    mapper=importlib.util.module_from_spec(spec);spec.loader.exec_module(mapper)
    import pyosys
    share=Path(pyosys.__file__).parent/'share'
    library=share/'xilinx/cells_sim.v'
    dsp=re.search(r'^module DSP48E1\b.*?^endmodule',library.read_text(),re.M|re.S)[0]
    dsp=re.sub(r'\bspecify\b.*?\bendspecify\b','',dsp,flags=re.S)
    models=out/'official_models.sv';models.write_text(dsp+'\n')
    helpers=[ROOT/'scripts/fpga/techmap'/name for name in ('wide_alu_dsp.sv','fpga_dsp_alu4.sv')]
    summary={'method':'select_cells、apply_mapping、JSON 导入及实际 techmap 后的完整输出 SAT',
             'mapper_sha256':digest(snapshot/'map_wide_alu.py'),
             'dependency_analyzer_sha256':digest(snapshot/'lut_dependencies.py'),
             'source_sha256':{str(path.relative_to(ROOT)):digest(path) for path in [Path(__file__).resolve(),*helpers]},
             'primitive_library_sha256':digest(library),'reference_model':'Yosys 内建 $alu SAT 模型',
             'runs':[]}
    workloads=cases()
    selected_shapes={}
    if args.selection:
        selection=json.loads(args.selection.read_text())
        if selection['input_sha256']!=digest(args.selected_netlist):
            raise RuntimeError('选择报告与输入网表摘要不同')
        groups=selection['small_alu_packing']['groups']
        for index,group in enumerate(groups):
            shape=tuple(tuple(integer(lane['parameters'][key]) for key in PARAMETERS) for lane in group['lanes'])
            if len(shape)!=len(group['cells']) or not 2<=len(shape)<=4:
                raise RuntimeError('实际分组参数不完整')
            selected_shapes.setdefault(shape,[]).append(index)
        for index,shape in enumerate(selected_shapes):
            workloads.append(('selected_'+str(index),list(shape),1,0,None,False,False,len(shape)))
        summary['production_selection']={
            'selection_sha256':digest(args.selection),'input_netlist_sha256':selection['input_sha256'],
            'groups':len(groups),'members':sum(len(group['cells']) for group in groups),
            'parameter_shapes':len(selected_shapes),'resulting_dsp_cells':selection['resulting_dsp_cells'],
            'additional_dsp_cells':selection['additional_dsp_cells'],
            'shape_groups':[{'shape':shape,'groups':indices} for shape,indices in selected_shapes.items()]}
    for name,configs,budget,reserve,polarity,dependency,repeated,expected_count in workloads:
        folder=out/name;folder.mkdir(exist_ok=True)
        original=make_module(configs,polarity,dependency,repeated)
        current=copy.deepcopy(original)
        report=mapper.select_cells(current,budget,reserve=reserve,minimum_width=1,pack_small_alu=True)
        assert len(report['selected'])==expected_count,(name,report)
        assert report['resulting_dsp_cells']+reserve<=budget
        if dependency:
            assert not {'alu0','alu1'}<={item['cell'] for item in report['selected']}
        mapper.apply_mapping(current,report)
        markers=[cell for cell in current['cells'].values() if cell['type'] in ('$__FPGA_DSP_ALU','$__FPGA_DSP_ALU4')]
        assert len(markers)==report['additional_dsp_cells']
        assert original['ports']==current['ports']
        paths=[]
        for label,module in (('reference',original),('current',current)):
            path=folder/(label+'.json');design={'modules':{'alu_group':module}}
            path.write_text(json.dumps(design,indent=2)+'\n');paths.append(path)
            path.with_suffix('.autoidx.il').write_text('autoidx '+str(mapper.next_autoidx(design))+'\n')
        (folder/'selection.json').write_text(json.dumps(report,indent=2)+'\n')
        script=folder/'formal.ys';commands=[]
        for label,path in zip(('reference','current'),paths):
            commands += ['read_json '+shlex.quote(str(path)),
                         'read_rtlil '+shlex.quote(str(path.with_suffix('.autoidx.il')))]
            if label=='current':
                commands += ['verilog_defaults -push','verilog_defaults -add -sv']
                commands += ['techmap -map '+shlex.quote(str(helper)) for helper in helpers]
                commands += ['verilog_defaults -pop','opt_clean',
                             'write_json '+shlex.quote(str(folder/'mapped.json'))]
            commands += ['read_verilog -sv -D VERIFIC '+shlex.quote(str(models)),
                         'prep -top alu_group -flatten','check -assert',
                         'rename alu_group '+label,'design -stash '+label]
        commands += ['design -copy-from reference -as reference reference','design -copy-from current -as current current',
                     'miter -equiv -make_assert reference current comparison','prep -top comparison -flatten',
                     'chformal -lower','opt -full','check -assert',
                     'sat -prove-asserts -verify -set-def-inputs -show-inputs -show-outputs']
        script.write_text('\n'.join(commands)+'\n');log=folder/'formal.log'
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                           cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise RuntimeError('完整输出比较未完成：'+name)
        mapped=json.loads((folder/'mapped.json').read_text())['modules']['alu_group']['cells']
        actual_dsp=sum(cell['type']=='DSP48E1' for cell in mapped.values())
        assert actual_dsp==report['additional_dsp_cells'],(name,actual_dsp,report['additional_dsp_cells'])
        assert all(cell['type'] not in ('$__FPGA_DSP_ALU','$__FPGA_DSP_ALU4') for cell in mapped.values())
        item={'name':name,'passed':True,'configurations':configs,'budget':budget,'reserve':reserve,
              'selected_cells':len(report['selected']),'packed_groups':len(report['small_alu_packing']['groups']),
              'actual_dsp_cells':actual_dsp,'compared_output_bits':sum(3*config[2] for config in configs),
              'independent_carry_inputs':len(configs),'shared_variable_BI':polarity is None,
              'log_sha256':digest(log),'input_json_sha256':digest(paths[0]),'mapped_json_sha256':digest(folder/'mapped.json')}
        summary['runs'].append(item);print(json.dumps(item),flush=True)
    summary['passed']=True
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'passed':True,'runs':len(summary['runs']),'production_shapes':len(selected_shapes)}),flush=True)


if __name__=='__main__':
    main()
