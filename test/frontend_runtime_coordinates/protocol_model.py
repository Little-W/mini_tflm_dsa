"""从实际运行寄存器提取顺序选择条件，生成可检查的完整事件集合。"""
from __future__ import annotations

import re


def case_conditions(source):
    result = []
    for section in source.split("unique case (1'b1)")[1:]:
        section = section[:section.index('endcase')]
        conditions = re.findall(r'^ {8}((?:i_\w+|\()[^;]*?):', section, re.M)
        result.append([' '.join(value.split()) for value in conditions])
    if list(map(len, result)) != [29, 22]:
        raise ValueError('运行寄存器的两组事件集合需要重新检查')
    return result


def observation_logic(source, prefix=''):
    declarations = []
    for label, conditions in zip(('main', 'arithmetic'), case_conditions(source)):
        if prefix:
            conditions = [re.sub(r'\bi_(\w+)\b', prefix+r'i_\1', term) for term in conditions]
        width = len(conditions)
        name = 'formal_'+label+'_conditions'
        declarations += [f'logic [{width-1}:0] {name};',
                         f'assign {name} = {{'+',\n'.join('('+term+')' for term in conditions)+'};',
                         f'assign formal_{label}_unique = ({name} & ({name}-{width}\'(1))) == 0;']
    return '\n'.join(declarations)+'\n'


def observed_runtime(source):
    index = source.index('\n);')
    header = source[:index]
    header = re.sub(r'(\bo_word_valid)\s*//', r'\1, //', header)
    header += '''
  output logic formal_main_unique, // 配置、描述符及运行状态最多选择一个主过程。
  output logic formal_arithmetic_unique // 解码与地址计算最多选择一个保存过程。
'''
    result = header+source[index:]
    return result.replace('endmodule', observation_logic(source)+'\nendmodule', 1)
