#!/usr/bin/env python3
"""检查状态标志同时保存与排空条件分组的完整输入行为。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/vector_engine.sv')
STATES = {
    'state_failed': 'FAILED', 'state_compute_commit': 'EXECUTE_COMMIT',
    'state_output_init': 'OUTPUT_INIT', 'state_vector_init': 'VECTOR_INIT',
    'state_dw_finish': 'DW_FINISH',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as handle:
        result = subprocess.run(list(map(str, command)), cwd=ROOT, stdout=handle,
                                stderr=subprocess.STDOUT, timeout=120)
    if result.returncode:
        raise RuntimeError('控制边界检查失败：' + str(log))


def control(source):
    updates = re.findall(r'\{([\w,]+,state)\}\s*<=\s*state_control_value\(([^;]+)\);', source)
    assert updates and len({target for target, _ in updates}) == 1
    assert not re.search(r'(?<!\w)state\s*<=', source)
    fields = updates[0][0].split(',')
    function = re.search(r'function automatic logic .*? state_control_value\(.*?endfunction', source, re.S)[0]
    return fields, [re.sub(r'\s+', '', value) for _, value in updates], function


def expression(source, name):
    return re.search(r'assign\s+' + name + r'\s*=\s*(.*?);', source, re.S)[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--reference-revision', default='c1c0cb91770a7bb1639afb773f907432f9b12d6f')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--iverilog', default='iverilog')
    parser.add_argument('--vvp', default='vvp')
    args = parser.parse_args()
    current_path = args.source_root.resolve() / SOURCE
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.reference_root:
        reference_path = args.reference_root.resolve() / SOURCE
    else:
        sys.path.insert(0, str(ROOT / 'test'))
        from rtl_reference import read_rtl_source
        reference_path = out / 'reference_engine.sv'
        reference_path.write_bytes(read_rtl_source(args.reference_revision + ':' + str(SOURCE), cwd=ROOT))
    current, reference = current_path.read_text(), reference_path.read_text()
    old_fields, old_updates, old_function = control(reference)
    fields, updates, function = control(current)
    assert old_updates == updates
    extra = fields[:len(fields)-len(old_fields)]
    assert extra and fields[len(extra):] == old_fields
    assert set(extra) <= set(STATES)
    old_width, width = len(old_fields)+5, len(fields)+5
    enum = re.search(r'typedef enum logic \[5:0\].*?state_t;', current, re.S)[0]
    assert enum == re.search(r'typedef enum logic \[5:0\].*?state_t;', reference, re.S)[0]
    old_function = old_function.replace('state_control_value', 'original_control_value')
    function = function.replace('state_control_value', 'selected_control_value')
    functions = (old_function+'\n'+function).replace('input state_t next_state', 'input logic [5:0] next_state')
    expected = '{' + ','.join('next_state=='+STATES[name] for name in extra) + '}'
    saved_expected = expected.replace('next_state', 'selected_saved[5:0]')
    model = out / 'control_word.sv'
    model.write_text(f'''module control_word (
    input logic clk, rst_n, load,
    input logic [5:0] next_state,
    output wire [{old_width-1}:0] original_word,
    output wire [{width-1}:0] selected_word,
    output logic [{old_width-1}:0] original_saved,
    output logic [{width-1}:0] selected_saved,
    output wire [{len(extra)-1}:0] expected_flags, expected_saved_flags,
    output wire comb_equal, saved_equal
);
{enum}
{functions}
assign original_word = original_control_value(next_state);
assign selected_word = selected_control_value(next_state);
assign expected_flags = {expected};
assign expected_saved_flags = {saved_expected};
assign comb_equal = selected_word[{old_width-1}:0] == original_word &&
    selected_word[{width-1}:{old_width}] == expected_flags;
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        original_saved <= original_control_value(IDLE);
        selected_saved <= selected_control_value(IDLE);
    end else if (load) begin
        original_saved <= original_word;
        selected_saved <= selected_word;
    end
end
assign saved_equal = selected_saved[{old_width-1}:0] == original_saved &&
    selected_saved[{width-1}:{old_width}] == expected_saved_flags;
endmodule
''')
    drain = out / 'drain_conditions.sv'
    drain.write_text('''module drain_conditions #(parameter bit SHARED_STORAGE_ENABLE=1'b1)(
    input logic rd_busy, read_done_q, wr_busy, win_busy, input_response_pending,
    input logic writeback_busy, shared_weight_write_pending, dma_cfg_ready,
    input logic i_weight_read_valid, i_ps_read_valid,
    input logic [1:0] dw_shared_inflight,
    output wire original, selected, equal
);
logic input_drain_local_idle;
assign original = ''' + expression(reference, 'input_drain_ready') + ''';
assign input_drain_local_idle = ''' + expression(current, 'input_drain_local_idle') + ''';
assign selected = ''' + expression(current, 'input_drain_ready') + ''';
assign equal = original == selected;
endmodule
''')
    proofs = []
    tasks = [('state_encodings', model, 'control_word', '',
              'delete w:original_saved w:selected_saved w:expected_saved_flags w:saved_equal\nopt_clean\n'
              'sat -verify -prove comb_equal 1 -show-inputs -show-outputs\n'),
             ('state_sequence', model, 'control_word', '',
              'async2sync\nsat -verify -seq 6 -set-at 1 rst_n 0 -prove saved_equal 1 -show-inputs -show-outputs\n')]
    for shared in (0, 1):
        tasks.append((f'drain_shared{shared}', drain, 'drain_conditions', f'-GSHARED_STORAGE_ENABLE={shared}',
                      'sat -verify -prove equal 1 -show-inputs -show-outputs\n'))
    for name, path, top, options, command in tasks:
        script = out / (name + '.ys')
        script.write_text(f'read_slang --top {top} {options} '+shlex.quote(str(path))+'\n'
                          f'prep -top {top} -flatten\n'+command)
        log = script.with_suffix('.log')
        run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        proofs.append({'name': name, 'passed': True, 'log_sha256': sha(log)})
    bench = out / 'four_state.sv'
    bench.write_text(f'''module tb;
logic clk=0, rst_n=1, load=0;
logic [5:0] next_state;
wire [{old_width-1}:0] original_word, original_saved;
wire [{width-1}:0] selected_word, selected_saved;
wire [{len(extra)-1}:0] expected_flags, expected_saved_flags;
wire comb_equal, saved_equal;
control_word dut (.*);
logic [11:0] drain_inputs;
wire [1:0] drain_original, drain_selected;
for (genvar shared=0;shared<2;shared++) begin:g_profile
    drain_conditions #(.SHARED_STORAGE_ENABLE(shared)) drain (
        .rd_busy(drain_inputs[0]),.read_done_q(drain_inputs[1]),.wr_busy(drain_inputs[2]),
        .win_busy(drain_inputs[3]),.input_response_pending(drain_inputs[4]),.writeback_busy(drain_inputs[5]),
        .shared_weight_write_pending(drain_inputs[6]),.dma_cfg_ready(drain_inputs[7]),
        .i_weight_read_valid(drain_inputs[8]),.i_ps_read_valid(drain_inputs[9]),
        .dw_shared_inflight(drain_inputs[11:10]),.original(drain_original[shared]),
        .selected(drain_selected[shared]),.equal());
end
integer code, bit_index, digit, seed, seed_result, state_checks=0, drain_checks=0;
initial begin
    #1;rst_n=0;#1;rst_n=1;
    for(code=0;code<4096;code=code+1) begin
        for(bit_index=0;bit_index<6;bit_index=bit_index+1) begin
            digit=(code>>(2*bit_index))&3;
            case(digit)
                0:next_state[bit_index]=1'b0;
                1:next_state[bit_index]=1'b1;
                2:next_state[bit_index]=1'bx;
                3:next_state[bit_index]=1'bz;
            endcase
        end
        load=1;#1;
        if(selected_word[{old_width-1}:0] !== original_word ||
           selected_word[{width-1}:{old_width}] !== expected_flags) $fatal(1,"state encoding %0d",code);
        clk=1;#1;
        if(selected_saved[{old_width-1}:0] !== original_saved ||
           selected_saved[{width-1}:{old_width}] !== expected_saved_flags) $fatal(1,"saved encoding %0d",code);
        clk=0;#1;state_checks=state_checks+1;
    end
    seed=32'h43a976ef;seed_result=$urandom(seed);
    for(code=0;code<65536;code=code+1) begin
        drain_inputs=12'($urandom());
        if(code%3==0)drain_inputs[$urandom()%12]=1'bx;
        if(code%3==1)drain_inputs[$urandom()%12]=1'bz;
        #1;
        if(drain_original !== drain_selected)$fatal(1,"drain inputs %0d",code);
        drain_checks=drain_checks+2;
    end
    $display("VECTOR_CONTROL_BOUNDARIES_PASS state_encodings=%0d drain_comparisons=%0d",state_checks,drain_checks);
    $finish;
end
endmodule
''')
    binary = out/'four_state.vvp'
    run([args.iverilog,'-g2012','-s','tb','-o',binary,model,drain,bench],out/'compile.log')
    run([args.vvp,binary],out/'four_state.log')
    assert 'VECTOR_CONTROL_BOUNDARIES_PASS state_encodings=4096 drain_comparisons=131072' in (out/'four_state.log').read_text()
    assert current == current_path.read_text() and reference == reference_path.read_text()
    report={'passed':True,'source_sha256':sha(current_path),'reference_sha256':sha(reference_path),
            'reference_revision':None if args.reference_root else args.reference_revision,
            'state_updates_checked':len(updates),'added_flags':{name:STATES[name]for name in extra},
            'original_state_control_fields_preserved':True,'formal':proofs,
            'four_state_encodings':4096,'four_state_drain_comparisons':131072,
            'test_sha256':sha(Path(__file__)),'simulation_log_sha256':sha(out/'four_state.log')}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
