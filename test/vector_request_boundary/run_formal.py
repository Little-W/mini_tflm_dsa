#!/usr/bin/env python3
"""验证核位置末项寄存状态及共享输入槽位的更新条件。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ENGINE = Path('rtl/npu/conv/vector_engine.sv')
KEPT = ('tap', 'taps', 'tap_last_modulo')
PROFILES = (
    ('production', True, dict(TILE=16, BUS_WIDTH=64, PE_COUNT=8, WINDOW_LANES=8,
                             SHARED_STORAGE_ENABLE=1, SHARED_QUANT_ENABLE=0,
                             SHARED_STORAGE_ADDR_WIDTH=12, DMA_SIZE=64)),
    ('generic', False, dict(TILE=16, BUS_WIDTH=32, PE_COUNT=16, WINDOW_LANES=4,
                           SHARED_STORAGE_ENABLE=0, SHARED_QUANT_ENABLE=1, DMA_SIZE=64)),
    ('small', False, dict(TILE=2, BUS_WIDTH=32, PE_COUNT=1, WINDOW_LANES=4,
                         SHARED_STORAGE_ENABLE=0, SHARED_QUANT_ENABLE=0, DMA_SIZE=8,
                         MAX_TAPS=1, POOL_MAX_TAPS=1)),
    ('odd_limit', False, dict(TILE=2, BUS_WIDTH=32, PE_COUNT=1, WINDOW_LANES=4,
                             SHARED_STORAGE_ENABLE=0, SHARED_QUANT_ENABLE=0, DMA_SIZE=8,
                             MAX_TAPS=7, POOL_MAX_TAPS=31)),
    ('wide_count', False, dict(TILE=2, BUS_WIDTH=64, PE_COUNT=2, WINDOW_LANES=8,
                              SHARED_STORAGE_ENABLE=0, SHARED_QUANT_ENABLE=0, DMA_SIZE=8,
                              MAX_TAPS=49, POOL_MAX_TAPS=1024)),
    ('maximum_limits', False, dict(TILE=2, BUS_WIDTH=32, PE_COUNT=1, WINDOW_LANES=4,
                                  SHARED_STORAGE_ENABLE=0, SHARED_QUANT_ENABLE=0, DMA_SIZE=8,
                                  MAX_TAPS=255, POOL_MAX_TAPS=65535)),
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, folder, name, timeout=240):
    log = folder / (name + '.log')
    with log.open('w') as stream:
        stream.write('$ ' + shlex.join(map(str, command)) + '\n')
        stream.flush()
        result = subprocess.run(list(map(str, command)), stdout=stream,
                                stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError('验证未通过：' + str(log))
    return log


def source_audit(reference, selected):
    """逐条确认 tap/taps 的更新与末项状态共同保存。"""
    actual = selected
    pool_flag = 'logic state_pool_store;' in actual
    if pool_flag:
        actual = actual.replace('logic [$bits(state_t)+10:0] state_control_value',
                                'logic [$bits(state_t)+9:0] state_control_value')
        actual = actual.replace('        next_state==POOL_STORE,\n', '')
        actual = actual.replace('  logic state_pool_store;\n', '')
        actual = actual.replace('{state_pool_store,state_output_init,', '{state_output_init,')
        actual = actual.replace('      assert(state_pool_store == (state==POOL_STORE));\n', '')
        actual = actual.replace('assign pool_selected = state_pool_store &&',
                                'assign pool_selected = state == POOL_STORE &&')
        actual = actual.replace('if (state_pool_store) assert(!result_byte_pending);',
                                'if (state==POOL_STORE) assert(!result_byte_pending);')
        actual = actual.replace(' || state_pool_store || ', ' || state==POOL_STORE || ')
        actual = actual.replace('// 初始化、提交、池化写入和失败资格与状态同时保存，直接控制数据选择及排空。',
                                '// 初始化、提交和失败资格与状态同时保存，直接控制数据选择及排空。')
    declaration = '  logic tap_last_config, tap_last_zero, tap_last_increment;\n'
    assert actual.count(declaration) == 1
    actual = actual.replace(declaration, '')
    old_compare = """  add_equal #(.p_width(TAP_COUNT_W)) u_tap_last_modulo (
      .i_a(tap), .i_b(TAP_COUNT_W'(1)), .i_target(taps), .i_carry_in(1'b0),
      .o_equal(tap_last_modulo)
  );"""
    new_compare = """  // 末项资格与核位置同时保存，权重预取直接读取该寄存结果。
  // 三种更新分别对应配置载入、位置归零和核位置递增。
  add_equal #(.p_width(TAP_COUNT_W)) u_tap_last_config (
      .i_a(tap), .i_b(TAP_COUNT_W'(1)), .i_target(TAP_COUNT_W'(kernel_count)),
      .i_carry_in(1'b0), .o_equal(tap_last_config)
  );
  add_equal #(.p_width(TAP_COUNT_W)) u_tap_last_zero (
      .i_a({TAP_COUNT_W{1'b0}}), .i_b(TAP_COUNT_W'(1)), .i_target(taps),
      .i_carry_in(1'b0), .o_equal(tap_last_zero)
  );
  add_equal #(.p_width(TAP_COUNT_W)) u_tap_last_increment (
      .i_a(weight_tap_nxt), .i_b(TAP_COUNT_W'(1)), .i_target(taps),
      .i_carry_in(1'b0), .o_equal(tap_last_increment)
  );"""
    assert actual.count(new_compare) == 1
    actual = actual.replace(new_compare, old_compare)
    updates = (
        ("taps<=0; tap_last_modulo<=1'b0; active<=0;", 'taps<=0; active<=0;', 1),
        ("taps<=32'(kernel_count);tap_last_modulo<=tap_last_config;channel_base<=0;",
         "taps<=32'(kernel_count);channel_base<=0;", 1),
        ('tap<=0;tap_last_modulo<=tap_last_zero;kx<=0;ky<=0;valid_taps<=0;',
         'tap<=0;kx<=0;ky<=0;valid_taps<=0;', 1),
        ("compute_index<='0;tap<='0;tap_last_modulo<=tap_last_zero;kx<='0;ky<='0;",
         "compute_index<='0;tap<='0;kx<='0;ky<='0;", 1),
        ('tap<=weight_tap_nxt;tap_last_modulo<=tap_last_increment;',
         'tap<=weight_tap_nxt;', 3),
    )
    for current, previous, count in updates:
        assert actual.count(current) == count
        actual = actual.replace(current, previous)
    old_release = '''  // PE 在释放边沿保存旧槽操作数，新请求可以在同一边沿预留该槽。
  assign input_slot_release = dw_issue_fire && dw_group_last && wf_bank==read_bank;'''
    new_release = '''  // 共享权重配置在槽位清空后预留下一请求，私有配置在操作数保存边沿允许复用。
  assign input_slot_release = !SHARED_STORAGE_ENABLE &&
      dw_issue_fire && dw_group_last && wf_bank==read_bank;'''
    slot_boundary = old_release in reference
    if slot_boundary:
        assert actual.count(new_release) == 1
        actual = actual.replace(new_release, old_release)
    assert actual == reference, '源码包含不属于末项状态保存的其他变换'
    return dict(update_sites=7, original_wide_comparison_preserved=True, registered_pool_qualifier=pool_flag,
                shared_slot_reuse_after_clear=slot_boundary,
                all_other_statements_identical=True)


def abstract_registers(folder):
    design = json.loads((folder / 'flat.json').read_text())
    module = design['modules']['vector_engine']
    kept_bits = {bit for name in KEPT for bit in module['netnames'][name]['bits']}
    ports = {name: port for name, port in module['ports'].items()
             if port['direction'] == 'input' or name == 'formal_tap_last_property'}
    retained, cut = [], []
    for name, cell in list(module['cells'].items()):
        sequential = any(kind in cell['type'] for kind in ('dff', 'latch'))
        if not sequential and not cell['type'].startswith('$mem'):
            continue
        outputs = [bit for port, direction in cell['port_directions'].items()
                   if direction == 'output' for bit in cell['connections'][port]]
        if any(bit in kept_bits for bit in outputs):
            assert all(bit in kept_bits for bit in outputs)
            retained.append(dict(cell=name, type=cell['type'], bits=outputs))
            continue
        del module['cells'][name]
        for port, direction in cell['port_directions'].items():
            bits = cell['connections'][port]
            if direction != 'output' or not any(isinstance(bit, int) for bit in bits):
                continue
            label = 'abstract_' + str(len(cut))
            ports[label] = dict(direction='input', bits=bits)
            module['netnames'][label] = dict(hide_name=0, bits=bits, attributes={})
            cut.append(dict(cell=name, port=port, bits=bits, name=label))
    module['ports'] = ports
    module['memories'] = {}
    for net in module['netnames'].values():
        net['attributes'].pop('init', None)
    for name in KEPT:
        module['ports']['o_' + name] = dict(direction='output', bits=module['netnames'][name]['bits'])
    assert len(retained) == 3
    (folder / 'abstract.json').write_text(json.dumps(design))
    record = dict(kept=KEPT, retained=retained, cut=cut)
    (folder / 'abstraction.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def prove(source, tool_root, folder, fpga, params, sources):
    folder.mkdir(parents=True, exist_ok=True)
    engine = folder / 'vector_engine.sv'
    text = (source / ENGINE).read_text()
    text = text.replace('  output logic ready, done_valid,',
                        '  output logic formal_tap_last_property,\n  output logic ready, done_valid,', 1)
    oracle = """
  wire formal_tap_last_expected;
  add_equal #(.p_width(TAP_COUNT_W)) u_formal_tap_last (
      .i_a(tap), .i_b(TAP_COUNT_W'(1)), .i_target(taps), .i_carry_in(1'b0),
      .o_equal(formal_tap_last_expected)
  );
  assign formal_tap_last_property = tap_last_modulo == formal_tap_last_expected;
"""
    engine.write_text(text.replace('endmodule', oracle + '\nendmodule', 1))
    arguments = ['read_slang', '--top', 'vector_engine', '-I', str(source / 'include'),
                 '-I', str(source / 'rtl/npu/ps_compact'), '-D', 'SYNTHESIS=1', '-D',
                 'XILINX_FPGA=1' if fpga else 'ASIC_SYNTHESIS=1']
    arguments += [f'-G{name}={value}' for name, value in params.items()]
    arguments += [str(engine if path == ENGINE else source / path) for path in sources]
    script = folder / 'elaborate.ys'
    script.write_text(shlex.join(arguments) + '\n'
                      'read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n'
                      'read_verilog -lib -overwrite +/xilinx/cells_xtra.v\n'
                      'hierarchy -check -top vector_engine\nproc\nflatten\nopt -keepdc\n'
                      'select vector_engine\nwrite_json -selected ' + str(folder / 'flat.json') + '\n')
    worker = [sys.executable, tool_root / 'scripts/fpga/open_fpga_synth.py', '--worker']
    run(worker + [script], folder, 'elaborate')
    abstraction = abstract_registers(folder)
    script = folder / 'proof.ys'
    script.write_text('read_json ' + str(folder / 'abstract.json') + '\n'
                      'hierarchy -top vector_engine\nopt -full\nasync2sync\nopt -full\n'
                      'sat -verify -tempinduct -seq 4 -set-at 1 rst_n 0 '
                      '-prove formal_tap_last_property 1 -show o_tap,o_taps,o_tap_last_modulo\n')
    log = run(worker + [script], folder, 'proof')
    message = log.read_text()
    assert 'Induction step proven: SUCCESS!' in message
    record = dict(passed=True,
                  induction_length=int(re.findall(r'Trying induction with length (\d+)', message)[-1]),
                  retained_register_groups=len(abstraction['retained']),
                  free_state_outputs=len(abstraction['cut']), proof_log_sha256=sha(log),
                  abstraction_sha256=sha(folder / 'abstraction.json'),
                  flat_sha256=sha(folder / 'flat.json'), abstract_sha256=sha(folder / 'abstract.json'))
    # 保留生成脚本、摘要和校验值，较大的中间 JSON 可按脚本重新生成。
    (folder / 'flat.json').unlink()
    (folder / 'abstract.json').unlink()
    return record


def four_state(source, folder, iverilog, vvp):
    folder.mkdir(parents=True, exist_ok=True)
    widths = (1, 2, 3, 5, 6, 9, 11, 16, 24)
    text = (source / ENGINE).read_text()
    blocks = []
    for name in ('u_weight_tap_increment', 'u_tap_last_config', 'u_tap_last_zero', 'u_tap_last_increment'):
        match = re.search(r'(?:parallel_prefix_add|add_equal)\s*#\(.*?\)\s*' + name +
                          r'\s*\(.*?\n  \);', text, re.S)
        # 从实例之前最近一个模块类型开始，保留实际运算参数及端口。
        assert match
        block = match[0]
        start = max(block.rfind('parallel_prefix_add #'), block.rfind('add_equal #'))
        blocks.append(block[start:])
    model = """module model #(parameter integer TAP_COUNT_W=9)(
 input logic clk,rst_n,configure,clear_position,advance,
 input logic [TAP_COUNT_W-1:0] kernel_count,
 output logic identical
);
 logic [TAP_COUNT_W-1:0] tap,taps,weight_tap_nxt;
 logic tap_last_modulo,tap_last_config,tap_last_zero,tap_last_increment;
 logic unused_weight_tap_carry,expected;
""" + '\n'.join(blocks) + """
 add_equal #(.p_width(TAP_COUNT_W)) oracle(
  .i_a(tap),.i_b(TAP_COUNT_W'(1)),.i_target(taps),.i_carry_in(1'b0),.o_equal(expected));
 always @(posedge clk or negedge rst_n) begin
  if(!rst_n) begin tap<=0;taps<=0;tap_last_modulo<=0;end
  else if(configure) begin taps<=kernel_count;tap_last_modulo<=tap_last_config;end
  else if(clear_position) begin tap<=0;tap_last_modulo<=tap_last_zero;end
  else if(advance) begin tap<=weight_tap_nxt;tap_last_modulo<=tap_last_increment;end
 end
 assign identical=(tap_last_modulo===expected);
