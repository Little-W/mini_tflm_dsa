#!/usr/bin/env python3
"""比较真实寄存器的完整一步状态转移及所有公开输出。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

SUPPORTED = {'$dff','$dffe','$adff','$adffe','$sdff','$sdffe','$sdffce','$ff'}


def state_sources(module):
    """保存每个真实状态位所属的寄存器、位序及初始值。"""
    states={}
    for name,cell in module['cells'].items():
        if cell['type'] in SUPPORTED:
            for index,bit in enumerate(cell['connections']['Q']):
                if isinstance(bit,int):
                    if bit in states:
                        raise RuntimeError('状态输出存在多个驱动')
                    states[bit]=(name,cell,index)
        elif re.search('ff|latch|mem',cell['type'],re.I):
            raise RuntimeError('存在尚未展开的时序或存储单元：'+cell['type'])
    initial={}
    for wire in module['netnames'].values():
        value=wire.get('attributes',{}).get('init')
        if value is None:
            continue
        if not isinstance(value,str) or len(value)!=len(wire['bits']):
            raise RuntimeError('寄存器初始值宽度不完整')
        for bit,entry in zip(wire['bits'],reversed(value)):
            if bit in states:
                if bit in initial and initial[bit]!=entry:
                    raise RuntimeError('同一状态位的初始值不一致')
                initial[bit]=entry
    return states,initial


def prove(folder,worker):
    """相同任意当前状态下，实际状态更新及输出相等即构成一步归纳关系。"""
    folder=Path(folder)
    modules={label:json.loads((folder/(label+'_state.json')).read_text())['modules'][label]
             for label in ('reference','current')}
    state_data={label:state_sources(module) for label,module in modules.items()}
    states={label:item[0] for label,item in state_data.items()}
    initial={label:item[1] for label,item in state_data.items()}
    correspondence,inverse,names={},{},{}
    for name,net in modules['reference']['netnames'].items():
        other=modules['current']['netnames'].get(name)
        if other is None or len(net['bits'])!=len(other['bits']):
            continue
        for index,(old,new) in enumerate(zip(net['bits'],other['bits'])):
            if old in states['reference'] and new in states['current']:
                if correspondence.get(old,new)!=new or inverse.get(new,old)!=old:
                    raise RuntimeError('真实寄存器的状态对应不是一一映射')
                correspondence[old]=new;inverse[new]=old
                names.setdefault(old,f'{name}[{index}]')
    if len(correspondence)!=len(states['reference']) or len(correspondence)!=len(states['current']):
        raise RuntimeError('存在未参与比较的真实寄存器状态位')
    order=sorted(correspondence)
    observed={label:[] for label in modules}
    layout=[]
    for old in order:
        new=correspondence[old]
        cells={label:states[label][bit] for label,bit in (('reference',old),('current',new))}
        metadata={}
        for label,(_,cell,index) in cells.items():
            parameters={key:value for key,value in cell['parameters'].items()
                        if key not in ('WIDTH','ARST_VALUE','SRST_VALUE')}
            for key in ('ARST_VALUE','SRST_VALUE'):
                if key in cell['parameters']:
                    parameters[key]=cell['parameters'][key][-1-index]
            metadata[label]=(cell['type'],parameters,sorted(cell['connections']))
            for port,bits in sorted(cell['connections'].items()):
                if port!='Q':
                    observed[label].append(bits[index] if port=='D' else bits[0])
        if metadata['reference']!=metadata['current']:
            raise RuntimeError('寄存器类型、极性或逐位复位值不同：'+names[old])
        if initial['reference'].get(old,'x')!=initial['current'].get(new,'x'):
            raise RuntimeError('寄存器初始值不同：'+names[old])
        layout.append(dict(state=names[old],type=metadata['reference'][0],
                           observed_ports=[port for port in metadata['reference'][2] if port!='Q']))
    for label,module in modules.items():
        for name in {entry[0] for entry in states[label].values()}:
            del module['cells'][name]
        module['ports']['equiv_state']={'direction':'input','bits':
            order if label=='reference' else [correspondence[bit] for bit in order]}
        module['ports']['equiv_transition']={'direction':'output','bits':observed[label]}
        (folder/(label+'_transition.json')).write_text(json.dumps({'modules':{label:module}})+'\n')
    result=worker(['read_json '+str(folder/'reference_transition.json'),
                   'read_json '+str(folder/'current_transition.json'),
                   'miter -equiv -flatten -make_assert reference current transition_proof',
                   'hierarchy -top transition_proof','opt -full','check -assert',
                   'sat -verify -prove-asserts'],folder,'transition')
    if 'SUCCESS!' not in result:
        raise RuntimeError('完整状态转移与公开输出未证明相等')
    layout_file=folder/'state_correspondence.json'
    layout_file.write_text(json.dumps(layout,ensure_ascii=False,separators=(',',':'))+'\n')
    return dict(passed=True,real_state_bits=len(order),state_update_and_control_bits=len(observed['reference']),
                all_public_outputs=True,all_current_states_arbitrary=True,external_input_assumptions=[],
                register_types_and_reset_parameters_equal=True,initial_values_equal=True,
                state_correspondence_sha256=hashlib.sha256(layout_file.read_bytes()).hexdigest(),
                proof_sha256=hashlib.sha256((folder/'transition.log').read_bytes()).hexdigest(),
                method='实际寄存器的一步状态转移等价；比较全部数据、时钟、复位、使能输入及公开输出')
