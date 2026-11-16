#!/usr/bin/env python3
"""Render the comparison report from verified release measurements."""
from pathlib import Path
import argparse
import json
import re

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data', type=Path, default=REPO / 'docs/gemmini_measurements.json')
parser.add_argument('--rowmajor', type=Path, required=True)
parser.add_argument('--out', type=Path, default=REPO / 'docs/gemmini_comparison.md')
args = parser.parse_args()
DATA = json.loads(args.data.read_text())
assert DATA['gemmini_depthwise_mapping']['passed']
MODEL = {x['model']: x for x in DATA['models']}
INIT = {x['model']: x for x in DATA['initialization']['models']}
ORDER = ['mnist_cnn', 'mobilenet_v1_vww', 'resnet8_cifar10', 'ds_cnn_kws']
LABEL = dict(zip(ORDER, ['MNIST CNN', 'MobileNetV1 VWW', 'ResNet-8 CIFAR-10', 'DS-CNN KWS']))
BASE_PROFILES = ['sp64_acc16', 'sp32_acc32', 'sp256_acc64']
PROFILES = [r['gemmini_profile'] for r in DATA['operator_totals']]
PROFILE_LABELS = dict(zip(BASE_PROFILES, ['Gemmini SP64+ACC16 KiB，DMA64', 'Gemmini SP32+ACC32 KiB，DMA64', 'Gemmini SP256+ACC64 KiB，DMA64']))
PROFILE_LABELS['sp256_acc64_dma128'] = 'Gemmini SP256+ACC64 KiB，DMA128'

def num(x):
    return f'{x:,.0f}' if int(x) == x else f'{x:,.1f}'

def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                      '| ' + ' | '.join(['---'] * len(headers)) + ' |',
                      *['| ' + ' | '.join(map(str, row)) + ' |' for row in rows]])

aggregate = DATA['aggregate_invoke']
totals = {x['gemmini_profile']: x for x in DATA['operator_totals']}
gemm = {p: {x['name']: x for x in DATA['gemm'] if x['gemmini_profile'] == p} for p in PROFILES}
conv = {p: {x['name']: x for x in DATA['conv'] if x['gemmini_profile'] == p} for p in PROFILES}
best = gemm['sp256_acc64']
sections = {'PRODUCTION_COMMIT': DATA['versions']['mini_modified_production'],
            'PRODUCTION_SHORT': DATA['versions']['mini_modified_production'][:7]}
sections['OVERVIEW'] = (
    f"四个模型各执行一次的硬件总周期为 **{num(aggregate['modified_cycles'])}**，"
    f"相对纯软件的合计加速比为 **{aggregate['modified_software_speedup']:,.2f}×**。"
    f"相对于原始硬件的 {num(aggregate['original_cycles'])} 周期，完整 Invoke 加速比为 "
    f"**{aggregate['hardware_speedup']:.2f}×**。\n\n"
    f"在默认 64 B DMA 上限的三种 Gemmini 存储配置中，31 个共同 GEMM 均由本项目取得较少周期。"
    f"本项目合计 **{num(totals['sp256_acc64']['gemm_npu_cycles'])}**，"
    f"最快配置 Gemmini 合计 **{num(totals['sp256_acc64']['gemm_gemmini_cycles'])}**。"
    "更长 DMA 突发的敏感性结果在第 3、4 节单独报告。"
)
if 'sp256_acc64_dma128' in totals:
    extra=totals['sp256_acc64_dma128']
    sections['OVERVIEW'] += (f"扩大至 128 B 并重新搜索合法分块后，Gemmini 的完整测试集为 "
        f"**{num(extra['gemm_gemmini_cycles'])} 周期**，本项目在 **{extra['gemm_npu_faster_cases']}/31** 项中更快。")
launch_row = best['model_m2304_n8_k27']
tail_row = best['tail17']
sections['TIMING_AND_BURSTS'] = (
    '三种 64 B 配置使用 Gemmini 官方默认 `dma_max_bytes=64`，NPU 支持最长 256 拍、1,024 B 的线性传输，'
    '本组 packed INT8 tile 读取通常为 256 B。两侧接受相同的外部存储器服务，最大 DMA 突发属于各自内部硬件配置。'
    '另外将 Gemmini 最大突发扩大至 128 B，完整搜索调度与输入布局，并测量其实际性能。\n\n'
    '计时同时保留 Gemmini 首条配置至完成、LOOP 启动至完成两项结果。'
    f"64 B 配置中 `M2304,N8,K27` 的 NPU 完整任务为 {num(launch_row['mini_modified_cycles'])} 周期，"
    f"Gemmini 从 LOOP 启动至完成为 {num(launch_row['gemmini_launch_to_complete_cycles'])} 周期。"
    'OS 方式没有 LOOP 启动命令，对应字段为 null，另可比较首次 AR 至完成的时间。'
)
if 'sp256_acc64_dma128' in gemm:
    tight = gemm['sp256_acc64_dma128']['model_m9_n256_k256']
    sections['TIMING_AND_BURSTS'] += (
        f"在 128 B 配置中，`M9,N256,K256` 的 NPU 为 {num(tight['mini_modified_cycles'])} 周期，"
        f"Gemmini 为 {num(tight['gemmini_cycles'])} 周期；去除 LOOP 启动前配置后为 "
        f"{num(tight['gemmini_launch_to_complete_cycles'])} 周期。")
