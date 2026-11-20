#!/usr/bin/env python3
"""检查实际 LUT 函数、重复信号、组合反馈以及 DSP 选择的寄存边界。"""
import itertools
import random
import unittest

from lut_dependencies import lut_output_dependencies
from map_wide_alu import select_cells
from netlist_metrics import connected_paths
from open_fpga_synth import logic_depth


def cell(kind, inputs, outputs, parameters=None):
    return {'type':kind,'connections':{**inputs,**outputs},'parameters':parameters or {},
            'port_directions':{**{p:'input' for p in inputs},**{p:'output' for p in outputs}}}


def lut(kind, bindings, table, outputs=None):
    return cell(kind,{f'I{i}':[bit] for i,bit in enumerate(bindings)},
                outputs or {'O':[90]},{'INIT':table})


def flop(q, d='0'):
    return cell('FDRE',{'D':[d],'C':[100],'CE':['1'],'R':['0']},{'Q':[q]})


def alu(source, target):
    return cell('$alu',{'A':[source],'B':['0']*32},{'Y':[target]},{'Y_WIDTH':32})


def actual_pin_support(table, bindings):
    """独立枚举原语引脚地址，只保留满足常量与重复信号连接的地址。"""
    groups={bit:sum(1<<pin for pin,value in enumerate(bindings) if value==bit)
            for bit in bindings if isinstance(bit,int)}
    valid=[]
    for address in range(1<<len(bindings)):
        if any(isinstance(bit,str) and bit in ('0','1') and
               ((address>>pin)&1)!=int(bit) for pin,bit in enumerate(bindings)):
            continue
        if any(address&mask not in (0,mask) for mask in groups.values()):
            continue
        valid.append(address)
    return {bit for bit,mask in groups.items()
            if any(((table>>address)^(table>>(address^mask)))&1 for address in valid)}


class LutDependenciesTests(unittest.TestCase):
    def support(self, primitive, output='O'):
        return {bit for _,_,bit in lut_output_dependencies(primitive,output)}

    def test_all_two_and_three_input_functions_with_bindings(self):
        for width in (2,3):
            for table in range(1<<(1<<width)):
                for bindings in itertools.product((10,11,'0','1'),repeat=width):
                    actual=self.support(lut('LUT'+str(width),bindings,table))
                    self.assertEqual(actual,actual_pin_support(table,bindings),(width,table,bindings))

    def test_all_lut_widths_and_random_six_input_tables(self):
        randomizer=random.Random(5917)
        for width in range(1,7):
            for _ in range(100):
                table=randomizer.getrandbits(1<<width)
                bindings=tuple(randomizer.choice((10,11,12,13,'0','1','x')) for _ in range(width))
                self.assertEqual(self.support(lut('LUT'+str(width),bindings,table)),
                                 actual_pin_support(table,bindings))

    def test_admission_outputs_have_distinct_support(self):
        primitive=lut('LUT6_2',[10,11,12,13,14,'1'],0x8000000080008000,
                      {'O5':[20],'O6':[21]})
        self.assertEqual(self.support(primitive,'O5'),{10,11,12,13})
        self.assertEqual(self.support(primitive,'O6'),{10,11,12,13,14})

    def test_dual_outputs_share_inputs_and_respect_constant_i5(self):
        for select,expected in [('0',{10}),('1',{11}),(12,{10,11,12})]:
            primitive=lut('LUT6_2',[10,11,'0','0','0',select],0xCCCCCCCCAAAAAAAA,
                          {'O5':[20],'O6':[21]})
            self.assertEqual(self.support(primitive,'O5'),{10})
            self.assertEqual(self.support(primitive,'O6'),expected)

    def test_repeated_signal_cancellation_and_persistent_dependency(self):
        self.assertEqual(self.support(lut('LUT2',[10,10],0b0110)),set())
        self.assertEqual(self.support(lut('LUT2',[10,10],0b1000)),{10})
        self.assertEqual(self.support(lut('LUT2',[10,'0'],0b1000)),set())
        self.assertEqual(self.support(lut('LUT2',[10,'1'],0b1000)),{10})
        self.assertEqual(self.support(lut('LUT2',['1','1'],0b1000)),set())

    def test_unknown_values_retain_possible_dependencies(self):
        self.assertEqual(self.support(lut('LUT2',[10,'x'],0b1000)),{10})
        self.assertEqual(self.support(lut('LUT2',[10,11],'10x0')),{10,11})
        primitive=lut('LUT6_2',[10,11,'0','0','0',12],'x'*32+'10'*16,
                      {'O5':[20],'O6':[21]})
        self.assertEqual(self.support(primitive,'O5'),{10})
        self.assertEqual(self.support(primitive,'O6'),{10,11,12})

    def test_unknown_output_and_vector_pin_are_rejected(self):
        primitive=lut('LUT1',[10],2)
        with self.assertRaises(ValueError):lut_output_dependencies(primitive,'O5')
        primitive['connections']['I0']=[10,11]
        with self.assertRaises(ValueError):lut_output_dependencies(primitive,'O')


