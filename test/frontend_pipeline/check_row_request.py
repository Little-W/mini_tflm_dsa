#!/usr/bin/env python3
"""证明两步行请求候选，并测量实际寄存模块的 xc7 组合级数。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import shlex
import subprocess
import sys
import four_state_coverage as coverage

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'rtl/npu/conv/conv_im2col_row_request.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(script, log):
    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=240)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--skip-mapping', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_text = SOURCE.read_text()
    start = source_text.index('    // 三种两步位置各自完成地址与边界运算')
    end = source_text.index('    assign context_valid =', start)
    arithmetic = source_text[start:end]
    proof = out / 'row_comparison.sv'
    proof.write_text('''// 两次独立的光栅位置推进作为算术参考。
module row_comparison #(parameter int p_coord_width=35)(
  input wire conv_im2col_pkg::conv_cfg_t i_configuration,
  input wire logic [15:0] i_output_x,
  input wire logic [31:0] i_base_address, i_base_pixel,
  input wire logic [1:0][p_coord_width-1:0] i_base_coordinate,
  input wire logic signed [32:0] i_wrap_dx, i_wrap_pixels,
  input wire logic [31:0] i_step_bytes, i_wrap_bytes,
  output logic o_equivalent
);
  logic [31:0] pair_bytes_q, pair_pixels_q;
  logic [31:0] double_address, double_pixel;
  logic [1:0][p_coord_width-1:0] double_coordinate;
  logic [1:0] coordinate_valid;
  logic wraps_once, wraps_twice, i_row_wrap;
  logic [15:0] i_second_last_x;
  logic signed [32:0] i_pair_dx;
  logic signed [p_coord_width:0] full_pair_dx;
  assign pair_bytes_q = i_wrap_bytes + i_step_bytes;
  assign pair_pixels_q = 32'(i_wrap_pixels) + 32'(i_configuration.stride_w);
  assign full_pair_dx = (p_coord_width+1)'(i_wrap_dx) +
      $signed((p_coord_width+1)'(i_configuration.stride_w));
  assign i_pair_dx = 33'(full_pair_dx);
  assign i_second_last_x = i_configuration.output_w - 16'd2;
  assign i_row_wrap = i_output_x == i_configuration.output_w - 16'd1;
'''+arithmetic+'''
  logic [31:0] reference_address, reference_pixel;
  logic [1:0][p_coord_width-1:0] reference_coordinate;
  logic [15:0] reference_x;
  logic reference_padding, configuration_valid;
  always_comb begin
    reference_address = i_base_address;
    reference_pixel = i_base_pixel;
    reference_coordinate = i_base_coordinate;
    reference_x = i_output_x;
    for (int step=0;step<2;step++) begin
      if (reference_x == i_configuration.output_w - 16'd1) begin
        reference_x = 16'd0;
        reference_address = reference_address + i_wrap_bytes;
        reference_pixel = reference_pixel + 32'(i_wrap_pixels);
        reference_coordinate[0] = reference_coordinate[0] + p_coord_width'(i_wrap_dx);
        reference_coordinate[1] = reference_coordinate[1] + p_coord_width'(i_configuration.stride_h);
      end else begin
        reference_x = reference_x + 16'd1;
        reference_address = reference_address + i_step_bytes;
        reference_pixel = reference_pixel + 32'(i_configuration.stride_w);
        reference_coordinate[0] = reference_coordinate[0] + p_coord_width'(i_configuration.stride_w);
      end
    end
    reference_padding = !(reference_coordinate[0] < p_coord_width'(i_configuration.input_w) &&
                          reference_coordinate[1] < p_coord_width'(i_configuration.input_h));
    configuration_valid = i_configuration.output_w != 0 && i_output_x < i_configuration.output_w &&
        full_pair_dx == (p_coord_width+1)'(i_pair_dx);
    o_equivalent = !configuration_valid ||
        (double_address == reference_address && double_pixel == reference_pixel &&
         double_coordinate == reference_coordinate && !(\u0026coordinate_valid) == reference_padding);
  end
endmodule
''')
    resolver = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))
    sources = resolver['with_dependencies']([proof], ROOT)
    tracked = [SOURCE, *resolver['input_files'](sources, ROOT)]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in tracked if path.is_relative_to(ROOT)}
    results = []
    for width in (33, 35, 40):
        script, log = out/f'coordinate_{width}.ys', out/f'coordinate_{width}.log'
        script.write_text(shlex.join(['read_slang', '--top', 'row_comparison', '-DSYNTHESIS=1',
                          f'-Gp_coord_width={width}', *map(str, sources)])+
                          '\nprep -top row_comparison -flatten\nsat -verify -prove o_equivalent 1\n')
        execute(script, log)
        if 'SUCCESS!' not in log.read_text():
            raise RuntimeError('两步行请求候选形式证明未完成')
        results.append(dict(coordinate_width=width, passed=True, log_sha256=digest(log)))
        print(f'ROW_REQUEST_FORMAL_PASS width={width}', flush=True)
    ports = []
    for line in source_text.splitlines():
        match = re.match(r'\s*(input|output) (?:wire )?(.+?)\s+([io]_\w+),?\s*//', line)
        if match:
            ports.append(match.groups())
    reference = ROOT/'test/frontend_pipeline/row_request_reference.sv'
    if digest(reference) != '6765584076395e4b1f54143f2346ec940916f84594de917b47f020ba37886bfa':
        raise RuntimeError('行请求寄存器参考内容与记录不同')
    bench = out/'row_four_state.sv'
    inputs = [(kind, name) for direction, kind, name in ports if direction == 'input']
    outputs = [(kind, name) for direction, kind, name in ports if direction == 'output']
    names = ','.join(name for kind, name in inputs if name not in ('i_clk', 'i_rst_n'))
    declarations = '\n'.join(kind+' '+name+';' for kind, name in inputs)
    declarations += '\n'+'\n'.join(kind+' '+prefix+name+';' for prefix in ('actual_', 'reference_')
                                    for kind, name in outputs)
    widths=coverage.expanded_widths(out,'localparam int p_coord_width=35;',
        '\n'.join(kind+' '+name+';' for kind,name in inputs),
        [name for kind,name in inputs if name not in ('i_clk','i_rst_n')],
        [ROOT/'rtl/npu/conv/conv_im2col_pkg.sv'])
    input_width=sum(widths.values())
    connections = ','.join('.'+name+'('+name+')' for kind, name in inputs)
    instances = '\n'.join(module+' #(.p_coord_width(p_coord_width)) u_'+prefix+'('+connections+','+
                           ','.join('.'+name+'('+prefix+name+')' for kind, name in outputs)+');'
                           for module, prefix in [('conv_im2col_row_request','actual_'),
                               ('conv_im2col_row_request_reference','reference_')])
    comparisons = ' || '.join('actual_'+name+' !== reference_'+name for kind, name in outputs)
    bench.write_text('module row_four_state;\nlocalparam int p_coord_width=35;\n'+declarations+'\n'+
        'localparam int p_inputs='+str(input_width)+';\nlogic [p_inputs-1:0] stimulus;\n'+
        'assign {'+names+'}=stimulus;\n'+instances+"""