sections['TIMING_AND_BURSTS'] += '\n\n' + DATA['timing_analysis']['report_markdown'].replace(
    '## 共同 GEMM 的计时起点核对', '#### 共同 GEMM 的计时起点核对', 1)
rows = [['当前 NPU', num(totals[PROFILES[0]]['gemm_npu_cycles']), num(totals[PROFILES[0]]['conv_npu_cycles']), '—']]
for p in PROFILES:
    t = totals[p]
    rows.append([PROFILE_LABELS[p], num(t['gemm_gemmini_cycles']), num(t['conv_gemmini_cycles']), f"{t['gemm_npu_faster_cases']}/31"])
sections['OPERATOR_TOTALS'] = table(['执行配置', '31 个 GEMM 总周期', '3 个原生 Conv/DW 总周期', 'NPU 更快的 GEMM 数量'], rows)
native = json.loads(args.rowmajor.read_text())
rows = []
for p in BASE_PROFILES:
    values = [r for r in native['cases'] if r['gemmini_profile'] == p]
    rows.append([PROFILE_LABELS[p], num(sum(r['mini_modified_cycles'] for r in values)),
                 num(sum(r['gemmini_cycles'] for r in values)),
                 str(sum(r['mini_modified_cycles'] < r['gemmini_cycles'] for r in values)) + '/31'])
sections['NATIVE_LAYOUT'] = '各自原生矩阵存储格式、仅优化调度的辅助结果为：\n\n' + table(['Gemmini 配置', 'NPU 总周期', 'Gemmini 总周期', 'NPU 更快项数'], rows)
sections['NATIVE_LAYOUT'] += (
    '\n\n固定官方版本的读响应字节计数为 8 位。扩大 DMA 上限至 256 B 和 1,024 B 后，'
    '分别有 26 个与 19 个形状完成全部数值和内存检查，这些配置的整套总周期保留为 null。'
    '将这些有效单项加入逐形状参考后，本项目的 31 个共同 GEMM 仍全部更快。'
    '各配置、起始地址、实际传输量和逐项记录见 [DMA 参数研究](gemmini_dma_parameters.md)。\n\n'
    '31 项全部更快对应允许打包和物理转置的主要比较组。原生矩阵存储辅助组的结果如上表所示，'
    '其中动态布局转换均没有进入算子计时。完整 TFLM 测试在 Prepare 中打包静态权重，动态输入保持原始格式。'
)

examples = ['tile16', 'tile32', 'tile64', 'tail17', 'model_m784_n8_k9', 'model_m2304_n8_k27',
            'model_m144_n64_k64', 'model_m125_n64_k64', 'model_m1024_n16_k144', 'model_m64_n64_k576', 'model_m1_n64_k784']
rows = []
for name in examples:
    r = best[name]; s = r['matrix_shape']; t = r['mini_modified_tiling']
    extra = [num(gemm['sp256_acc64_dma128'][name]['gemmini_cycles'])] if 'sp256_acc64_dma128' in gemm else []
    rows.append([','.join(num(s[k]) for k in ('m','n','k')), num(r['mini_modified_cycles']), num(r['gemmini_cycles']), *extra,
                 f"{r['mini_modified_dataflow'].upper()}，R{t['ia_reuse']}/W{t['w_reuse']}", r['mini_modified_layout'],
                 ])
sections['GEMM_EXAMPLES'] = table(['M, N, K', 'NPU 周期', 'Gemmini 256+64 KiB，DMA64',
    *(['Gemmini 256+64 KiB，DMA128'] if 'sp256_acc64_dma128' in gemm else []), 'NPU 调度', 'NPU 布局'], rows)