endmodule
module tb;
 logic clk=0,rst_n=0,configure=0,clear_position=0,advance=0;
 logic [31:0] data=0;
 wire [8:0] identical;
 integer i,j,checks=0;integer unsigned rng=32'h319b8b4e;
 function automatic [31:0] next_random();
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
 endfunction
 function automatic logic four(input [1:0] value);
  case(value) 0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
 endfunction
 task automatic tick;
  #2;clk=1;#2;
  if(identical!==9'h1ff)$fatal(1,"末项状态四态比较不一致：%b",identical);
  checks=checks+9;clk=0;#2;
 endtask
"""
    for i, width in enumerate(widths):
        model += f'model #(.TAP_COUNT_W({width})) m{i}(clk,rst_n,configure,clear_position,advance,data[{width-1}:0],identical[{i}]);\n'
    model += """
 initial begin
  tick();rst_n=1;
  for(i=0;i<24000;i=i+1)begin
   data=next_random();
   if(i%3==0)for(j=0;j<32;j=j+1)data[j]=four(2'(next_random()));
   configure=four(2'(next_random()));clear_position=four(2'(next_random()));advance=four(2'(next_random()));
   rst_n=(i%97==0)?four(2'(next_random())):1'b1;
   tick();
  end
  $display("TAP_LAST_FOUR_STATE_PASS checks=%0d",checks);$finish;
 end
endmodule
"""
    bench = folder / 'tb.sv'
    bench.write_text(model)
    executable = folder / 'simulation'
    run([iverilog, '-g2012', '-s', 'tb', '-o', executable, bench,
         source / 'rtl/common/add_equal.sv', source / 'rtl/common/parallel_prefix_add.sv'],
        folder, 'build')
    log = run([vvp, executable], folder, 'simulation')
    checks = int(re.search(r'TAP_LAST_FOUR_STATE_PASS checks=(\d+)', log.read_text())[1])
    return dict(passed=True, widths=widths, comparisons=checks, source_model_sha256=sha(bench),
                log_sha256=sha(log), arithmetic_instances_extracted_from_actual_source=True)


def prove_slot(reference, selected, tool_root, folder):
    """对实际请求表达式检查私有配置等价性及共享配置的空槽要求。"""
    folder.mkdir(parents=True, exist_ok=True)

    def expression(text, name):
        return re.search(r'assign\s+' + name + r'\s*=\s*(.*?);', text, re.S)[1]

    model = folder / 'slot.sv'
    model.write_text('''module slot #(parameter bit SHARED_STORAGE_ENABLE=0)(
 input logic dw_issue_fire,dw_group_last,window_slot_available,window_response_fault,
 input logic [1:0] wf_bank,read_bank,
 input logic [3:0] input_ready,input_reserved,
 output logic property_ok
);
 wire previous_release,selected_release,previous_valid,selected_valid;
 assign previous_release = ''' + expression(reference, 'input_slot_release') + ''';
 assign selected_release = ''' + expression(selected, 'input_slot_release') + ''';
 assign previous_valid = ''' + expression(reference, 'win_req_valid').replace('input_slot_release', 'previous_release') + ''';
 assign selected_valid = ''' + expression(selected, 'win_req_valid').replace('input_slot_release', 'selected_release') + ''';
 assign property_ok = SHARED_STORAGE_ENABLE ?
     (selected_release==0 &&
      selected_valid==(window_slot_available && !window_response_fault &&
          !input_ready[wf_bank] && !input_reserved[wf_bank])) :
     (previous_release==selected_release && previous_valid==selected_valid);
endmodule
''')
    rows = []
    for shared in (0, 1):
        script = folder / f'shared{shared}.ys'
        script.write_text(f'read_slang --top slot -GSHARED_STORAGE_ENABLE={shared} ' +
                          shlex.quote(str(model)) + '\nprep -top slot -flatten\n'
                          'sat -verify -prove property_ok 1 -show-inputs -show-outputs\n')
        log = run([sys.executable, tool_root / 'scripts/fpga/open_fpga_synth.py', '--worker', script],
                  folder, f'shared{shared}')
        rows.append(dict(shared_storage=shared, passed=True, log_sha256=sha(log)))
    return dict(passed=True, profiles=rows, model_sha256=sha(model), input_constraints='none')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--tool-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--reference-revision', default='0c99ca796e8a8cdd99180bcc8f8e5085abf17bca')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--iverilog', default='iverilog')
    parser.add_argument('--vvp', default='vvp')
    args = parser.parse_args()
    source, tools, out = args.source_root.resolve(), args.tool_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_text = (source / ENGINE).read_text()
    if args.reference_root:
        reference = args.reference_root.resolve() / ENGINE
    else:
        reference = out / 'reference_engine.sv'
        reference.write_bytes(subprocess.check_output(
            ['git', 'show', args.reference_revision + ':' + str(ENGINE)], cwd=tools))
    report = dict(passed=False, source_sha256=sha(source / ENGINE), reference_sha256=sha(reference),
                  source_audit=source_audit(reference.read_text(), source_text), profiles=[],
                  abstraction='Only tap, taps and tap_last_modulo remain sequential; every other state and memory output is free',
                  constraints='rst_n=0 at the first sampled cycle; all other inputs and subsequent resets are free')
    case = json.loads((tools / 'test/vector_engine/production_synthesis_cases.json').read_text())['vector']
    sources = list(dict.fromkeys([Path(path) for path in case['sources']] +
                  [path.relative_to(source) for path in sorted((source / 'rtl/common').rglob('*'))
                   if path.suffix in ('.v', '.sv')]))
    hashes = {str(path): sha(source / path) for path in sources}
    report['slot_qualification'] = prove_slot(reference.read_text(), source_text, tools, out / 'slot')
    report['four_state'] = four_state(source, out / 'four_state', args.iverilog, args.vvp)
    print(json.dumps(report['four_state']), flush=True)
    for name, fpga, params in PROFILES:
        row = dict(name=name, fpga=fpga, parameters=params,
                   result=prove(source, tools, out / name, fpga, params, sources))
        report['profiles'].append(row)
        print(json.dumps(row), flush=True)
    assert source_text == (source / ENGINE).read_text()
    assert hashes == {str(path): sha(source / path) for path in sources}
    report.update(passed=True, dependencies_sha256=hashes, test_sha256=sha(Path(__file__)))
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(passed=True, profiles=len(PROFILES), source_sha256=report['source_sha256'])))


if __name__ == '__main__':
    main()
