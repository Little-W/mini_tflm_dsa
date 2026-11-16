#!/usr/bin/env python3
"""Compare complete TFLM inference and layer measurements on the shared Pico SoC."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[2]
MODELS = ('mnist_cnn', 'mobilenet_v1_vww', 'resnet8_cifar10', 'ds_cnn_kws')
LABELS = {'mnist_cnn': 'MNIST CNN', 'mobilenet_v1_vww': 'MobileNetV1 VWW',
          'resnet8_cifar10': 'ResNet-8 CIFAR-10', 'ds_cnn_kws': 'DS-CNN KWS'}
CPU_FIELDS = ('cpu_profile', 'cpu', 'cpu_isa', 'cpu_icache', 'cpu_icache_data_bytes',
              'cpu_enable_mul', 'cpu_enable_fast_mul', 'cpu_enable_div',
              'cpu_enable_regs_dualport', 'cpu_two_stage_shift', 'cpu_barrel_shifter',
              'cpu_two_cycle_compare', 'cpu_two_cycle_alu', 'ram_words', 'bus_width',
              'dma_max_bytes', 'cpu_axi_data_bits','ram_read_first_latency','ram_read_latency_origin','ram_continuous_read_beat_cycles', 'cpu_axi_read_timing_buffer', 'cpu_axi_write_timing_buffer',
              'npu_axi_timing_buffer', 'bypass_ram_pingpong', 'ram_write_timing_buffer')
OP_NAMES = {'CONV_2D': 'Conv', 'DEPTHWISE_CONV_2D': 'DW', 'FULLY_CONNECTED': 'FC',
            'MAX_POOL_2D': 'MaxPool', 'AVERAGE_POOL_2D': 'AveragePool', 'ADD': 'Add',
            'SOFTMAX': 'Softmax', 'RESHAPE': 'Reshape'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path, sources):
    path = Path(path).resolve()
    sources[str(path)] = digest(path)
    return json.loads(path.read_text())


def check_build(build, gemmini=False):
    require(build['returncode'] == 0 and build['sources_unchanged_during_build'],
            'Simulator build must be complete with stable source files')
    profile = build['profile']
    require(profile['dma_max_bytes'] == 2048 and profile['bus_width'] == 64 and profile['cpu_axi_data_bits'] == 32,
            'Expected a native 64-bit AXI bus with 256-beat bursts and a 32-bit Pico path')
    require(profile['cpu_profile'] == 'performance' and profile['cpu_icache_data_bytes'] == 1024,
            'Expected the performance Pico profile with a 1 KiB instruction cache')
    require(profile['ram_read_first_latency']==8 and profile['ram_read_latency_origin']=='accepted_AR' and
            profile['ram_continuous_read_beat_cycles']==1,'Expected an eight-cycle synchronous read with pipelined requests')
    require(profile['ram_words'] == 524288, 'Expected 2 MiB of system RAM')
    if gemmini:
        require(profile['scratchpad_bytes'] == profile['accumulator_bytes'] == 32768,
                'Expected Gemmini SP32/ACC32')
        require(profile['has_im2col'] and profile['has_dwconv_dataflow'] and
                profile['spad_read_delay'] == 1, 'Expected DWConv and hardware Im2Col')
    else:
        require(profile['core'] == 'standard' and profile['size'] == 16 and
                profile['ia_cache_blocks'] == 8 and profile['ps_storage_rows'] == 720 and
                profile['output_banks_s16_max'] == 4 and profile['conv_cache_data_bytes'] == 4096,
                'Expected the 64 KiB NPU main-data-memory profile')


def check_run(run, model, sample, kind, simulator_sha256):
    require(run['passed'] and all(run['checks'].values()), 'Every run check must pass')
    require((run['model_id'], run['sample_index'], run['kind']) == (model, sample, kind),
            'Unexpected model, sample or measurement mode')
    require(run['ram_fixed_lat'] == 0, 'Expected RAM_FIXED_LAT=0')
    require(run['simulator']['simulator_sha256'] == simulator_sha256,
            'A run used a different simulator')
    require(run['result']['invoke_cycles'] > 0 and run['result']['mismatches'] == 0,
            'Inference must complete with an exact final output')
    require(run['output_comparison']['actual_sha256'] == run['output_comparison']['expected_sha256'],
            'Final tensor differs from the reference')
    if kind == 'trace':
        require(len(run['layers']) == run['result']['operator_count'] and
                all(row['passed'] and row['comparison']['mismatches'] == 0 for row in run['trace']),
                'Every graph node and intermediate tensor must be checked')


def identity(run):
    return (run['model']['sha256'], run['input_sha256'],
            run['output_comparison']['expected_sha256'])


def count_outputs(run):
    return len(run.get('trace', []))


def verify_current_sources(npu_build, gem_build, equivalence_path, sources):
    npu_hashes = {path: digest(ROOT / path) for path in npu_build['source_sha256']}
    record = dict(current_npu_source_sha256=npu_hashes, gemmini_current_sources_match=True)
    if npu_hashes == npu_build['source_sha256']:
        record['npu_validation'] = 'Measured source files match the current repository'
    else:
        require(equivalence_path is not None, 'Changed NPU sources require measured equivalence results')
        equivalence = read_json(equivalence_path, sources)
        require(equivalence['passed'] and all(equivalence['checks'].values()) and
                equivalence['original_simulator_sha256'] == npu_build['binary_sha256'] and
                equivalence['original_source_sha256'] == npu_build['source_sha256'] and
                equivalence['proposed_source_sha256'] == npu_hashes and len(equivalence['pairs']) == 8,
                'The current NPU sources must match the checked equivalent implementation')
        record.update(npu_validation=equivalence['comparison'], equivalence=equivalence)
    require(all(digest(path) == value for path, value in gem_build['source_sha256'].items()),
            'Gemmini simulator sources differ from the build record')
    require(all(digest(path) == value for path, value in npu_build['external_dependency_sha256'].items()),
            'An external NPU simulator dependency differs')
    return record


def aggregate(args):
    sources = {}
    npu_build = read_json(args.npu / 'sim/build.json', sources)
    gem_build = read_json(args.gemmini_sim / 'build.json', sources)
    check_build(npu_build)
    check_build(gem_build, gemmini=True)
    require(all(npu_build['profile'][k] == gem_build['profile'][k] for k in CPU_FIELDS),
            'CPU, RAM or system-interface settings differ')
    require(npu_build['picorv32_commit'] == gem_build['picorv32_commit'], 'Pico revisions differ')
    source_validation = verify_current_sources(npu_build, gem_build, args.npu_equivalence, sources)
    npu_summary = read_json(args.npu / 'summary/summary.json', sources)
    require(npu_summary['complete'] and npu_summary['functional_passed'], 'NPU suite is incomplete')
    budget = read_json(args.npu / 'model_budget.json', sources)
    require(budget['passed'], 'NPU budget analysis must pass')
    runs, models, layers, sample_layers = [], [], [], []
    for model in MODELS:
        grouped = defaultdict(list)
        for sample in (0, 1):
            records = {}
            for kind in ('perf', 'trace'):
                for name, mode in (('software', 0), ('npu', 63)):
                    path = args.npu / 'results/cases' / model / f'sample_{sample:04d}' / f'{kind}_{mode}/result.json'
                    run = read_json(path, sources)
                    check_run(run, model, sample, kind, npu_build['binary_sha256'])
                    records[(name, kind)] = run
                for name, directory in (('native', args.gemmini_native), ('im2col', args.gemmini_im2col)):
                    run = read_json(directory / model / f'{sample:04d}' / kind / 'result.json', sources)
                    check_run(run, model, sample, kind, gem_build['binary_sha256'])
                    require(run['convolution_policy'] == name, 'Unexpected Gemmini convolution policy')
                    records[(name, kind)] = run
            ref = identity(records[('software', 'perf')])
            require(all(identity(run) == ref for run in records.values()),
                    'Compared runs must have identical models, inputs and expected outputs')
            for (name, kind), run in records.items():
                runs.append(dict(platform=name, model=model, sample=sample, kind=kind,
                    invoke_cycles=run['result']['invoke_cycles'], initialization_cycles=run['result']['init_cycles'],
                    accelerator_busy_cycles=run['network']['npu_busy_cycles'],
                    checked_intermediate_tensors=count_outputs(run), firmware_sha256=run['firmware_elf_sha256'],
                    simulator_sha256=run['simulator']['simulator_sha256'], model_sha256=ref[0],
                    input_sha256=ref[1], final_output_sha256=ref[2]))
                if kind == 'perf':
                    grouped[name].append(run)
            trace = {name: records[(name, 'trace')] for name in ('software', 'npu', 'native', 'im2col')}
            node_ids = [row['index'] for row in trace['software']['layers']]
            require(all([row['index'] for row in run['layers']] == node_ids for run in trace.values()),
                    'Layer order differs across platforms')
            case = read_json(args.npu / 'results/cases' / model / f'sample_{sample:04d}/trace_63/case.json', sources)
            prepared_path = Path(case['prepared_dir']) / 'manifest.json'
            require(digest(prepared_path) == case['prepared_sha256'], 'Prepared model manifest differs')
            prepared = read_json(prepared_path, sources)
            nodes = {node['index']: node for node in prepared['graph']['nodes']}
            expected = {row['descriptor']['ordinal']: row['comparison']['expected_sha256']
                        for row in trace['software']['trace']}
            for name, run in trace.items():
                require({row['descriptor']['ordinal']: row['comparison']['actual_sha256']
                         for row in run['trace']} == expected, 'Intermediate tensor hashes differ')
            for ordinal, index in enumerate(node_ids):
                node = nodes[index]
                row = dict(model=model, sample=sample, index=index, op=node['op'],
                           input_shapes=node['input_shapes'], output_shapes=node['output_shapes'],
                           options=node.get('options', {}), output_exact=True)
                for name, run in trace.items():
                    observation = run['layers'][ordinal]
                    row[name] = dict(cycles=observation['cycles'],
                        accelerator_busy_cycles=observation['npu_busy_cycles'],
                        read_bytes=observation['npu_read_bytes'], write_bytes=observation['npu_write_bytes'])
                    if name in ('native', 'im2col'):
                        row[name].update(execution_path=observation['execution_path'],
                            commands=observation['commands'], im2col_requests=observation['im2col_requests'],
                            im2col_responses=observation['im2col_responses'])
                sample_layers.append(row)
        row = dict(model=model, samples=2)
        for name, observations in grouped.items():
            row[name] = dict(invoke_cycles=mean(r['result']['invoke_cycles'] for r in observations),
                initialization_cycles=mean(r['result']['init_cycles'] for r in observations),
                accelerator_busy_cycles=mean(r['network']['npu_busy_cycles'] for r in observations),
                arena_used_bytes=mean(r['result']['arena_used_bytes'] for r in observations),
                milliseconds_at_100mhz=mean(r['result']['invoke_cycles'] for r in observations) / 100000)
            row[name]['elapsed_outside_accelerator_busy_cycles'] = (
                row[name]['invoke_cycles'] - row[name]['accelerator_busy_cycles'])
        selected = min(('native', 'im2col'), key=lambda name: row[name]['invoke_cycles'])
        row.update(selected_gemmini_policy=selected,
            npu_speedup_over_software=row['software']['invoke_cycles'] / row['npu']['invoke_cycles'],
            gemmini_speedup_over_software=row['software']['invoke_cycles'] / row[selected]['invoke_cycles'],
            npu_speedup_over_selected_gemmini=row[selected]['invoke_cycles'] / row['npu']['invoke_cycles'])
        models.append(row)
    model_lookup = {row['model']: row for row in models}
    for model in MODELS:
        indices = sorted({row['index'] for row in sample_layers if row['model'] == model})
        for index in indices:
            observations = [row for row in sample_layers if row['model'] == model and row['index'] == index]
            require(len(observations) == 2, 'Each layer needs both inputs')
            first = observations[0]
            row = {key: first[key] for key in ('model', 'index', 'op', 'input_shapes', 'output_shapes', 'options')}
            for name in ('software', 'npu', 'native', 'im2col'):
                row[name] = {key: mean(value[name][key] for value in observations)
                             for key in ('cycles', 'accelerator_busy_cycles', 'read_bytes', 'write_bytes')}
                if name in ('native', 'im2col'):
                    require(len({value[name]['execution_path'] for value in observations}) == 1,
                            'Execution path must be stable across the two inputs')
                    row[name]['execution_path'] = first[name]['execution_path']
                    row[name]['im2col_requests'] = mean(v[name]['im2col_requests'] for v in observations)
                    row[name]['im2col_responses'] = mean(v[name]['im2col_responses'] for v in observations)
            selected = model_lookup[model]['selected_gemmini_policy']
            row.update(selected_gemmini_policy=selected,
                npu_speedup_over_selected_gemmini=row[selected]['cycles'] / row['npu']['cycles'],
                npu_speedup_over_software=row['software']['cycles'] / row['npu']['cycles'], output_exact=True)
            layers.append(row)
    for row in models:
        subset = [value for value in layers if value['model'] == row['model']]
        row['execution_paths'] = {name: dict(Counter(value[name]['execution_path'] for value in subset))
                                  for name in ('native', 'im2col')}
    totals = {}
    for name in ('software', 'npu', 'native', 'im2col'):
        totals[name] = {key: sum(row[name][key] for row in models)
                       for key in ('invoke_cycles', 'initialization_cycles', 'accelerator_busy_cycles',
                                   'elapsed_outside_accelerator_busy_cycles')}
    totals['selected_gemmini'] = {key: sum(row[row['selected_gemmini_policy']][key] for row in models)
                                for key in totals['npu']}
    totals['npu_speedup_over_software'] = totals['software']['invoke_cycles'] / totals['npu']['invoke_cycles']
    totals['npu_speedup_over_selected_gemmini'] = totals['selected_gemmini']['invoke_cycles'] / totals['npu']['invoke_cycles']
    totals['gemmini_speedup_over_software'] = totals['software']['invoke_cycles'] / totals['selected_gemmini']['invoke_cycles']
    categories = []
    for op in dict.fromkeys(row['op'] for row in layers):
        subset = [row for row in layers if row['op'] == op]
        row = dict(op=op, layers=len(subset))
        for name in ('software', 'npu', 'native', 'im2col'):
            row[name] = sum(value[name]['cycles'] for value in subset)
        row['selected_gemmini'] = sum(value[value['selected_gemmini_policy']]['cycles'] for value in subset)
        row['npu_speedup_over_selected_gemmini'] = row['selected_gemmini'] / row['npu']
        categories.append(row)
    dense_samples=[]
    for row in sample_layers:
        if row['op']!='FULLY_CONNECTED':continue
        gemmini_cycles=min(row['native']['cycles'],row['im2col']['cycles'])
        npu_cycles=row['npu']['cycles']
        dense_samples.append(dict(model=row['model'],node=row['index'],sample=row['sample'],
            npu_cycles=npu_cycles,gemmini_cycles=gemmini_cycles,
            speedup=gemmini_cycles/npu_cycles,target_met=6*npu_cycles<=5*gemmini_cycles))
    return dict(schema_version=2, passed=True,
        dense_layer_target=dict(required_speedup=1.2,passed=all(row['target_met'] for row in dense_samples),
            cases=dense_samples,selection='Faster Gemmini policy for each measured FC layer and input'),
        definitions=dict(model_cycles='rdcycle around complete ordinary-firmware TFLM Invoke',
            layer_cycles='Per-node interval in separate trace firmware, including host operator work',
            model_average='Arithmetic mean of two inputs for each model',
            aggregate='Sum of the four model means, equivalent to one invocation of each model',
            relative_speedup='Gemmini cycles divided by NPU cycles; greater than one favors NPU',
            gemmini_selection='One faster complete-model policy per model, chosen by mean ordinary Invoke',
            initialization='Reported separately and excluded from Invoke',
            time_conversion='cycles / 100000 gives milliseconds at an assumed 100 MHz'),
        common_profile={k: npu_build['profile'][k] for k in CPU_FIELDS},
        current_source_validation=source_validation,
        npu_profile=npu_build['profile'], gemmini_profile=gem_build['profile'],
        picorv32_commit=npu_build['picorv32_commit'],
        gemmini_repositories=gem_build['gemmini_build']['repositories'],
        validation=dict(runs=len(runs), trace_tensor_outputs=sum(row['checked_intermediate_tensors'] for row in runs),
            graph_nodes=len(layers), accelerated_conv_dw_fc_nodes=sum(row['op'] in
                ('CONV_2D', 'DEPTHWISE_CONV_2D', 'FULLY_CONNECTED') for row in layers),
            matching_model_input_and_output_hashes=True, matching_common_configuration=True),
        models=models, aggregate=totals, operator_categories=categories, layers=layers, layer_samples=sample_layers,
        target_1000=budget['aggregate'], target_1000_models=budget['models'],
        depthwise_analysis=budget['depthwise'], runs=runs,
        source_files=[dict(path=path, sha256=value) for path, value in sorted(sources.items())],
        generator_sha256=digest(__file__))


def number(value):
    return f'{value:,.0f}' if float(value).is_integer() else f'{value:,.1f}'


def markdown(report):
    out = ['# AXI64 完整模型与逐层比较', '',
        '本报告由 `test/gemmini_comparison/compare_fair_models.py` 从通过检查的仿真结果生成。',
        '完整模型周期取每个模型两个输入的普通固件 `Invoke` 平均值；逐层数据来自独立记录固件。',
        '两种 Gemmini 调度分别执行整个模型，每个模型采用平均完整推理时间较短的一组作为主要比较对象。', '',
        '## 1. 测试配置', '',
        '双方采用性能配置 PicoRV32、1 KiB 指令缓存、2 MiB 系统 RAM、64 bit AXI、最多 256 拍的 INCR 突发，',
        '`RAM_FIXED_LAT=0`，并共用 CPU、RAM、总线仲裁和时序缓冲实现。64 位完整拍传输 8 B，遵守 4 KiB 边界。',
        'CPU 数据通路保持 32 位，主存物理行数相应调整。RAM 同步读取，最早首拍延迟为 8 周期，每周期返回一拍。多个请求从各自的 AR 握手开始计时，就绪的相邻突发之间有 0 个空闲周期。主要数据 RAM 均为 65,536 B。',
        'NPU 使用 16×16 阵列、8 个 VCE PE、`PS_STORAGE_ROWS=720`，共享窗口缓存计入该容量。',
        'Gemmini 使用第三方 DWConv 分支、16×16 阵列、32 KiB scratchpad、32 KiB accumulator，',
        '`spad_read_delay=1`，启用原生 LoopConv、独立硬件 Im2Col 和第三方 DW 数据流。', '',
        'Gemmini 的 `native` 策略采用 LoopConv、WS GEMM 和 DW 数据流；`im2col` 策略让适用空间卷积经过',
        '独立 Im2Col。1×1 且步幅为 1 的卷积和 FC 使用 WS GEMM。每层实际执行路径记录在 JSON 中。', '',
        'DS-CNN 的 10×4 首层卷积使用 LoopConv；该模型两种配置均未发起独立 Im2Col 请求。',
        '两份固件的代码布局、张量地址和访存请求不同，表中保留各自的实测时间。', '',
        '完整模型保留实际零点、偏置、逐通道 Q31 最近偶数舍入和激活范围。Gemmini 返回 INT32，',
        'Pico 执行精确重新量化；Pool、Add 和 Softmax 也在 Pico 上执行。NPU 使用对应硬件算子。',
        '输入整理、命令提交、DMA、重新量化和软件算子的周期均计入 `Invoke`。初始化单独报告。', '',
        '## 2. 完整推理周期', '',
        '| 模型 | 软件 | NPU | Gemmini native | Gemmini Im2Col | 采用的 Gemmini 策略 | 软件/NPU | Gemmini/NPU |',
        '| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |']
    for row in report['models']:
        values = [number(row[name]['invoke_cycles']) for name in ('software', 'npu', 'native', 'im2col')]
        out.append(f"| {LABELS[row['model']]} | " + ' | '.join(values) +
            f" | {row['selected_gemmini_policy']} | {row['npu_speedup_over_software']:.2f}× | {row['npu_speedup_over_selected_gemmini']:.2f}× |")
    total = report['aggregate']
    out += ['| **四模型各一次** | ' + ' | '.join(number(total[name]['invoke_cycles']) for name in
            ('software', 'npu', 'native', 'im2col')) + f" | 按完整模型选择 | **{total['npu_speedup_over_software']:.2f}×** | **{total['npu_speedup_over_selected_gemmini']:.2f}×** |", '',
        '合计加速比使用周期总和相除。100 MHz 下的毫秒数为周期数除以 100,000；频率用于统一换算。', '',
        '## 3. 初始化和首次推理', '',
        '| 模型 | NPU 初始化 | Gemmini 初始化，所选策略 | NPU 初始化 + Invoke | Gemmini 初始化 + Invoke |',
        '| --- | ---: | ---: | ---: | ---: |']
    for row in report['models']:
        n, g = row['npu'], row[row['selected_gemmini_policy']]
        out.append(f"| {LABELS[row['model']]} | {number(n['initialization_cycles'])} | {number(g['initialization_cycles'])} | "
                   f"{number(n['initialization_cycles'] + n['invoke_cycles'])} | {number(g['initialization_cycles'] + g['invoke_cycles'])} |")
    out += ['', '初始化包含 TFLM 分配、Prepare 和静态权重整理。重复推理可以复用初始化结果。', '',
        '## 4. 加速器忙碌时间与完整推理', '',
        '| 模型 | NPU busy | Gemmini native busy | Gemmini Im2Col busy | 所选 Gemmini 完整 Invoke | 所选 Gemmini 未忙碌时间 |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for row in report['models']:
        chosen = row[row['selected_gemmini_policy']]
        out.append(f"| {LABELS[row['model']]} | " + ' | '.join(number(row[name]['accelerator_busy_cycles'])
            for name in ('npu', 'native', 'im2col')) + f" | {number(chosen['invoke_cycles'])} | "
            f"{number(chosen['elapsed_outside_accelerator_busy_cycles'])} |")
    out += ['', 'busy 统计加速器或其 DMA 尚有任务的周期。完整推理还包含主机命令组织、数据处理、',
        '精确重新量化、软件算子和 TFLM 执行开销。未忙碌时间按 Invoke 减去 busy 计算；',
        '各项主机函数的独立时间需要额外函数计时。完整模型加速比描述本表所用 TFLM 适配和相同 Pico 系统，',
        '独立算子报告用于比较计算及 DMA 调度。', '',
        '## 5. 按算子类别统计', '',
        '下表累计逐层记录固件中的算子时间。记录过程会增加开销，因此这里的总和与普通固件完整推理时间分别使用。', '',
        '| 类别 | 节点数 | 软件周期 | NPU 周期 | Gemmini native | Gemmini Im2Col | 所选 Gemmini/NPU |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for row in report['operator_categories']:
        out.append(f"| {OP_NAMES.get(row['op'], row['op'])} | {row['layers']} | " +
            ' | '.join(number(row[name]) for name in ('software', 'npu', 'native', 'im2col')) +
            f" | {row['npu_speedup_over_selected_gemmini']:.2f}× |")
    out += ['', '## 6. 全部模型节点', '',
        '周期为两个输入的平均值。最后一列使用第 2 节为整个模型选择的 Gemmini 策略。', '']
    for model in MODELS:
        out += [f'### {LABELS[model]}', '',
            '| 节点 | 算子 | 输出形状 | 软件 | NPU | Gemmini native | Gemmini Im2Col | Gemmini/NPU |',
            '| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |']
        for row in report['layers']:
            if row['model'] != model:
                continue
            shape = '; '.join('×'.join(map(str, value)) for value in row['output_shapes'])
            out.append(f"| {row['index']} | {OP_NAMES.get(row['op'], row['op'])} | {shape} | " +
                ' | '.join(number(row[name]['cycles']) for name in ('software', 'npu', 'native', 'im2col')) +
                f" | {row['npu_speedup_over_selected_gemmini']:.2f}× |")
        out.append('')
    target = report['target_1000']
    out += ['## 7. 1000× 周期预算', '',
        f"四个模型各执行一次的软件平均总周期为 {number(target['sw_invoke_cycles'])}，",
        f"1000× 对应硬件总周期上限为 {target['allowed_hw_invoke_cycles']:,.3f}。",
        f"当前 NPU 总周期为 {number(target['hw_invoke_cycles'])}。",
        (f"达到目标还需减少 {target['required_reduction_cycles']:,.3f} 周期，即当前时间的 {target['required_reduction_percent']:.4f}%。"
         if target['required_reduction_cycles'] > 0 else '四个模型合计达到 1000× 目标。'), '',
        '| 模型 | 当前 NPU 周期 | 1000× 周期预算 | 需减少周期 | 需减少比例 |',
        '| --- | ---: | ---: | ---: | ---: |']
    for row in report['target_1000_models']:
        out.append(f"| {LABELS[row['model']]} | {number(row['hw_invoke_cycles_mean'])} | "
            f"{row['allowed_hw_invoke_cycles_mean']:,.4f} | {row['required_reduction_cycles_mean']:,.4f} | "
            f"{row['required_reduction_percent']:.2f}% |")
    dw = report['depthwise_analysis']['overall']
    dw_busy = dw['npu_busy_cycles'] / 2
    dw_bound = dw['mac_and_window_width_lower_bound_cycles'] / 2
    max_port4_saving = dw_busy - dw_bound
    out += ['', '## 8. DW 缓存与数据返回速率', '',
        '统计包含 17 个 DW 层、每层两个输入，共 34 条记录。有效 MAC 排除了填充位置。', '',
        '| 指标 | 实测值 |', '| --- | ---: |',
        f"| 有效 MAC | {number(dw['useful_macs'])} |",
        f"| MAC 执行周期 | {number(dw['vector_compute_cycles'])} |",
        f"| 加速器忙碌周期 | {number(dw['npu_busy_cycles'])} |",
        f"| 8 PE 总体有效利用率 | {dw['pe_effective_mac_utilization_percent']:.4f}% |",
        f"| MAC 执行期间的 PE 利用率 | {dw['compute_lane_utilization_percent']:.2f}% |",
        f"| 返回阶段的平均元素数/周期 | {dw['window_elements_per_return_span_cycle']:.4f} |",
        f"| 当前返回宽度 | {dw['window_elements_per_beat']} 个 INT16 元素/周期 |",
        f"| 加权需求命中率 | {dw['demand_hit_rate_percent']:.4f}% |",
        f"| 最低单层需求命中率 | {dw['minimum_layer_demand_hit_rate_percent']:.4f}% |",
        f"| 输入读取字节放大倍数 | {dw['input_read_amplification']:.4f} |",
        f"| 各任务观察到的最大 outstanding | {dw['minimum_peak_outstanding']}～{dw['maximum_peak_outstanding']} |", '',
        '需求命中率按 hits/(hits+misses) 计算，预取请求未计入分母。输入读取字节数包括需求填充与预取填充。',
        '当前日志没有分别统计预取使用、浪费和迟到次数。所有 DW 任务均有多个请求未完成，且请求与响应重叠。', '',
        '每次有效 MAC 对应一个输入元素时，内部返回宽度和 8 个 PE 共同给出连续计算吞吐上限。',
        f"四模型各执行一次时，DW 忙碌时间为 {number(dw_busy)} 周期，MAC 数量和返回宽度给出的下界为 {number(dw_bound)} 周期。",
        f"两者相差 {number(max_port4_saving)} 周期，可用来估计进一步重叠访存、计算和写回的空间。", '',
        '## 9. Dense 逐项目标', '',
        '以下使用每个真实 FC 层、每个输入中时间较短的 Gemmini 策略，检查 `6 × NPU周期 <= 5 × Gemmini周期`。', '',
        '| 模型 | 节点 | 输入 | NPU 周期 | Gemmini 周期 | Gemmini/NPU | 达到 1.2× |',
        '| --- | ---: | ---: | ---: | ---: | ---: | --- |']
    for row in report['dense_layer_target']['cases']:
        out.append(f"| {LABELS[row['model']]} | {row['node']} | {row['sample']} | {number(row['npu_cycles'])} | "
                   f"{number(row['gemmini_cycles'])} | {row['speedup']:.3f}× | {'是' if row['target_met'] else '否'} |")
    out += ['',
        '## 10. 检查结果与文件', '',
        f"共检查 {report['validation']['runs']} 次完整模型执行和 {report['validation']['trace_tensor_outputs']} 个逐层输出张量。",
        f"四个模型共有 {report['validation']['graph_nodes']} 个节点，其中 Conv、DW、FC 共 {report['validation']['accelerated_conv_dw_fc_nodes']} 个。",
        '所有模型、输入、最终输出和逐层张量的 SHA-256 均通过交叉检查，实际 DMA 上限和 CPU 参数与构建记录一致。', '',
        ('当前 standard 核心另以八次硬件完整推理复核，所有结果字段、输出、初始化周期、Invoke 周期、'
         'CPU/DMA 配置、窗口任务和 boot/network 计数器均与主测量一致；源码摘要与复核记录保存在 JSON 中。'
         if 'equivalence' in report['current_source_validation'] else
         '构建时记录的源码摘要与当前实现一致，详细检查结果保存在 JSON 中。'), '',
        '详细结果与源文件 SHA-256：[fair_axi64_models.json](fair_axi64_models.json)。',
        '存储配置：[axi64_configuration.md](axi64_configuration.md)。',
        '独立算子比较：[axi64_operators_sync8.md](axi64_operators_sync8.md)。', '',
        '硬件和软件固定版本：', '']
    for name in ('gemmini', 'gemmini_rocc_tests', 'chipyard'):
        repo = report['gemmini_repositories'][name]
        out.append(f"- {name}: [{repo['commit']}]({repo['url'].removesuffix('.git')}/tree/{repo['commit']})")
    out += [f"- PicoRV32: `{report['picorv32_commit']}`", '']
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--npu', type=Path, required=True)
    parser.add_argument('--gemmini-sim', type=Path, required=True)
    parser.add_argument('--gemmini-native', type=Path, required=True)
    parser.add_argument('--gemmini-im2col', type=Path, required=True)
    parser.add_argument('--npu-equivalence', type=Path,
                        help='Eight-run source-equivalence record when NPU source files have changed')
    parser.add_argument('--out', type=Path, default=ROOT / 'docs/fair_axi64_models.json')
    args = parser.parse_args()
    report = aggregate(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    args.out.with_suffix('.md').write_text(markdown(report))
    print(json.dumps(dict(passed=report['passed'], validation=report['validation'],
                         aggregate=report['aggregate']), ensure_ascii=False))


if __name__ == '__main__':
    main()