names = ['conv3x3_s2_96_c3_o8', 'dw3x3_s1_48_c8', 'dw3x3_s2_48_c8']
rows = []
for name, label in zip(names, ['普通 3×3，stride 2', 'DW 3×3，stride 1', 'DW 3×3，stride 2']):
    npu = conv[PROFILES[0]][name]['mini_modified_cycles']
    values = [conv[p][name]['gemmini_cycles'] for p in PROFILES]
    rows.append([label, num(npu), *map(num, values), f'{min(values)/npu:.3f}×'])
sections['CONV_RESULTS'] = table(['算子', 'NPU', *[PROFILE_LABELS[p] for p in PROFILES], '相对最快 Gemmini 的速度比'], rows)
rows=[]
for name, label in [('dw3x3_s1_48_c8','DW stride 1'),('dw3x3_s2_48_c8','DW stride 2')]:
    r=min((conv[p][name] for p in PROFILES),key=lambda r:r['gemmini_cycles'])
    for prefix, implementation in [('mini_modified','当前 NPU'),('gemmini','最快 Gemmini 配置')]:
        rows.append([label,implementation,num(r[prefix+'_read_bytes']),num(r[prefix+'_read_requests']),
                     num(r[prefix+'_write_requests']),num(r[prefix+'_cycles'])])
sections['DW_MAPPING'] = (
    '固定官方软件中的 `tiled_conv_dw` 在空间分块内部逐通道调用 `sp_tiled_conv`，'
    '传入 `pochs=1`、`kchs=1` 和 `dw=true`。本次 3×3 DW 同时满足第一层像素打包条件，'
    '实际命令的 `max_pixels_per_row=3`。`LoopConvExecute` 因此形成 '
    '`[I,3]×[3,1]` 的内层运算，其中 `I≤16`，三个卷积核行依次推进并累加到同一输出。'
    '逻辑输出列宽为 1；完整任务的利用率还受空间尾部、阵列推进、装载和写回影响。[3][5]\n\n'
    '实际外部事务数量为：\n\n'
    +table(['算子','实现','读取字节','读请求','写请求','周期'],rows)
    +'\n\nNPU 的 VCE 并行处理通道，窗口缓存保存图像数据，连续通道结果合并写回。'
    '共同 DW 的速度差同时来自这种映射、图像复用以及较少的短传输。'
)
rows = []
for name in ORDER:
    old, new = MODEL[name]['original'], MODEL[name]['modified']
    rows.append([LABEL[name], f"{new['main_array_spatial_occupancy']*100:.2f}%",
                 f"{old['main_array_effective_utilization']*100:.2f}%", f"{new['main_array_effective_utilization']*100:.2f}%",
                 num(new['cpu_outside_npu_busy_cycles']), f"{new['cpu_outside_npu_busy_fraction']*100:.2f}%"])
sections['UTILIZATION'] = table(['模型', '当前空间占用率', '原始任务有效利用率', '当前任务有效利用率', 'Invoke 中 NPU 未忙碌的周期', '占完整 Invoke'], rows)
rows = []
for name in ['model_m1024_n16_k144', 'model_m64_n64_k576']:
    r = best[name]
    for prefix, label in [('mini_original','原始'),('mini_modified','当前')]:
        b, req, cyc = r[prefix+'_read_bytes'], r[prefix+'_read_requests'], r[prefix+'_cycles']
        floor = b/2 + req
        rows.append([name.removeprefix('model_').replace('_',' ').upper(), label, num(b), num(req), num(floor), num(cyc), f'{(cyc/floor-1)*100:.2f}%'])
sections['MEMORY_BOUND'] = table(['形状', '版本', '读取字节', '读请求', '读取服务下界', '实测周期', '高于下界'], rows)
cache = DATA['window_cache']
sections['CACHE_RESULTS'] = cache['report_markdown']
rows = []
for name in ORDER:
    old, new = MODEL[name]['original'], MODEL[name]['modified']
    rows.append([LABEL[name], num(new['software_cycles']), num(old['hardware_cycles']), num(new['hardware_cycles']),
                 f"{new['hardware_cycles']/1e5:.3f}", f"{new['software_speedup']:,.2f}×", f"{MODEL[name]['hardware_speedup']:.2f}×"])
rows.append(['四模型各一次', num(aggregate['software_cycles']), num(aggregate['original_cycles']), num(aggregate['modified_cycles']),
             f"{aggregate['modified_cycles']/1e5:.3f}", f"{aggregate['modified_software_speedup']:,.2f}×", f"{aggregate['hardware_speedup']:.2f}×"])
