#!/usr/bin/env python3
"""从实际 NPU 控制器提取任务接收状态及其全部组合输入。"""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = 'c42f5ff9'
SOURCE = 'rtl/npu/top/npu_top.sv'
INSTANCE = '''    npu_task_accept_qualify #(.p_vector_capable(VECTOR_ENGINE_CAPABLE), .p_exclusive_vector(1'b1)) u_task_accept (
        .i_accept_ready(task_accept_ready), .i_abort_idle(abort_state == AB_IDLE),
        .i_run_conv(run_conv), .i_run_vector(run_vector), .i_conv_error(conv_error),
        .i_fault({ps_capacity_fault, shared_ram_capacity_fault, vector_shared_store_o_error, dma_bus_error,
            frame_mode_q && inner_done_valid && (inner_err_code != 2'b00)}),
        .i_calc_start(calc_start), .i_vector_enable(cfg_vector_enable), .i_conv_enable(cfg_conv_enable),
        .o_ready(sa_ready), .o_vector_start(vector_start_fire), .o_fault(task_fault)
    );
'''
PORTS = '''#(parameter bit VECTOR_ENGINE_CAPABLE=1)(
 input logic clk,rst_n,calc_start,cfg_vector_enable,cfg_conv_enable,done_valid,done_ready,
 input logic[1:0]abort_state,
 input logic ps_capacity_fault,shared_ram_capacity_fault,vector_shared_store_o_error,dma_bus_error,
 input logic frame_mode_q,inner_done_valid,input logic[1:0]inner_err_code,
 input logic run_conv,conv_error,vector_engine_ready,ctrl_sa_ready,frame_scheduler_ready,
 input logic[2:0]cfg_valid_q,
 input logic operand_cache_idle,frame_prefetch_idle,conv_task_idle,
 output logic sa_ready,vector_start_fire,task_accept_ready,run_vector,vector_rejected,task_fault,
 output wire proof_idle
);
 localparam logic[1:0]AB_IDLE=2'b00;
 logic task_accept_conditions;
 logic reset_seen=1'b0;
 always_ff @(posedge clk)if(!rst_n)reset_seen<=1'b1;
 assign proof_idle=!reset_seen||!run_vector||!task_accept_ready;
'''


def assignment(source, name):
    first = source.index('    assign ' + name + ' =')
    return source[first:source.index(';', first) + 1] + '\n'


def context(output):
    """检查完整父模块的变更范围，并原样保留实际状态更新语句。"""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(['git', 'show', REFERENCE + ':' + SOURCE], cwd=ROOT, text=True)
    candidate = (ROOT / SOURCE).read_text()
    expected = reference.replace(assignment(reference, 'vector_start_fire'), '')
    expected = expected.replace(assignment(reference, 'sa_ready'), '')
    expected = expected.replace(assignment(reference, 'task_fault'), INSTANCE)
    expected = expected.replace('    // 各运算来源并行汇总故障，中止状态持续保持至当前任务结束。\n', '')
    assert candidate == expected, '父模块存在任务接收资格以外的变化，需要更新组成验证范围'
    first = reference.index('    always_ff @(posedge clk or negedge rst_n) begin',
                            reference.index('    assign sa_ready ='))
    last = reference.index('    // 排空判断完成后', first)
    registers = reference[first:last]
    assert registers in candidate
    assert assignment(reference, 'task_accept_conditions') == assignment(candidate, 'task_accept_conditions')
    equations = ''.join(assignment(reference, name) for name in
                        ('sa_ready', 'vector_start_fire', 'task_fault', 'task_accept_conditions'))
    reference_context = 'module task_accept_property' + PORTS + equations + registers + 'endmodule\n'
    candidate_context = ('module task_accept_property' + PORTS + INSTANCE +
                         assignment(candidate, 'task_accept_conditions') + registers + 'endmodule\n')
    (output / 'reference.sv').write_text(reference_context)
    (output / 'candidate.sv').write_text(candidate_context)
    report = {
        'reference_commit': REFERENCE,
        'source': SOURCE,
        'parent_composition_checked': True,
        'nonstate_fanins_unconstrained': True,
        'state_registers': registers,
        'reference_assignments': equations,
        'candidate_instance': INSTANCE,
        'source_sha256': {
            'reference_parent': hashlib.sha256(reference.encode()).hexdigest(),
            'candidate_parent': hashlib.sha256(candidate.encode()).hexdigest(),
            'reference_context': hashlib.sha256(reference_context.encode()).hexdigest(),
            'candidate_context': hashlib.sha256(candidate_context.encode()).hexdigest(),
        }
    }
    (output / 'extraction.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report
