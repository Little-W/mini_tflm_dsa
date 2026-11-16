#!/usr/bin/env python3
"""Verify native AXI64 operator comparisons and each Dense 1.2x target."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shlex

import compare_fair_operators as common


ROOT = common.ROOT
EXPECTED_FC = {
    ('mnist_cnn', 5): (1, 64, 784),
    ('mnist_cnn', 6): (1, 10, 64),
    ('mobilenet_v1_vww', 29): (1, 2, 256),
    ('resnet8_cifar10', 14): (1, 10, 64),
    ('ds_cnn_kws', 11): (1, 12, 64),
}


class Axi64Comparison(common.Comparison):
    AXI_DATA_BITS = 64
    DMA_MAX_BYTES = 2048

    def verify_conditions(self) -> dict:
        conditions = super().verify_conditions()
        common.require(self.read_beat_cycles in (1, 2), 'Read service must be one or two cycles per beat')
        common.require(self.first_read_latency > 0, 'Synchronous memory must have nonzero read latency')
        common.require(self.inter_burst_gap > 0, 'Inter-burst spacing must be positive')
        for group, build in self.npu_builds.items():
            profile = self.documents['npu_' + group]['profile']
            common.require(build['bus_width'] == profile['bus_width'] == 64,
                           'NPU simulator must instantiate native 64-bit ports')
            command = build['command']
            common.require('-DTB_BUS_WIDTH=64' in command and '-DTB_DMA_MAX_BYTES=2048' in command
                           and '--assert' in command, 'NPU AXI64 compilation parameters differ')
            if 'read_beat_cycles' in build:
                common.require(build['read_beat_cycles'] == self.read_beat_cycles,
                               'NPU compiled read service differs')
                common.require(f'-DTB_READ_BEAT_CYCLES={self.read_beat_cycles}' in command,
                               'NPU read-service compile definition differs')
            else:
                common.require(self.read_beat_cycles == 2, 'NPU build does not specify one-cycle read service')
            if isinstance(profile['memory'], dict):
                for gemmini_key, (npu_key, value) in common.MEMORY_KEYS.items():
                    if gemmini_key == 'read_beat_interval_cycles':
                        value = self.read_beat_cycles
                    elif gemmini_key == 'first_read_latency_cycles':
                        value = self.first_read_latency
                    elif gemmini_key == 'inter_burst_read_gap_cycles':
                        value = self.inter_burst_gap
                    common.require(profile['memory'][npu_key] == value,
                                   'NPU group memory service differs: ' + npu_key)
                common.require(profile['memory']['write_beat_interval_min'] == 1,
                               'NPU write beat service differs')
            else:
                common.require(self.read_beat_cycles == 2 and self.first_read_latency == 3 and group == 'conv',
                               'The selected NPU memory service requires structured parameters')
        build = self.documents['gemmini_build']
        if self.first_read_latency != 3 or self.inter_burst_gap != 3:
            latency_semantics = 'per_request_from_ar_handshake'
            common.require(build['memory_service']['read_latency_semantics'] == latency_semantics,
                           'Gemmini read latency must be measured from each accepted AR')
            common.require(build['memory_service']['synchronous_read_register'] and
                           build['memory_service']['response_mode'] == 'request_deadline' and
                           build['memory_service']['read_outstanding_limit'] == 4,
                           'Gemmini synchronous read configuration differs')
            for group in ('npu_gemm', 'npu_conv'):
                memory = self.documents[group]['profile']['memory']
                common.require(memory['read_latency_semantics'] == latency_semantics,
                               'NPU read latency must be measured from each accepted AR')
                common.require(memory['registered_synchronous_read'] and memory['read_latency_overlap'],
                               'NPU must overlap independently timed synchronous reads')
                npu_build = self.npu_builds[group.removeprefix('npu_')]
                common.require(npu_build['first_read_latency'] == self.first_read_latency and
                               f'-DTB_READ_FIRST_LATENCY={self.first_read_latency}' in npu_build['command'] and
                               npu_build['memory_timing'] == 'pipelined' and
                               '-DTB_PIPELINED_READ=1' in npu_build['command'],
                               'NPU compiled first-response latency differs')
        for key, value in {'axi_max_beats': 256, 'axi_boundary_bytes': 4096,
                           'parameter_header_max_bytes': 2048}.items():
            common.require(build['configuration'][key] == value, 'Gemmini AXI4 parameter differs: ' + key)
        for path_key in ('generated_rtl', 'params_header'):
            path = self.resolve_recorded(build[path_key])
            common.require(common.digest(path) == build[path_key + '_sha256'],
                           'Gemmini generated artifact differs: ' + path_key)
            self.sources['gemmini_' + path_key] = common.artifact(path)
        for group in ('gemmini_native', 'gemmini_im2col'):
            exporter = self.documents[group]['exporter_build']
            common.require(exporter['vendor']['params_sha256'] == build['params_header_sha256'],
                           'Convolution exporter parameters differ from the generated hardware')
        adaptations = []
        for adaptation in build.get('source_adaptations', []):
            for key in ('patch', 'compiled_source'):
                path = self.resolve_recorded(adaptation[key])
                common.require(common.digest(path) == adaptation[key + '_sha256'],
                               'Gemmini source adaptation differs: ' + key)
            adaptations.append(adaptation)
        conditions.update(
            axi_max_beats=256, axi_boundary_bytes=4096,
            dma_limit_policy='AXI4 maximum 256 beats and 4 KiB boundary',
            read_beat_cycles=self.read_beat_cycles, write_beat_cycles=1,
            first_read_latency_cycles=self.first_read_latency,
            inter_burst_read_gap_cycles=self.inter_burst_gap,
            memory_service_role='soc_throughput' if self.read_beat_cycles == 1 else 'bandwidth_sensitivity',
            gemmini_source_adaptations=adaptations,
            npu_physical_port_validation='BUS_WIDTH=64 compile parameter; native read byte/beat accounting; AXI protocol assertions',
            gemmini_physical_port_validation='Compiled data-port width assertions and observed AXI width/beat histograms',
        )
        return conditions

    def verify_npu(self, row: dict, group: str, output_bytes: int) -> dict:
        result = super().verify_npu(row, group, output_bytes)
        timing, measurement = row['timing'], row['measurement']
        common.require(timing['read_latency_min'] >= self.first_read_latency,
                       'NPU returned data before the accepted request matured')
        common.require(measurement['ar_bytes'] == 8 * timing['read_beats'],
                       'NPU native 64-bit read beat accounting differs')
        common.require(output_bytes <= 8 * timing['write_beats'], 'NPU write lane accounting differs')
        common.require(timing['read_outstanding_max'] <= 4 and timing['write_outstanding_max'] <= 4,
                       'NPU outstanding transactions exceed the configured limit')
        if group == 'gemm':
            config = row['schedule_configuration']
            common.require(config['axi_data_bits'] == 64 and config['dma_max_bytes'] == 2048,
                           'NPU scheduler does not use the native AXI64 capabilities')
            common.require(config['read_beat_cycles'] == self.read_beat_cycles,
                           'NPU scheduler memory-service cost differs')
            common.require(row['schedule_mode'] == 'auto', 'GEMM comparison requires automatic NPU scheduling')
        result['physical_port_bits'] = 64
        result['protocol_assertions_enabled'] = True
        return result

    def verify_gemmini(self, row: dict, group: str, output_bytes: int) -> dict:
        result = super().verify_gemmini(row, group, output_bytes)
        if self.first_read_latency != 3 or 'read_latency_min' in row:
            common.require(row['read_latency_min'] >= self.first_read_latency,
                           'Gemmini returned data before the accepted request matured')
        if self.first_read_latency != 3 or self.inter_burst_gap != 3:
            common.require(row['read_latency_cycles'] == self.first_read_latency and
                           row['read_outstanding_limit'] == 4 and
                           row['memory_response_mode'] == 'request_deadline',
                           'Gemmini observed read service differs')
            common.require(row['max_read_outstanding_observed'] <= 4,
                           'Gemmini observed read concurrency exceeds its configured limit')
            if row['matured_request_switches']:
                common.require(row['matured_request_switch_gap_min'] >= self.inter_burst_gap,
                               'Gemmini switched mature requests before the configured response edge')
        for key, value in {'axi_data_bits': 64, 'axi_strobe_bits': 8,
                           'axi_max_beats': 256, 'axi_boundary_bytes': 4096}.items():
            common.require(row[key] == value, 'Gemmini observed AXI interface differs: ' + key)
        for direction in ('read', 'write'):
            beats = row[direction + '_beats']
            histogram = row[direction + '_beats_by_beat_bytes']
            requests = row[direction + '_requests_by_beat_bytes']
            common.require(set(histogram) == set(requests) == {'1', '2', '4', '8'},
                           'Gemmini AXI transfer-size histogram differs')
            common.require(sum(histogram.values()) == beats and
                           sum(requests.values()) == row[direction + '_requests'],
                           'Gemmini AXI transaction accounting differs')
            common.require(row[direction + '_bus_lane_bytes'] == 8 * beats,
                           'Gemmini native AXI lane accounting differs')
            common.require(0 < row['max_' + direction + '_burst_beats'] <= 256,
                           'Gemmini AXI burst exceeds 256 beats')
            transaction_bytes = sum(int(size) * count for size, count in histogram.items())
            if direction == 'read':
                common.require(transaction_bytes == row['read_bytes'], 'Gemmini read byte accounting differs')
            else:
                common.require(row['write_bytes'] <= transaction_bytes, 'Gemmini write strobe accounting differs')
        if group == 'gemmini_gemm':
            common.require(row['params_header_sha256'] == self.documents['gemmini_build']['params_header_sha256']
                           and row['config']['max_bytes'] == 2048,
                           'GEMM command generator parameters differ from the generated hardware')
            common.require(0 <= row['first_launch_cycle'] < row['cycles'] and
                           row['launch_to_complete_cycles'] == row['cycles'] - row['first_launch_cycle'],
                           'Gemmini loop-launch timing differs from the complete command interval')
        result['physical_port_bits'] = 64
        result['protocol_assertions_enabled'] = True
        return result


def dense_target(rows: list[dict], read_beat_cycles: int) -> dict:
    origins = {}
    vector = None
    for row in rows:
        source = common.load(Path(row['verification']['workload']['path']))
        if row['name'] == 'vector_m1':
            common.require(row['shape'] == {'m': 1, 'n': 64, 'k': 64}, 'vector_m1 dimensions differ')
            vector = (row, source)
        for origin in source['source'].get('operators', []):
            if origin['operator'] != 'FULLY_CONNECTED':
                continue
            key = origin['model'], origin['node']
            common.require(key in EXPECTED_FC and key not in origins, 'Unexpected or duplicate Dense origin')
            expected = EXPECTED_FC[key]
            common.require(tuple(origin[name] for name in ('m', 'n', 'k')) == expected and
                           tuple(row['shape'][name] for name in ('m', 'n', 'k')) == expected,
                           'Dense shape differs from the model operator')
            origins[key] = (row, source, origin)
    common.require(set(origins) == set(EXPECTED_FC) and vector is not None,
                   'Expected all five model FC origins and vector_m1')
    items = []
    ordered = [(key, origins[key]) for key in EXPECTED_FC]
    ordered.append((('vector_m1', None), (*vector, None)))
    for (model, node), (row, source, origin) in ordered:
        npu, gemmini = row['npu']['cycles'], row['gemmini']['cycles']
        loop_cycles = row['gemmini'].get('launch_to_complete_cycles', -1)
        tensors = source['tensors']
        minimum_bytes = sum(tensors[name]['bytes'] for name in ('a', 'b', 'bias'))
        minimum_beats = math.ceil(minimum_bytes / 8)
        read_service_cycles = minimum_beats * read_beat_cycles
        npu_limit = 5 * gemmini // 6
        strict_limit = min(npu_limit, 5 * loop_cycles // 6) if loop_cycles >= 0 else None
        timing = row['npu']['timing']
        read_span = timing['last_r'] - timing['first_r'] + 1
        minimum_read_span = (row['npu']['read_beats'] - 1) * read_beat_cycles + 1
        items.append({
            'model': model, 'node': node,
            'model_sha256': origin['model_sha256'] if origin else None,
            'operator': 'FULLY_CONNECTED' if origin else 'synthetic_vector_gemm',
            'workload': row['name'], 'shape': row['shape'],
            'npu_cycles': npu, 'gemmini_cycles': gemmini,
            'speedup': gemmini / npu, 'passed': 6 * npu <= 5 * gemmini,
            'gemmini_first_loop_launch_cycle': row['gemmini'].get('first_launch_cycle'),
            'gemmini_loop_launch_to_complete_cycles': loop_cycles if loop_cycles >= 0 else None,
            'speedup_from_gemmini_loop_launch': loop_cycles / npu if loop_cycles >= 0 else None,
            'passed_from_gemmini_loop_launch': 6 * npu <= 5 * loop_cycles if loop_cycles >= 0 else None,
            'strict_passed': loop_cycles >= 0 and 6 * npu <= 5 * min(gemmini, loop_cycles),
            'strict_maximum_npu_cycles_for_target': strict_limit,
            'integer_check': {'left_6_times_npu': 6 * npu, 'right_5_times_gemmini': 5 * gemmini},
            'loop_launch_integer_check': ({'left_6_times_npu': 6 * npu,
                                           'right_5_times_gemmini': 5 * loop_cycles}
                                          if loop_cycles >= 0 else None),
            'maximum_npu_cycles_for_target': npu_limit,
            'cycles_above_target': max(0, npu - npu_limit),
            'strict_cycles_above_target': max(0, npu - strict_limit) if strict_limit is not None else None,
            'minimum_cold_read_bytes': minimum_bytes,
            'minimum_cold_read_beats': minimum_beats,
            'minimum_read_service_cycles': read_service_cycles,
            'maximum_speedup_at_minimum_read_service': gemmini / read_service_cycles,
            'target_below_minimum_read_service': npu_limit < read_service_cycles,
            'strict_target_below_minimum_read_service': (strict_limit < read_service_cycles
                                                        if strict_limit is not None else None),
            'npu_observed_read_bytes': row['npu']['read_bytes'],
            'npu_observed_read_beats': row['npu']['read_beats'],
            'npu_read_response_span_cycles': read_span,
            'npu_read_response_gap_cycles': read_span - minimum_read_span,
            'npu_cycles_beyond_minimum_read_service': npu - read_service_cycles,
            'gemmini_observed_read_bytes': row['gemmini']['read_bytes'],
            'gemmini_observed_read_beats': row['gemmini']['read_beats'],
            'workload_manifest': row['verification']['workload'],
        })
    return {
        'required_speedup': 1.2,
        'integer_condition': '6 * NPU cycles <= 5 * Gemmini cycles',
        'item_count': len(items), 'real_model_fc_origins': len(EXPECTED_FC),
        'unique_workload_count': len({item['workload'] for item in items}),
        'passed_count': sum(item['passed'] for item in items),
        'passed': all(item['passed'] for item in items),
        'strict_passed_count': sum(item['strict_passed'] for item in items),
        'strict_passed': all(item['strict_passed'] for item in items),
        'strict_condition': 'Each Dense item reaches 1.2x under both complete-command and first-loop-launch Gemmini timing.',
        'gemmini_loop_launch_sensitivity': {
            'item_count': sum(item['gemmini_loop_launch_to_complete_cycles'] is not None for item in items),
            'passed_count': sum(item['passed_from_gemmini_loop_launch'] is True for item in items),
            'scope': 'Gemmini first loop-launch handshake through completion; NPU accepted calc_start through completion.',
        },
        'failed_items': [f"{item['model']}:{item['node']}" if item['node'] is not None else item['model']
                         for item in items if not item['passed']],
        'strict_failed_items': [f"{item['model']}:{item['node']}" if item['node'] is not None else item['model']
                                for item in items if not item['strict_passed']],
        'tensor_scope': 'Shared synthetic tensors with exact model FC dimensions; real model inference is measured separately.',
        'minimum_read_service_scope': 'Uncompressed cold reads of A, B and INT32 bias, packed into full 8-byte beats; excludes command gaps, first response latency, computation and output. Each beat consumes the selected read-service interval.',
        'items': items,
    }


def make_report(args: argparse.Namespace) -> dict:
    report = common.make_report(args, Axi64Comparison)
    report['format_version'] = 2
    report['comparison_verified'] = report['passed']
    report['generator'] = common.artifact(Path(__file__))
    report['sources']['shared_comparison_code'] = common.artifact(Path(common.__file__))
    report['dense_target'] = dense_target(report['gemm'], args.read_beat_cycles)
    leading = [row['name'] for row in report['gemm']
               if row['npu']['cycles'] < row['gemmini']['cycles']]
    report['gemm_target'] = {
        'integer_condition': 'NPU cycles < Gemmini cycles',
        'item_count': len(report['gemm']), 'passed_count': len(leading),
        'passed': len(leading) == len(report['gemm']),
        'failed_items': [row['name'] for row in report['gemm'] if row['name'] not in leading],
    }
    report['all_requested_targets_passed'] = (report['comparison_verified'] and
                                             report['gemm_target']['passed'] and
                                             report['dense_target']['strict_passed'])
    report['reproduction_command'][1] = 'test/gemmini_comparison/compare_axi64_operators.py'
    report['reproduction_command'].extend(['--read-beat-cycles', str(args.read_beat_cycles)])
    report['reproduction_command'].extend(['--first-read-latency', str(args.first_read_latency)])
    report['reproduction_command'].extend(['--inter-burst-gap', str(args.inter_burst_gap)])
    report['bandwidth_definition'] = (
        'Observed bus-service demand = max(read_beats * read_beat_cycles, write_beats). '
        'Reads and writes are independent; narrow transfers still occupy one native bus beat. '
        'The service demand excludes first-response latency and inter-burst gaps.')
    return report


def render_markdown(report: dict) -> str:
    conditions, dense = report['conditions'], report['dense_target']
    interval = conditions['read_beat_cycles']
    role = '每周期一个读数据拍' if interval == 1 else '每两个周期一个读数据拍'
    labels = {'mnist_cnn': 'MNIST CNN', 'mobilenet_v1_vww': 'MobileNetV1 VWW',
              'resnet8_cifar10': 'ResNet-8 CIFAR-10', 'ds_cnn_kws': 'DS-CNN KWS',
              'vector_m1': 'vector_m1'}
    if conditions['external_memory'].get('read_latency_semantics') == 'per_request_from_ar_handshake':
        latency_description = (
            f"每个请求在 AR 握手周期独立记录最早响应时间 `t_AR + {conditions['first_read_latency_cycles']}`。"
            '后续请求可以在前一突发传输期间等待成熟；已经成熟的请求按表中突发转换间隔继续返回，'
            '因此多个 outstanding 请求能够隐藏首拍等待。内存数据在时钟边沿读取并进入响应寄存器。'
            '突发转换间隔表示前一突发最后一个 R 握手边沿与后一突发第一个 R 握手边沿的周期差；'
            '间隔为 1 时，两次握手位于相邻周期，中间没有空闲的数据拍。')
    else:
        latency_description = '本组保留所列首拍延迟和跨突发转换时序，用于独立内存服务的敏感性比较。'
    lines = [f"# 原生 AXI64 独立算子比较：首拍 {conditions['first_read_latency_cycles']} 周期，{role}", '',
        '双方使用 64 bit AXI 数据端口、256 拍最大突发和 4 KiB 边界拆分，'
        '单次完整数据宽度事务最多 2,048 B。主要数据 RAM 均为 65,536 B。'
        '31 个 GEMM、5 个 NPU Conv/DW，以及 Gemmini 的两组 Conv/DW 均通过完整输出验证。'
        '[^npu_gemm][^npu_conv][^gemmini_gemm][^gemmini_native][^gemmini_im2col]', '',
        f"GEMM 逐项领先目标通过 **{report['gemm_target']['passed_count']}/{report['gemm_target']['item_count']} 项**，"
        '每项均直接检查 `NPU 周期 < Gemmini 周期`。', '',
        f"按完整命令计时，Dense 目标通过 **{dense['passed_count']}/{dense['item_count']} 项**；"
        f"同时要求首条循环启动计时也达到目标的严格检查通过 **{dense['strict_passed_count']}/{dense['item_count']} 项**。"
        '每项独立使用整数条件 `6 × NPU 周期 ≤ 5 × Gemmini 周期`，对应至少 1.2×。'
        '五个 FC 层按其真实模型尺寸和节点归属列出；MNIST 的第二个 FC 与 ResNet 的 FC 共用同一尺寸测量。'
        '本组输入与权重为共同生成的整数张量，完整模型的真实输入、权重和逐层量化测试另行统计。', '',
        '## 1. 硬件与内存服务', '',
        '| 项目 | mini_tflm_dsa | DWConv Gemmini |', '|---|---|---|',
        '| 矩阵阵列 | 16 × 16 | 16 × 16 |',
        '| 外部输入 / 权重 / 输出 | INT8 / INT8 / INT8 | INT8 / INT8 / INT8 |',
        '| 矩阵乘法器输入 / 累加结果 | INT16 / INT32 | INT8 / INT32 |',
        '| 主要数据 RAM | 60 KiB + 4 KiB window cache | 32 KiB SP + 32 KiB ACC |',
        '| AXI 数据宽度 / 最大突发 | 64 bit / 256 拍 | 64 bit / 256 拍 |',
        f"| 首个空闲读响应延迟 | {conditions['first_read_latency_cycles']} 周期 | "
        f"{conditions['first_read_latency_cycles']} 周期 |",
        f'| 同一读突发的数据拍间隔 | {interval} 周期 | {interval} 周期 |',
        f"| 已成熟请求之间的读突发转换间隔 | 最少 {conditions['inter_burst_read_gap_cycles']} 周期 | "
        f"最少 {conditions['inter_burst_read_gap_cycles']} 周期 |",
        '| 配置的读 / 写并发请求 | 4 / 4 | 4 / 4 |',
        '| 内存服务同时处理的写事务 | 1 | 1 |',
        '| 写数据拍间隔 | 最少 1 周期 | 最少 1 周期 |',
        '| AW 至首个 W，末个 W 至 B | 各最少 1 周期 | 各最少 1 周期 |',
        '| 输出量化 | ×1/32，最近偶数舍入 | ×1/32，最近偶数舍入 |', '',
        '每次算子测试重新启动仿真并复位加速器。NPU 从接受 `calc_start` 开始计时，'
        'Gemmini 从第一个计时配置命令开始，经过最终 `FENCE` 结束。两者均计入硬件数据搬运、'
        '计算、重新量化和输出写回，并等待全部内存响应。主机指令、布局准备与调度搜索位于本组独立算子计时之外。'
        'Gemmini GEMM 固定使用上游 WS 自动分块；普通卷积同时测量优化后的原生 `LoopConv` 和真实启用的独立 `Im2Col`，'
        'DW 使用第三方专用指令。[^gemmini_build]', '',
        latency_description, '',
        '参考源代码及构建依赖由构建清单中的提交号和 SHA-256 标识。Gemmini 的 DMA 完成字节计数使用 '
        '16 bit，支持到 2,048 B 的事务；相应源代码补丁和编译源文件的 SHA-256 随清单保存。[^gemmini_build]', '',
        '## 2. Dense 逐项 1.2× 目标', '',
        '| 模型 / 节点 | M × N × K | NPU 周期 | Gemmini 周期 | 加速比 | NPU 周期上限 | 达到 1.2× |',
        '|---|---:|---:|---:|---:|---:|---|']
    for item in dense['items']:
        shape = item['shape']
        label = labels[item['model']] + (f" / {item['node']}" if item['node'] is not None else '')
        lines.append(f"| {label} | {shape['m']} × {shape['n']} × {shape['k']} | "
                     f"{item['npu_cycles']:,} | {item['gemmini_cycles']:,} | {item['speedup']:.5f}× | "
                     f"{item['maximum_npu_cycles_for_target']:,} | {'通过' if item['passed'] else '未达到'} |")
    sensitivity = dense['gemmini_loop_launch_sensitivity']
    lines += ['', '### Gemmini 首条循环启动命令的补充计时', '',
        '主表采用 Gemmini 从首条计时配置命令到最终完成的周期。下表同时给出从首条循环启动命令 '
        '`first_launch_cycle` 到完成的周期，NPU 仍从接受 `calc_start` 开始计时。'
        '两种起点均保留原始测量值。[^gemmini_gemm]', '',
        '| 模型 / 节点 | Gemmini 首条循环启动周期 | Gemmini 启动至完成 | NPU 周期 | 加速比 | NPU 周期上限 | 达到 1.2× |',
        '|---|---:|---:|---:|---:|---:|---|']
    for item in dense['items']:
        if item['gemmini_loop_launch_to_complete_cycles'] is None:
            continue
        label = labels[item['model']] + (f" / {item['node']}" if item['node'] is not None else '')
        lines.append(f"| {label} | {item['gemmini_first_loop_launch_cycle']:,} | "
                     f"{item['gemmini_loop_launch_to_complete_cycles']:,} | {item['npu_cycles']:,} | "
                     f"{item['speedup_from_gemmini_loop_launch']:.6f}× | "
                     f"{item['strict_maximum_npu_cycles_for_target']:,} | "
                     f"{'通过' if item['passed_from_gemmini_loop_launch'] else '未达到'} |")
    lines += ['', f"该补充计时达到 1.2× 的项目为 **{sensitivity['passed_count']}/{sensitivity['item_count']}**。"
        'JSON 分别保存完整命令周期与循环启动周期，不将二者混用。']
    long_fc = next(item for item in dense['items'] if item['model'] == 'mnist_cnn' and item['node'] == 5)
    lines += ['', '表中加速比为 `Gemmini 周期 / NPU 周期`。`dense_target.passed` 保存完整命令计时的目标结果，'
        '`dense_target.strict_passed` 要求两种起点均满足目标。'
        '输入、输出与实验条件通过验证记录为 `comparison_verified`；'
        '`all_requested_targets_passed` 同时要求实验条件、全部 GEMM 领先和严格 Dense 目标通过。'
        '[^npu_gemm][^gemmini_gemm]', '',
        '### 长 FC 的读带宽约束', '',
        'MNIST 第一个 FC 的输入为 784 B、权重为 50,176 B、INT32 偏置为 256 B，'
        f"冷启动至少读取 {long_fc['minimum_cold_read_bytes']:,} B，即 {long_fc['minimum_cold_read_beats']:,} 个 8 B 数据拍。"
        f"本组读服务需要至少 {long_fc['minimum_read_service_cycles']:,} 个周期的传输时间；"
        f"完整命令计时下的 1.2× 目标要求 NPU 不超过 {long_fc['maximum_npu_cycles_for_target']:,} 周期。"]
    target_limit = long_fc['strict_maximum_npu_cycles_for_target']
    if target_limit is not None:
        lines += [f"同时满足首条循环启动计时的严格目标要求 NPU 不超过 {target_limit:,} 周期。"]
    else:
        target_limit = long_fc['maximum_npu_cycles_for_target']
    if target_limit < long_fc['minimum_read_service_cycles']:
        lines += ['在本组内存服务、冷启动和未压缩张量条件下，该目标低于必要的读数据传输时间。'
                  '调整分块和重叠流水线可以降低额外等待，但仍须传输这些输入字节。']
    else:
        lines += [f"目标上限比必要读传输时间多 "
                  f"{target_limit-long_fc['minimum_read_service_cycles']:,} 周期。"
                  '可用空间还需要容纳首个响应、突发转换、计算和输出写回；实际结果由完整算子计时给出。']
    lines += ['', '上述传输时间按每个读数据拍占用完整服务间隔计算，不包含命令等待、首个响应和跨突发间隔。'
        '逻辑 MAC 数除以峰值与总周期得到的是吞吐利用率；带宽受限时，该数值较低仍可能伴随持续的数据读取。', '',
    ]
    long_row = next(row for row in report['gemm'] if row['name'] == long_fc['workload'])
    if interval == 1 and long_fc['npu_read_response_gap_cycles'] == 0:
        timing = long_row['npu']['timing']
        lines += [f"该 FC 实测从第 {timing['first_r']:,} 周期到第 {timing['last_r']:,} 周期连续返回 "
            f"{long_fc['npu_observed_read_beats']:,} 个读数据拍，最大同时有 "
            f"{long_row['npu']['read_outstanding_observed']} 个未完成读事务。"
            f"{long_fc['npu_cycles']:,} 个总周期比必要读服务时间多 "
            f"{long_fc['npu_cycles_beyond_minimum_read_service']:,} 个周期；"
            '该差值反映全任务时间与必要读传输时间的差额，计算和写回可以与读取重叠。[^npu_gemm]', '']
    lines += [
        '## 3. 全部 GEMM', '',
        '| 名称 | M × N × K | NPU 周期 | Gemmini 周期 | 加速比 | NPU 数据流 |',
        '|---|---:|---:|---:|---:|---|']
    for row in report['gemm']:
        s = row['shape']
        lines.append(f"| `{row['name']}` | {s['m']} × {s['n']} × {s['k']} | {row['npu']['cycles']:,} | "
                     f"{row['gemmini']['cycles']:,} | {row['speedup']:.4f}× | {row['npu']['dataflow'].upper()} |")
    lines += ['', '## 4. Conv 与 DW', '',
        '| 算子 | NPU 周期 | Gemmini 原生调度 | Gemmini 独立 Im2Col 组 | 相对原生调度 | 相对 Im2Col 组 |',
        '|---|---:|---:|---:|---:|---:|']
    for row in report['convolution']:
        lines.append(f"| `{row['name']}` | {row['npu']['cycles']:,} | {row['gemmini_native']['cycles']:,} | "
                     f"{row['gemmini_im2col']['cycles']:,} | {row['speedup_native']:.4f}× | {row['speedup_im2col']:.4f}× |")
    lines += ['', 'DW 在两组中均走第三方专用 DW 指令；独立 Im2Col 对应普通卷积的硬件输入重排。'
        'JSON 保存每项实际 `loop_depthwise_launches`、`loop_conv_launches` 与独立 Im2Col 请求、响应计数。', '',
        '## 5. 汇总与总线流量', '',
        '| 算子集合 | 项数 | NPU 领先项数 | 总周期加速比 | 几何平均加速比 |', '|---|---:|---:|---:|---:|']
    for name, stats in report['statistics'].items():
        lines.append(f"| `{name}` | {stats['case_count']} | {stats['npu_faster_count']} | "
                     f"{stats['aggregate_cycle_speedup']:.4f}× | {stats['geometric_mean_speedup']:.4f}× |")
    lines += ['', '总周期加速比对应所列算子各执行一次；几何平均加速比对每项算子等权。'
        'JSON 保留各算子的完整周期、首个 AR 到完成、首个 AR 到最后 B 的时间区间，主要比较始终使用完整周期。', '',
        '| Dense 形状 | NPU 读字节 / 拍 / 事务 | Gemmini 读字节 / 拍 / 事务 | NPU 写字节 / 拍 | Gemmini 写字节 / 拍 |',
        '|---|---:|---:|---:|---:|']
    seen = set()
    by_name = {row['name']: row for row in report['gemm']}
    for item in dense['items']:
        if item['workload'] in seen:
            continue
        seen.add(item['workload'])
        row = by_name[item['workload']]
        n, g = row['npu'], row['gemmini']
        lines.append(f"| `{item['workload']}` | {n['read_bytes']:,} / {n['read_beats']:,} / {n['read_requests']:,} | "
                     f"{g['read_bytes']:,} / {g['read_beats']:,} / {g['read_requests']:,} | "
                     f"{n['write_bytes']:,} / {n['write_beats']:,} | {g['write_bytes']:,} / {g['write_beats']:,} |")
    lines += ['', '## 6. 复现与数据文件', '',
        '比较程序检查共同输入和输出 SHA-256、完整输出结果、仿真器与构建清单、参数头、'
        '读写事务排空、实际数据拍计数、最大突发、内存服务间隔以及 Im2Col/DW 活动。', '',
        '```bash', shlex.join(report['reproduction_command']), '```', '',
        '添加 `--require-dense-target` 可在任一 Dense 项未同时满足两种起点下的 1.2× 目标时返回非零状态；'
        '`--require-all-targets` 同时要求全部 GEMM 领先。'
        'JSON 与 Markdown 会在返回之前写出，以保留全部测量结果。', '',
        '| 数据文件 | SHA-256 |', '|---|---|']
    for name, source in report['sources'].items():
        lines.append(f"| `{name}` | `{source['sha256']}` |")
    lines.append('')
    for name, source in report['sources'].items():
        lines.append(f"[^{name}]: `{source['path']}`，SHA-256 `{source['sha256']}`。")
    return '\n'.join(lines) + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=ROOT.parent)
    parser.add_argument('--read-beat-cycles', type=int, choices=(1, 2), default=1)
    parser.add_argument('--first-read-latency', type=int, default=8)
    parser.add_argument('--inter-burst-gap', type=int, default=1)
    defaults = {
        'npu-gemm': 'measurements/axi64/sync_latency8/npu_gemm/summary.json',
        'npu-conv': 'measurements/axi64/sync_latency8/npu_conv/summary.json',
        'gemmini-gemm': 'measurements/axi64/sync_latency8/gemmini_gemm_results/results.json',
        'gemmini-native': 'measurements/axi64/sync_latency8/gemmini_conv_native/results.json',
        'gemmini-im2col': 'measurements/axi64/sync_latency8/gemmini_conv_im2col/results.json',
        'gemmini-build': 'measurements/axi64/sync_latency8/gemmini_build/generated_sp32_acc32_axi64_spdelay1/build_manifest.json',
        'gemmini-gemm-traces': 'measurements/axi64/gemmini_gemm_traces',
        'conv-workloads': 'comparison_conv_workloads_five',
    }
    for key, value in defaults.items():
        parser.add_argument('--' + key, type=Path, default=Path(value))
    parser.add_argument('--json', type=Path, default=ROOT / 'docs/axi64_operators_sync8.json')
    parser.add_argument('--markdown', type=Path, default=ROOT / 'docs/axi64_operators_sync8.md')
    parser.add_argument('--require-dense-target', action='store_true')
    parser.add_argument('--require-all-targets', action='store_true')
    args = parser.parse_args()
    args.data_root = args.data_root.resolve()
    for key in defaults:
        attribute = key.replace('-', '_')
        path = getattr(args, attribute)
        setattr(args, attribute, path.resolve() if path.is_absolute() else (args.data_root / path).resolve())
    report = make_report(args)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    args.markdown.write_text(render_markdown(report))
    print(json.dumps({
        'comparison_verified': report['comparison_verified'],
        'all_requested_targets_passed': report['all_requested_targets_passed'],
        'read_beat_cycles': args.read_beat_cycles,
        'first_read_latency_cycles': args.first_read_latency,
        'inter_burst_read_gap_cycles': args.inter_burst_gap,
        'dense_target_passed': report['dense_target']['passed'],
        'dense_passed_count': report['dense_target']['passed_count'],
        'dense_item_count': report['dense_target']['item_count'],
        'strict_dense_target_passed': report['dense_target']['strict_passed'],
        'strict_dense_passed_count': report['dense_target']['strict_passed_count'],
        'gemm_target_passed': report['gemm_target']['passed'],
        'gemm_passed_count': report['gemm_target']['passed_count'],
        'json': str(args.json.resolve()), 'markdown': str(args.markdown.resolve()),
    }, ensure_ascii=False, indent=2))
    return int((args.require_dense_target and not report['dense_target']['strict_passed']) or
               (args.require_all_targets and not report['all_requested_targets_passed']))


if __name__ == '__main__':
    raise SystemExit(main())