sections['MODEL_RESULTS'] = table(['模型', '软件周期', '原始硬件周期', '当前硬件周期', '当前耗时，100 MHz / ms', '软件加速比', '相对原始硬件'], rows)
mn, vw = MODEL['mnist_cnn']['modified'], MODEL['mobilenet_v1_vww']['modified']
met = [LABEL[name] for name in ORDER if MODEL[name]['modified']['software_speedup'] >= 1000]
limits = DATA['bottleneck_analysis']['mnist']
sections['TARGET_ANALYSIS'] = (
    '合计推理以及 ' + '、'.join(met) + ' 已超过 1,000×。'
    f"MNIST 的 1,000× 目标为 {limits['target_1000x_cycles']:,.3f} 周期，当前还需减少 "
    f"{limits['required_cycle_reduction']:,.3f} 周期，即 {limits['required_cycle_reduction_fraction']*100:.2f}%。\n\n"
    f"MNIST 的 NPU 忙碌时间为 {num(limits['perf_npu_busy_cycles_mean'])} 周期，"
    f"其余 Invoke 时间为 {num(limits['perf_cycles_outside_npu_busy_mean'])} 周期。"
    f"按七个顺序硬件任务的实际外存字节数，分别计算每周期 4 B 的读取、写入下界并求和，得到 "
    f"{num(limits['serial_jobs_external_payload_floor_cycles'])} 周期。保持当前传输量及 NPU 非忙碌时间时，"
    f"Invoke 下界为 {num(limits['invoke_floor_if_outside_and_external_traffic_unchanged'])} 周期。"
    '达到目标需要同时减少固定软件提交时间并改善卷积供数或减少 FC 实际传输量。'
    'Softmax 硬件、Prepared 提交和静态 Reshape 共享存储均已计入当前结果。'
)
rows = []
for name in ORDER:
    r = INIT[name]; old, new = r['original'], r['modified']
    rows.append([LABEL[name], num(old['init_cycles']), num(new['init_cycles']), num(new['arena_used_bytes']),
                 num(new['initialize_and_invoke_cycles']), str(r['minimum_inferences_to_amortize_initialization'])])
sections['INITIALIZATION'] = table(['模型', '原始初始化周期', '当前初始化周期', '当前 tensor arena / B', '当前初始化加一次 Invoke', '抵消新增初始化所需次数'], rows)
agc = DATA['aggregate_initialization_and_invoke']
sections['COLD_TOTAL'] = (
    f"四模型分别初始化并执行一次，当前硬件合计 {num(agc['modified_cycles'])} 周期，"
    f"相对软件相同计时范围为 {agc['modified_software_speedup']:.2f}×。"
    '持续推理和初始化后只执行一次的结果应按实际使用方式选择。'
)
sections['VALIDATION'] = table(['验证对象', '通过结果'], [
    ['四模型软件/硬件 × 两输入 × 性能/逐层', '32/32，全部输出与逐层张量检查通过'],
    ['NPU 共同算子', '31 GEMM、31 原生矩阵存储格式 GEMM、3 原生 Conv/DW'],
    ['Gemmini 64 B 最优命令独立复跑', '93 GEMM；93 原生存储格式 GEMM；9 原生 Conv/DW'],
    *([['Gemmini 128 B 最优命令独立复跑', '31 GEMM；3 原生 Conv/DW']] if 'sp256_acc64_dma128' in gemm else []),
    ['两套 Prepared 驱动入口', '各 2,197 项；WS-only 兼容设置各 78 项'],
    ['Prepared 运行时启用与张量地址', '64 种启用组合、43,594 项检查；动态张量对象绑定检查'],
    ['静态 Reshape 分配与生命周期', '12 项、28 次重复推理，ASan/UBSan 通过'],
    ['VCE 默认 8 PE 与单 PE', '各 592 项，包括 DW、Pool、Add、Softmax 和错误恢复'],
    ['默认 VCE 性能场景', '23 项，103,668 个输出元素正确'],
    ['窗口描述请求与响应', '421 项接受，417 项完成，4 项由复位取消；随机反压、有序错误及配置切换检查'],
    ['写授权期间的窗口错误', '16 项，覆盖错误报告、完整写回、完成后静止及后续任务'],
    ['缓存需求流水', '36 个配置场景；连续命中、队列反压、缺失、配置排空与复位'],
    ['范围读取与仲裁同周期交接', '452 段读取；768 个双客户端事务，400 次末 R 与下一 AR 同周期握手'],
    ['窗口前端 SIZE16 与 SIZE4', '各 37 项，另有范围、控制及 9 种窗口压力检查'],
    ['调度传输量核对', '31/31 读字节与 31/31 写请求预测等于实际 RTL']
]) + '\n\n组件验证记录分别保存被测模块的源文件摘要与实际覆盖范围；最终 32 次完整 SoC 测量使用同一份仿真程序。'

