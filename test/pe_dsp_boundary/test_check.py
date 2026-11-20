#!/usr/bin/env python3
"""使用人工构造的 DSP 连接图验证检查程序；不表示器件测量结果。"""
import csv
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from check import inspect


def cell(row, column, *, breg=1, cascade=1, suffix='mac', mode='CASCADE'):
    return dict(name=f'u_array/gen_row[{row}].gen_col[{column}].ws_cell/{suffix}',
                b_input=mode, breg=breg, bcascreg=cascade, areg=1, acascreg=1, mreg=0, preg=0)


def connection(source, target, bit=0):
    port='BCIN' if target['b_input']=='CASCADE' else 'B'
    return dict(source=source['name'], target=target['name'], port=port,
                source_pin=source['name']+f'/BCOUT[{bit}]',
                target_pin=target['name']+f'/{port}[{bit}]')


class ConnectionChecks(unittest.TestCase):
    def test_registered_cross_pe_connections(self):
        cells=[cell(row,column) for row in range(2) for column in range(2)]
        result=inspect(cells,[connection(cells[0],cells[2])],2)
        self.assertTrue(result['passed'])
        self.assertEqual(result['longest_cross_pe_bypass'],0)

    def test_unregistered_cross_pe_connection(self):
        cells=[cell(row,column,breg=0,cascade=0) for row in range(2) for column in range(2)]
        result=inspect(cells,[connection(cells[0],cells[2])],2)
        self.assertFalse(result['passed'])
        self.assertEqual(result['longest_cross_pe_bypass'],1)

    def test_sixteen_row_combinational_broadcast(self):
        cells=[cell(row,column,breg=int(row==0),cascade=int(row==0))
               for row in range(16) for column in range(16)]
        edges=[connection(cells[row*16],cells[(row+1)*16]) for row in range(15)]
        result=inspect(cells,edges,16,8)
        self.assertFalse(result['passed'])
        self.assertEqual(result['longest_cross_pe_bypass'],15)

    def test_same_pe_combinational_connection(self):
        cells=[cell(0,0,breg=0,cascade=0,suffix='first'),
               cell(0,0,breg=0,cascade=0,suffix='second',mode='DIRECT')]
        result=inspect(cells,[connection(cells[0],cells[1])],1)
        self.assertTrue(result['passed'])
        self.assertEqual(result['longest_combinational_b_dsp_cells'],2)

    def test_combinational_b_cell_count_limit(self):
        cells=[cell(0,0,breg=0,cascade=0,suffix=f'unit{i}') for i in range(10)]
        edges=[connection(cells[i],cells[i+1]) for i in range(9)]
        result=inspect(cells,edges,1)
        self.assertEqual(result['longest_cross_pe_bypass'],0)
        self.assertEqual(result['longest_combinational_b_dsp_cells'],10)
        self.assertFalse(result['passed'])

    def test_per_bit_edges_count_once(self):
        cells=[cell(0,0),cell(0,0,breg=0,cascade=0,suffix='second')]
        result=inspect(cells,[connection(cells[0],cells[1],bit) for bit in range(18)],1)
        self.assertEqual(len(result['edges']),1)
        self.assertEqual(result['edges'][0]['connected_bits'],18)

    def test_registered_stage_ends_combinational_sequence(self):
        cells=[cell(row,column,breg=0,cascade=0) for row in range(3) for column in range(3)]
        cells[3]['breg']=1
        cells[3]['bcascreg']=1
        edges=[connection(cells[0],cells[3]),connection(cells[3],cells[6])]
        self.assertEqual(inspect(cells,edges,3,1)['longest_cross_pe_bypass'],1)

    def test_missing_pe_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'every computation cell'):
            inspect([cell(0,0)],[],2)

    def test_unsupported_register_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Invalid BREG'):
            inspect([cell(0,0,breg=1,cascade=0)],[],1)

    def test_unrecorded_driver_is_rejected(self):
        source=cell(0,0)
        target=cell(0,0,suffix='second')
        with self.assertRaisesRegex(ValueError,'unrecorded'):
            inspect([target],[connection(source,target)],1)

    def test_combinational_cycle_is_rejected(self):
        cells=[cell(0,0,breg=0,cascade=0,suffix='first'),
               cell(0,0,breg=0,cascade=0,suffix='second')]
        with self.assertRaisesRegex(ValueError,'contains a cycle'):
            inspect(cells,[connection(cells[0],cells[1]),connection(cells[1],cells[0])],1)

    @unittest.skipUnless(shutil.which('tclsh'),'Tcl interpreter unavailable')
    def test_tcl_collection_and_failure_status(self):
        helper=Path(__file__).resolve().with_name('check_vivado.tcl')
        for registered in (True,False):
            with self.subTest(registered=registered), tempfile.TemporaryDirectory(prefix='pe_dsp_check_') as temporary:
                out=Path(temporary)
                script=out/'mock.tcl'
                script.write_text('''
# 人工构造端口连接，只验证导出及错误处理，不执行器件综合。
set cells [list {u_array/gen_row[0].gen_col[0].ws_cell/mac} \
    {u_array/gen_row[0].gen_col[1].ws_cell/mac} \
    {u_array/gen_row[1].gen_col[0].ws_cell/mac} \
    {u_array/gen_row[1].gen_col[1].ws_cell/mac} other_dsp]
set target [lindex $cells 2]
set driver [lindex $cells 0]
set registered '''+str(int(registered))+'''
proc option {arguments name} {
    set index [lsearch -exact $arguments $name]
    return [lindex $arguments [expr {$index+1}]]
}
proc get_cells {args} {
    if {[lsearch -exact $args -of_objects]>=0} {
        return [file dirname [option $args -of_objects]]
    }
    return $::cells
}
proc get_property {property object} {
    if {$property eq "NAME"} { return $object }
    if {$property eq "REF_NAME"} { return DSP48E1 }
    if {$property eq "REF_PIN_NAME"} { return [file tail $object] }
    if {$property eq "B_INPUT"} { return CASCADE }
    if {$property in {BREG BCASCREG} && $object eq $::target} { return $::registered }
    if {$property in {BREG BCASCREG AREG ACASCREG}} { return 1 }
    if {$property in {MREG PREG}} { return 0 }
    error "Unknown modeled property $property"
}
proc get_pins {args} {
    set object [option $args -of_objects]
    if {[lsearch -exact $args -leaf]>=0} {
        return [list $::driver/BCOUT\\[0\\]]
    }
    if {$object eq $::target} { return [list $object/BCIN\\[0\\]] }
    return [list]
}
proc get_nets {args} { return [option $args -of_objects] }
source {'''+str(helper)+'''}
pe_dsp_boundary::check {'''+str(out)+'''} {u_array/*} 2 0
''')
                result=subprocess.run(['tclsh',str(script)],capture_output=True,text=True)
                self.assertEqual(result.returncode==0,registered,result.stdout+result.stderr)
                report=json.loads((out/'dsp_b_cascade.json').read_text())
                self.assertEqual(report['passed'],registered)
                self.assertEqual(report['pe_count'],4)
                self.assertEqual(report['all_dsp_count'],5)
                with (out/'all_dsp_cells.tsv').open() as stream:
                    self.assertEqual(len(list(csv.DictReader(stream,delimiter='\t'))),5)


if __name__=='__main__':
    unittest.main()
