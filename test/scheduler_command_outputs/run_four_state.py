#!/usr/bin/env python3
"""逐周期比较实际调度器在正常命令和四态输入下的全部公开输出。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
RTL = Path('rtl/npu/control/ps_window_scheduler.sv')
HELPERS = ['onehot_check.sv', 'regfile.v', 'parallel_prefix_add.sv', 'unsigned_compare.sv']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_bench(size, frames, reuse):
    id_width = max(1, (frames - 1).bit_length())
    outputs = [('ready', 1), ('done_valid', 1), ('err_code', 2), ('command_valid', 1),
               ('frame_id', id_width)]
    outputs += [(name, 32) for name in ('p0', 'q0', 'column0', 'rows', 'cols', 'count_k', 'reserve_rows')]
    outputs += [(name, 1) for name in ('frame_init', 'frame_final', 'command_active', 'lookahead_valid')]
    outputs += [(name, 32) for name in ('lookahead_q0', 'lookahead_column', 'lookahead_cols', 'lookahead_count_k')]
    inputs = ('clk rst_n start stream_rows stationary_rows reduction reuse_rows window_frames '
              'slice_tiles config_error done_ready command_ready command_pressure command_complete').split()
    declarations = []
    instances = []
    for label in ('reference', 'current'):
        for name, width in outputs:
            declarations.append(f'wire [{width-1}:0] {label}_{name};')
        ports = [f'.{name}({name})' for name in inputs]
        ports += [f'.{name}({label}_{name})' for name, _ in outputs]
        instances.append(f'{label}_scheduler #(.SIZE({size}), .FRAME_COUNT({frames}), '
                         f'.MAX_REUSE_TILES({reuse})) u_{label}(' + ', '.join(ports) + ');')
    reference = ', '.join(f'reference_{name}' for name, _ in outputs)
    current = ', '.join(f'current_{name}' for name, _ in outputs)
    return rf'''module tb;
    logic clk=0, rst_n=0, start=0, done_ready=0;
    logic command_ready=0, command_pressure=0, command_complete=0;
    logic [31:0] stream_rows=1, stationary_rows=1, reduction=1;
    logic [31:0] reuse_rows=1, window_frames=1, slice_tiles=0;
    logic [1:0] config_error=0;
    {chr(10).join(declarations)}
    {chr(10).join(instances)}
    integer checks=0, accepted=0, completed=0, pressure_checks=0;
    integer completed_configs=0, unknown_checks=0, state_checks=0;
    integer timeout_cycles;
    reg [31:0] rng=32'h36c41a75;
    task next_random;
        begin
            rng = rng ^ (rng << 13);
            rng = rng ^ (rng >> 17);
            rng = rng ^ (rng << 5);
        end
    endtask
    task compare_outputs;
        begin
            if ({{{reference}}} !== {{{current}}})
                $fatal(1, "公开输出不同 check=%0d ref_phase=%0d current_phase=%0d active=%b valid=%b", checks,
                    u_reference.phase, u_current.phase, reference_command_active, reference_command_valid);
            checks = checks + 1;
            if (reference_command_active === 1'b1) begin
                if ({{u_current.active_id, u_current.active_init, u_current.active_row,
                      u_current.active_rows, u_current.active_q0, u_current.active_final}} !==
                    {{u_current.command_buffer_id, u_current.command_buffer_init,
                      u_current.command_buffer_row, 32'(u_current.command_buffer_rows),
                      u_current.command_buffer_q, u_current.command_buffer_final}})
                    $fatal(1, "执行字段保持关系不满足");
                state_checks = state_checks + 1;
            end
        end
    endtask
    task tick;
        begin
            #2; compare_outputs();
            if (rst_n === 1'b1) begin
                if (reference_command_valid === 1'b1 && command_ready === 1'b1 &&
                    command_pressure === 1'b0) accepted = accepted + 1;
                if (reference_command_active === 1'b1 && command_complete === 1'b1)
                    completed = completed + 1;
                if (reference_command_valid === 1'b1 && command_pressure === 1'b1)
                    pressure_checks = pressure_checks + 1;
            end
            clk=1; #2; compare_outputs(); clk=0; #1;
        end
    endtask
    task reset_state;
        begin
            rst_n=0; start=0; done_ready=0; command_ready=0;
            command_pressure=0; command_complete=0; config_error=0;
            tick(); tick(); rst_n=1; tick();
        end
    endtask
    task random_configuration;
        begin
            next_random(); stream_rows = 1 + rng % 113;
            next_random(); stationary_rows = 1 + rng % 81;
            next_random(); reduction = 1 + rng % 99;
            next_random(); reuse_rows = 1 + rng % {min(4, reuse) if reuse else 4};
            next_random(); window_frames = 1 + rng % {frames};
            next_random(); slice_tiles = (rng[0] && reuse_rows > 1) ? 1 : 0;
            config_error=0;
        end
    endtask
    initial begin
        reset_state();
        // 命令接收、完成和压力均经过实际状态机，空闲间隔随机变化。
        for (integer scenario=0; scenario<96; scenario=scenario+1) begin
            random_configuration(); start=1; tick(); start=0;
            timeout_cycles=0;
            while (reference_done_valid !== 1'b1 && timeout_cycles<120000) begin
                next_random(); command_ready = rng[0] | rng[1];
                command_complete = reference_command_active && rng[2];
                command_pressure = reference_command_valid && (rng[6:3] == 4'd0);
                tick(); timeout_cycles=timeout_cycles+1;
            end
            if (reference_done_valid !== 1'b1) $fatal(1, "命令序列未完成");
            completed_configs=completed_configs+1;
            command_ready=0; command_pressure=0; command_complete=0;
            done_ready=1; tick(); done_ready=0; tick();
        end
        // 每个配置位分别注入 X/Z，比较配置处理和后续有限执行的四态结果。
        for (integer field=0; field<7; field=field+1) begin
            for (integer bit_index=0; bit_index<(field==6 ? 2 : 32); bit_index=bit_index+1) begin
                for (integer unknown=0; unknown<2; unknown=unknown+1) begin
                    reset_state(); random_configuration();
                    case (field)
                        0: stream_rows[bit_index] = unknown ? 1'bz : 1'bx;
                        1: stationary_rows[bit_index] = unknown ? 1'bz : 1'bx;
                        2: reduction[bit_index] = unknown ? 1'bz : 1'bx;
                        3: reuse_rows[bit_index] = unknown ? 1'bz : 1'bx;
                        4: window_frames[bit_index] = unknown ? 1'bz : 1'bx;
                        5: slice_tiles[bit_index] = unknown ? 1'bz : 1'bx;
                        6: if (bit_index<2) config_error[bit_index] = unknown ? 1'bz : 1'bx;
                    endcase
                    start=1; tick(); start=0;
                    for (integer cycle=0; cycle<48; cycle=cycle+1) begin
                        next_random(); command_ready=rng[0]; command_complete=rng[1];
                        command_pressure=(rng[5:2] == 4'd0); done_ready=rng[6];
                        tick(); unknown_checks=unknown_checks+1;
                    end
                end
            end
        end
        // 正常配置中单独改变控制输入四态值，并跨越复位与空闲周期。
        reset_state(); random_configuration(); start=1; tick(); start=0;
        for (integer cycle=0; cycle<10000; cycle=cycle+1) begin
            next_random();
            command_ready=rng[0]; command_pressure=(rng[4:1] == 4'd0);
            command_complete=rng[5]; done_ready=rng[6]; start=rng[7];
            case (rng[11:8])
                0: command_ready=1'bx;
                1: command_ready=1'bz;
                2: command_pressure=1'bx;
                3: command_pressure=1'bz;
                4: command_complete=1'bx;
                5: command_complete=1'bz;
                6: done_ready=1'bx;
                7: done_ready=1'bz;
                8: start=1'bx;
                9: start=1'bz;
            endcase
            if (cycle%211 == 0) reset_state();
            tick(); unknown_checks=unknown_checks+1;
        end
        // 执行状态为未知值时检查实际输出选择表达式。
        force u_reference.command_active=1'bx; force u_current.command_active=1'bx;
        #2; compare_outputs();
        force u_reference.command_active=1'bz; force u_current.command_active=1'bz;
        #2; compare_outputs();
        release u_reference.command_active; release u_current.command_active;
        if (accepted==0 || completed==0 || pressure_checks==0 || state_checks==0)
            $fatal(1, "必须覆盖接收、完成、压力和执行字段保持");
        $display("{{\"passed\":true,\"checks\":%0d,\"accepted_commands\":%0d,\"completed_commands\":%0d,\"pressure_checks\":%0d,\"completed_configurations\":%0d,\"four_state_cycles\":%0d,\"active_state_checks\":%0d}}",
            checks,accepted,completed,pressure_checks,completed_configs,unknown_checks,state_checks);
        $finish;
    end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--profiles', nargs='+', default=['4:2:0', '8:4:1', '16:8:16', '16:16:32'])
    parser.add_argument('--modes', nargs='+', choices=['XILINX_FPGA', 'ASIC_SYNTHESIS'],
                        default=['XILINX_FPGA', 'ASIC_SYNTHESIS'])
    parser.add_argument('--out', type=Path, default=ROOT / 'build/scheduler_command_outputs/four_state')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths = {'reference': args.reference_root.resolve() / RTL,
             'current': args.source_root.resolve() / RTL}
    helpers = [args.source_root.resolve() / 'rtl/common' / name for name in HELPERS]
    manifest = {str(path): digest(path) for path in list(paths.values()) + helpers + [Path(__file__).resolve()]}
    models = []
    for label, path in paths.items():
        text = path.read_text()
        for name in re.findall(r'^module\s+(\w+)', text, re.MULTILINE):
            text = re.sub(r'\b' + name + r'\b',
                          label + ('_scheduler' if name == 'ps_window_scheduler' else '_' + name), text)
        generated = out / (label + '.sv')
        generated.write_text(text)
        models.append(generated)
    results = []
    for profile in args.profiles:
        size, frames, reuse = map(int, profile.split(':'))
        for mode in args.modes:
            name = f'{size}_{frames}_{reuse}_{mode}'
            bench = out / (name + '.sv')
            bench.write_text(make_bench(size, frames, reuse))
            binary = out / (name + '.vvp')
            command = ['iverilog', '-g2012', '-D' + mode + '=1', '-s', 'tb', '-o', str(binary)]
            command += [str(path) for path in models + helpers + [bench]]
            compile_log = out / (name + '.compile.log')
            with compile_log.open('w') as stream:
                subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
            run = subprocess.run(['vvp', str(binary)], text=True, capture_output=True, timeout=300)
            log = out / (name + '.log')
            log.write_text(run.stdout + run.stderr)
            if run.returncode != 0:
                raise RuntimeError(f'四态逐周期比较未通过：{log}')
            result = json.loads(next(line for line in run.stdout.splitlines() if line.startswith('{')))
            if not result['passed']:
                raise RuntimeError(f'四态检查未通过：{log}')
            result.update(SIZE=size, FRAME_COUNT=frames, MAX_REUSE_TILES=reuse, mode=mode,
                          bench_sha256=digest(bench), log_sha256=digest(log), log=str(log))
            results.append(result)
            print(json.dumps(result), flush=True)
    if any(digest(Path(path)) != expected for path, expected in manifest.items()):
        raise RuntimeError('测试期间输入文件发生变化')
    summary = dict(passed=True, source_sha256=manifest, profiles=results,
                   comparisons=sum(row['checks'] for row in results),
                   four_state_cycles=sum(row['four_state_cycles'] for row in results))
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