integer random_state=32'h42950137;
function automatic integer random_word;
  random_state=random_state^(random_state<<13);
  random_state=random_state^(random_state>>17);
  random_state=random_state^(random_state<<5);
  return random_state;
endfunction
initial begin
  i_clk=0;i_rst_n=0;stimulus='0;#1;i_clk=1;#1;i_clk=0;i_rst_n=1;
  for(integer sample=0;sample<8192;sample++)begin
    for(integer index=0;index<p_inputs;index++)stimulus[index]=1'(random_word());
    case(sample%16)
      0:stimulus='0;
      1:stimulus='1;
      2:stimulus='x;
      3:stimulus='z;
      4,5,6,7:stimulus[sample%p_inputs]=1'bx;
      8,9,10,11:stimulus[sample%p_inputs]=1'bz;
      default:begin end
    endcase
    #1;i_clk=1;#1;
    if("""+comparisons+""")$fatal(1,"row request four-state mismatch sample=%0d",sample);
    i_clk=0;#1;
  end
  $display("ROW_REQUEST_FOUR_STATE_PASS samples=8192");$finish;
end
endmodule
""")
    tb=bench.read_text()
    tb=tb.replace('initial begin',coverage.declarations('p_inputs')+'initial begin'+coverage.initialize('p_inputs',names),1)
    tb=tb.replace('    #1;i_clk=1;',coverage.sample('p_inputs')+'    #1;i_clk=1;',1)
    tb=tb.replace('  $display("ROW_REQUEST_FOUR_STATE_PASS',coverage.finish('p_inputs')+'  $display("ROW_REQUEST_FOUR_STATE_PASS',1)
    bench.write_text(tb)
    four_sources = resolver['with_dependencies']([SOURCE, reference, bench], ROOT)
    four_log, binary = out/'four_state.log', out/'four_state.vvp'
    with four_log.open('w') as stream:
        subprocess.run(['iverilog','-g2012','-s','row_four_state','-o',str(binary),*map(str,four_sources)],
                       stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
        subprocess.run(['vvp',str(binary)], stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=180)
    if 'ROW_REQUEST_FOUR_STATE_PASS' not in four_log.read_text():
        raise RuntimeError('行请求寄存器四态比较未完成')
    for path in resolver['input_files'](four_sources, ROOT):
        if path.is_relative_to(ROOT):
            hashes[str(path.relative_to(ROOT))] = digest(path)
    print('ROW_REQUEST_FOUR_STATE_PASS samples=8192', flush=True)
    report = dict(passed=True, formal=results, four_state_samples=8192,four_state_coverage=coverage.result(four_log,widths),
                  four_state_log_sha256=digest(four_log), source_sha256=hashes)

    if not args.skip_mapping:
        ports = []
        for line in source_text.splitlines():
            match = re.match(r'\s*(input|output) (?:wire )?(.+?)\s+([io]_\w+),?\s*//', line)
            if match:
                ports.append(match.groups())
        model = out/'registered_row_request.sv'
        declarations = ',\n'.join(direction+' '+kind+' '+name for direction, kind, name in ports)
        internals = '\n'.join(kind+' saved_'+name+';' for direction, kind, name in ports
                              if direction == 'input' and name != 'i_clk')
        internals += '\n'+'\n'.join(kind+' result_'+name+';' for direction, kind, name in ports
                                    if direction == 'output')
        assignments = '\n'.join('  saved_'+name+' <= '+name+';' if direction == 'input' else
                                 '  '+name+' <= result_'+name+';'
                                 for direction, kind, name in ports if name != 'i_clk')
        connections = ',\n'.join('.'+name+'('+('i_clk' if name=='i_clk' else
                                  ('saved_' if direction=='input' else 'result_')+name)+')'
                                  for direction, kind, name in ports)
        model.write_text('module registered_row_request #(parameter int p_coord_width=35)(\n'+
                         declarations+'\n);\n'+internals+'\nalways_ff @(posedge i_clk) begin\n'+
                         assignments+'\nend\nconv_im2col_row_request #(.p_coord_width(p_coord_width)) u_candidate(\n'+
                         connections+'\n);\nendmodule\n')
        sources = resolver['with_dependencies']([SOURCE, model], ROOT)
        mapped, pre, script, log = out/'mapped.json', out/'pre.il', out/'mapping.ys', out/'mapping.log'
        script.write_text(shlex.join(['read_slang', '--top', 'registered_row_request',
                          '-DSYNTHESIS=1', *map(str, sources)])+'\n'+
                          'read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n'+
                          'synth_xilinx -top registered_row_request -family xc7 -abc9 -noiopad -noclkbuf -flatten -run begin:map_luts\n'+
                          f'write_rtlil {pre}\n'+
                          'synth_xilinx -top registered_row_request -family xc7 -abc9 -noiopad -noclkbuf -flatten -run map_luts:\n'+
                          f'check -assert\nwrite_json {mapped}\n')
        execute(script, log)
        sys.path.insert(0, str(ROOT/'scripts/fpga'))
        from netlist_metrics import resources, connected_paths, register_origins
        module = json.loads(mapped.read_text())['modules']['registered_row_request']
        for name, value in register_origins(pre).items():
            if name in module['cells']:
                module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = value
        module['cells'] = {name: cell for name, cell in module['cells'].items() if cell['type'] != '$scopeinfo'}
        paths = connected_paths(module, limit=12, group_limit=12)
        if not paths['graph_complete']:
            raise RuntimeError('行请求模块组合连接统计不完整')
        report['mapping'] = dict(resources=resources(module['cells']), paths=paths,
                                 log_sha256=digest(log), model_sha256=digest(model))
        print('ROW_REQUEST_MAPPING '+json.dumps({
            'lut': report['mapping']['resources']['logic_lut_cells'],
            'depth': paths['longest_register_path_cells']}), flush=True)
    if any(digest(ROOT/name) != value for name, value in hashes.items()):
        raise RuntimeError('验证过程中行请求源码发生变化')
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