pipeline = DATA['window_pipeline']
dw = pipeline['depthwise']
assert dw['all_active_jobs_overlap_requests'] and dw['all_active_jobs_overlap_request_response']
sections['WINDOW_PIPELINE'] = (
    f"八次硬件逐层运行共记录 {dw['records']} 个 DW 任务。接受并完成 "
    f"{num(dw['requests'])} 个窗口描述，正确返回 {num(dw['response_elements'])} 个有效元素。"
    f"每个活动任务均观察到请求与响应重叠，最多同时保留 {dw['maximum_peak_outstanding']} 个未完成描述。"
    f"连续响应拍占可相邻响应拍的 {dw['consecutive_response_fraction']*100:.2f}%，"
    f"实际返回区间平均吞吐为 {dw['mean_response_elements_per_span_cycle']:.3f} 个有效元素/周期。"
    '请求数量与元素数量由模型卷积几何独立计算，包含通道片段和边界处理。\n\n'
)
rows=[]
for model, layer in [('mobilenet_v1_vww',1),('mobilenet_v1_vww',3),('ds_cnn_kws',1)]:
    r=next(r for r in pipeline['layers'] if r['model']==model and r['layer_index']==layer)
    rows.append([LABEL[model]+'，层 '+str(layer), num(r['requests']), num(r['response_beats']),
                 str(r['maximum_peak_outstanding']), f"{r['mean_response_elements_per_span_cycle']:.3f}",
                 num(r['npu_busy_cycles'])])
sections['WINDOW_PIPELINE'] += table(['层，两个输入合计', '窗口描述', '响应拍', '最多在途', '有效元素/周期', 'NPU busy'],rows)

bounds = DATA['bottleneck_analysis']['depthwise']['aggregate_two_samples']
lb = bounds['lower_bounds_cycles']
sections['DW_BOUNDS'] = (
    f"这 {dw['records']} 个 DW 任务共完成 {num(bounds['useful_macs'])} 次有效乘加，"
    f"busy 合计 {num(bounds['npu_busy_cycles'])} 周期。按有效 MAC 除以 `8×busy`，"
    f"任务有效 PE 利用率为 {bounds['useful_macs']/(8*bounds['npu_busy_cycles'])*100:.2f}%。\n\n"
    + table(['资源', '周期下界'], [
        ['8 PE，每周期 8 次乘加',num(lb['pe_8_macs'])],
        ['窗口返回，每周期 4 个元素',num(lb['window_return_4_elements'])],
        ['重新量化，每周期一个输出',num(lb['requantize_1_output'])],
        ['重新量化，包含逐组启动及流水线尾部',num(lb['requantize_current_group_pipeline'])],
        ['SoC 外部读取，每周期 4 B',num(lb['external_read_4_bytes'])],
        ['SoC 输出写回，每周期 4 B',num(lb['external_write_4_bytes'])],
    ])
    + '\n\n当前映射每次有效乘加消费一个返回元素，因此 4 元素/周期的接口对应 8 PE 的 50% 长期利用率上限。'
    f"当前 DW busy 总和是返回下界的 {bounds['npu_busy_cycles']/lb['window_return_4_elements']:.3f} 倍。"
    '这一比值只描述这些 DW 任务在当前映射中的改进范围。增加 PE 之前，应优先扩大命中数据交付带宽并减少输出组交接间隔。'
    f"`vector_dma_wait` 中至少 {num(bounds['compute_dma_overlap_cycles_at_least'])} 周期与运算重叠，"
    '该计数不能作为可直接删除的空闲时间。'
)

sections['COMMON_UTILIZATION'] = table(['共同 GEMM 配置', '总周期', '完整任务有效 PE 利用率'],[
    ['当前 NPU' if r['configuration']=='mini_tflm_dsa' else PROFILE_LABELS[r['configuration']],
     num(r['cycles']), f"{r['effective_256_pe_utilization']*100:.3f}%"]
    for r in DATA['bottleneck_analysis']['common_gemm']
])

template = (HERE / 'comparison_report_template.md').read_text()
for key, value in sections.items():
    assert '@@'+key+'@@' in template, key
    template = template.replace('@@'+key+'@@', value)
assert not re.search(r'@@[A-Z_]+@@', template)
target = args.out
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(template)
print(json.dumps({'report': str(target), 'bytes': target.stat().st_size, 'models': len(MODEL)}, ensure_ascii=False))
