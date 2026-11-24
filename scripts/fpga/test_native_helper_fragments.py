#!/usr/bin/env python3
"""Check exact native helper extraction from files containing typed parents."""
import hashlib
import unittest

from open_fpga_synth import native_helper_module_fragments, native_terminal_function_assignments


class NativeHelperFragmentsTests(unittest.TestCase):
    def test_module_attributes_and_bodies_are_copied_verbatim(self):
        helper = '''(* keep_hierarchy = "yes" *)
(* keep = 1 *)
module selected #(parameter int p_width=3)(
 input logic[p_width-1:0] i_data, output logic o_data);
 // module ignored; endmodule
 initial $display("endmodule module");
 assign o_data = &i_data;
endmodule : selected'''
        source = ('package typed; typedef logic[2:0] item_t; endpackage\n'
                  'module parent(input typed::item_t i_data); endmodule\n' + helper + '\n')
        fragment, records = native_helper_module_fragments(source, ('selected',))
        self.assertEqual(fragment, '`default_nettype none\n' + helper + '\n`default_nettype wire\n')
        record = records['selected']
        self.assertEqual(source[record['character_start']:record['character_stop']], helper)
        self.assertEqual(record['sha256'], hashlib.sha256(helper.encode()).hexdigest())
        self.assertEqual(record['line_start'], 3)

    def test_all_recursive_definitions_are_retained(self):
        source = '''module leaf(input logic a,output logic y);assign y=a;endmodule
module tree #(parameter int N=2)(input logic[N-1:0] a,output logic y);
if(N==1)leaf u_leaf(a,y);else tree #(N-1)u_rest(a[N-2:0],y);
endmodule
module unused;endmodule
'''
        fragment, records = native_helper_module_fragments(source, ('leaf', 'tree'))
        self.assertEqual(set(records), {'leaf', 'tree'})
        self.assertIn('tree #(N-1)u_rest', fragment)
        self.assertNotIn('module unused', fragment)

    def test_incomplete_or_context_dependent_sources_are_rejected(self):
        for source in ('module a;', 'module a;endmodule module a;endmodule',
                       'module a;module b;endmodule endmodule', 'endmodule',
                       'module a(input pkg::value_t x);endmodule',
                       'module a;assign x=`VALUE;endmodule',
                       'module a;endmodule : other'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                native_helper_module_fragments(source, ('a',))
        with self.assertRaisesRegex(ValueError, 'Missing native helper'):
            native_helper_module_fragments('module a;endmodule', ('missing',))

    def test_terminal_return_preserves_the_function_result(self):
        source = '''function automatic logic [p_width-1:0] combine(input logic [p_count-1:0][p_width-1:0] values);
      logic [p_width-1:0] result;
      result = '0;
      for (int item = 0; item < p_count; item++) result |= values[item];
      return result;
    endfunction'''
        converted, replacements = native_terminal_function_assignments(source)
        self.assertEqual(converted, source.replace('return result;', 'combine = result;'))
        self.assertEqual(replacements, [dict(function='combine', source_statement='return result;',
            native_statement='combine = result;', source_function_sha256=hashlib.sha256(source.encode()).hexdigest(),
            native_function_sha256=hashlib.sha256(converted.encode()).hexdigest())])
        with self.assertRaisesRegex(ValueError, 'function text differs'):
            native_terminal_function_assignments(source.replace("result = '0", "result = '1"))
        for body in ('if(value) return value;return result;', 'return result;result=value;'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                native_terminal_function_assignments(
                    'function automatic logic f(input logic value);' + body + 'endfunction')


if __name__ == '__main__':
    unittest.main()