class LutGraphTests(unittest.TestCase):
    def admission(self, table=0x8000000080008000):
        cells={f'state{i}':flop(10+i) for i in range(4)}
        cells.update(pair=lut('LUT6_2',[10,11,12,13,22,'1'],table,{'O5':[20],'O6':[23]}),
                     calc_start=lut('LUT2',[20,24],8,{'O':[21]}),
                     admission_start=lut('LUT2',[21,25],8,{'O':[22]}),last=flop(26,23))
        return cells

    def test_admission_feedback_is_acyclic_in_all_consumers(self):
        cells=self.admission()
        self.assertEqual(select_cells({'cells':cells},0)['additional_dsp_cells'],0)
        self.assertEqual([row['cell'] for row in logic_depth(cells)],
                         ['pair','calc_start','admission_start','pair'])
        paths=connected_paths({'cells':cells})
        self.assertTrue(paths['graph_complete'])
        self.assertEqual(paths['longest_register_path_cells'],4)

    def test_actual_lut_feedback_is_detected_in_all_consumers(self):
        cells=self.admission(0x8000000080000000)
        with self.assertRaisesRegex(ValueError,'Combinational cycle'):select_cells({'cells':cells},0)
        with self.assertRaisesRegex(RuntimeError,'Combinational cycle'):logic_depth(cells)
        paths=connected_paths({'cells':cells})
        self.assertFalse(paths['graph_complete'])
        self.assertTrue(paths['combinational_cycle_nodes'])

    def test_dual_output_dsp_dependencies_remain_separate(self):
        cells={'a':alu(1,2),
               'pair':lut('LUT6_2',[10,11,12,13,2,'1'],0x8000000080008000,
                          {'O5':[3],'O6':[4]}),'b':alu(3,5),'c':alu(4,6)}
        report=select_cells({'cells':cells},10)
        self.assertEqual([row['cell'] for row in report['selected']],['a','b'])

    def test_existing_dsp_blocks_only_dependent_lut_output(self):
        cells={'dsp':cell('DSP48E1',{'A':[1]},{'P':[2]},{'PREG':0}),
               'pair':lut('LUT6_2',[10,11,12,13,2,'1'],0x8000000080008000,
                          {'O5':[3],'O6':[4]}),'b':alu(3,5),'c':alu(4,6)}
        report=select_cells({'cells':cells},10)
        self.assertEqual([row['cell'] for row in report['selected']],['b'])
        self.assertEqual(report['blocked_by_existing_combinational_dsp'],['c'])

    def test_constant_and_repeated_signal_paths_preserve_dsp_limit(self):
        for table,bindings,expected in [(8,[2,'0'],2),(6,[2,2],2),(8,[2,2],1)]:
            cells={'a':alu(1,2),'logic':lut('LUT2',bindings,table,{'O':[3]}),'b':alu(3,4)}
            self.assertEqual(select_cells({'cells':cells},10)['additional_dsp_cells'],expected)

    def test_two_dsp_limit_through_actual_lut_function(self):
        cells={'a':alu(1,2),'logic':lut('LUT2',[2,2],8,{'O':[3]}),
               'b':alu(3,4),'c':alu(4,5)}
        report=select_cells({'cells':cells},10,maximum_chain=2)
        self.assertEqual(report['additional_dsp_cells'],2)
        self.assertEqual(report['selected_combinational_dsp_upper_bound'],2)


if __name__=='__main__':unittest.main()
