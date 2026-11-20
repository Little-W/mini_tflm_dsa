#!/usr/bin/env python3
"""验证真实 npu_top 的完成背压、单次接收和连续普通任务恢复。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
COMMON = ROOT / 'test/conv_npu'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise RuntimeError('The shared testbench structure changed; inspect the completion adapter')
    return text.replace(before, after, 1)


def testbench():
    text = (COMMON / 'tb_conv_npu.sv').read_text()
    text = replace_once(text,
        '                done_ready=1;@(negedge clk);done_ready=0;\n'
        '                repeat(8)@(negedge clk);',
        '''                assert(u_dut.tb_completion.wait_done_seen)
                    else $fatal(1,"ordinary controller did not enter WAIT_DONE");
                // 完成接收后保持就绪，逐周期检查完成计数与公开有效信号。
                done_ready=1;
                repeat(24)begin
                    @(negedge clk);
                    assert(u_dut.tb_completion.job_done_count==1 && !done_valid)
                        else $fatal(1,"duplicate completion during sustained ready");
                end
                assert(sa_ready && u_dut.dma_idle && !u_dut.conv_busy &&
                    u_mem.count==0 && !u_mem.rd_active && !rvalid &&
                    !u_mem.wr_active && !bvalid)
                    else $fatal(1,"ordinary task did not return to a fully drained ready state");
                $display("COMPLETION_HANDSHAKE_PASS task=%0d conv=%0d accepted=%0d ready_cycles=24 wait_done=%0d",
                    task_number,saved_cfg[32][0],u_dut.tb_completion.job_done_count,
                    u_dut.tb_completion.wait_done_seen);
                done_ready=0;
                repeat(2)@(negedge clk);''')
    return replace_once(text,
        '        $display("CONV_NPU_PASS tasks=%0d size=%0d",task_number,SIZE);',
        '''        assert(u_dut.tb_completion.tasks_started==32'(task_number) &&
            u_dut.tb_completion.tasks_completed==32'(task_number) &&
            u_dut.tb_completion.gemm_completed>=2 && u_dut.tb_completion.conv_completed>=2)
            else $fatal(1,"ordinary completion coverage is incomplete");
        $display("NPU_COMPLETION_PASS starts=%0d completed=%0d gemm=%0d conv=%0d backpressure_cycles=%0d",
            u_dut.tb_completion.tasks_started,u_dut.tb_completion.tasks_completed,
            u_dut.tb_completion.gemm_completed,u_dut.tb_completion.conv_completed,
            u_dut.tb_completion.completion_backpressure_cycles);
        $display("CONV_NPU_PASS tasks=%0d size=%0d",task_number,SIZE);''')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/completion_handshake')
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--jobs', type=int, default=1)
    args = parser.parse_args()
    out = args.out.resolve()
    out.relative_to(ROOT)
    out.mkdir(parents=True, exist_ok=True)
    generated = out / 'tb_conv_npu.sv'
    generated.write_text(testbench())

    spec = importlib.util.spec_from_file_location('completion_common', COMMON / 'run.py')
    common = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(common)
    sources, includes, tracked = common.source_files()
    sources = [generated if source == COMMON / 'tb_conv_npu.sv' else source for source in sources]
    sources.append(HERE / 'observer.sv')
    tracked.extend([generated, HERE / 'observer.sv', Path(__file__).resolve()])
    common.source_files = lambda: (sources, includes, list(dict.fromkeys(tracked)))
    reference = common.make_reference(out)
    tasks = [
        common.precision_task(out, 16, name='gemm_s8_ws', lhs_s16=False,
            rows=5, reduction=7, columns=9, requested_r=1, requested_w=1),
        common.task(out, 16, reference, name='conv_ws', h=5, w=7, c=3,
            co=7, requested_r=1, requested_w=1, seed=2101),
        common.precision_task(out, 16, name='gemm_s16_is', dataflow=1,
            rows=17, reduction=19, columns=7, requested_r=1, requested_w=1),
        common.task(out, 16, reference, name='conv_is', h=4, w=5, c=2,
            co=17, dataflow=1, requested_r=1, requested_w=1, seed=2102),
    ]
    binary = common.build(out, 16, args.verilator, args.jobs,
        cache_sets=128, cache_policy=3, ps_compress=True, pool_bytes=16384,
        bus_width=64, shared_bank_bytes=4096, shared_bank_count=8)
    results = []
    for name, fixed in (('fixed_latency', True), ('random_stalls', False)):
        result = common.run_suite(binary, out, name, tasks, no_random=fixed)
        log = (out / (name + '.log')).read_text()
        handshakes = [dict((key, int(value)) for key, value in re.findall(r'(\w+)=(\d+)', line))
            for line in log.splitlines() if line.startswith('COMPLETION_HANDSHAKE_PASS ')]
        totals = [dict((key, int(value)) for key, value in re.findall(r'(\w+)=(\d+)', line))
            for line in log.splitlines() if line.startswith('NPU_COMPLETION_PASS ')]
        result['completion_checks'] = handshakes
        result['completion_totals'] = totals
        result['passed'] = (result['passed'] and len(handshakes) == len(tasks) and len(totals) == 1
            and all(item['accepted'] == 1 and item['ready_cycles'] >= 20 and item['wait_done'] == 1
                    for item in handshakes)
            and totals[0]['starts'] == totals[0]['completed'] == len(tasks))
        results.append(result)
    summary = {
        'passed': all(result['passed'] for result in results),
        'task_count': sum(len(result['completion_checks']) for result in results),
        'parameters': {'SIZE': 16, 'BUS_WIDTH': 64, 'SHARED_BANK_BYTES': 4096,
            'SHARED_BANK_COUNT': 8, 'OPERAND_CACHE_ENABLE': 0},
        'build_manifest': str(out / 'build.json'),
        'binary_sha256': digest(binary),
        'input_sha256': {str(path.relative_to(ROOT)): digest(path)
            for task in tasks for path in sorted(task.iterdir()) if path.is_file()},
        'runs': results,
    }
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print('NPU_COMPLETION_RESULT', summary['passed'], 'tasks', summary['task_count'], flush=True)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
