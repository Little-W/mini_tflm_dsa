# IA 紧凑读数据重建

`ia_loader_cache_mgr` 按调用者声明的有效偏移位宽重建紧凑数据。`ia_loader` 在 16 位数据配置下使用九位有符号偏移，每列先形成十位有符号和，再扩展为阵列接口的 16 位数据。缓存管理器的参数 `p_compact_offset_width` 默认等于 `DATA_WIDTH`，独立使用时保留完整偏移输入范围。

该实现使用显式加法和符号扩展，本地 RAM 与外部共享 RAM 共用同一段读出算术。寄存器、存储端口、容量、数据格式和所有公开接口周期保持原有行为。

## 偏移范围与配置周期

加载器现有的 `compact_config_valid` 同时要求 `COMPACT_S8 != 0`、`DATA_WIDTH == 16`、`cfg_compact` 有效，以及 `cfg_compact_offset` 位于 -127 至 128。`cfg_compact_q` 和 `compact_offset_q` 在同一个 `init_cfg` 边沿更新，复位时均为零。因此，紧凑模式有效时，偏移高位始终是第八位的符号扩展。

配置接收、忙碌时重新配置及复位过程都沿用上述更新条件。紧凑模式无效时，输出选择原有完整宽度数据。对默认参数缓存模块的形式比较允许任意偏移输入；对完整加载器的形式比较同时包含原有加载器、控制器和缓存管理器，输入不附加取值限制。

## 独立缓存配置

配置为 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`CACHE_BLOCKS=32`、`EXTERNAL_RAM=1`、`RAM_WORD_ADDR_WIDTH=12`。参考源为提交 `b0ccc7a9fefaa4f1f9e53a545cee273d0d8c27b3`。当前实现使用 `p_compact_offset_width=9`，该参数由完整加载器中的配置资格条件支持。

以下结果使用普通 LUT 和进位逻辑映射。逻辑 LUT 数量按映射后、物理共享前的逻辑单元统计，分布式存储单独列出。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 1,979 | 1,896 |
| 分布式 RAM LUT | 8 | 8 |
| 触发器 | 354 | 354 |
| CARRY4 | 130 | 114 |
| DSP | 0 | 0 |
| RAMB18 / RAMB36 | 0 / 0 | 0 / 0 |
| 最长寄存器间组合单元数 | 11 | 11 |
| `ram_port_rd_data` 至 `ia_out` 组合单元数 | 6 | 5 |
| `compact_offset` 至 `ia_out` 组合单元数 | 6 | 5 |
| `compact_mode` 至 `ia_out` 组合单元数 | 1 | 1 |

`measure_read_paths.py` 沿映射网表的实际连接统计输入至输出路径。脚本仅在内存中的分析图加入观察起终点，资源统计和保存的综合网表均保持原样。

## 独立完整加载器配置

两组测量均使用 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`CACHE_BLOCKS=32`、`COUNT_WIDTH=29`、`EXTERNAL_RAM=1`、`ORDERED_JOB=1`。

第一组直接比较 `b0ccc7a` 与本次读数据实现；第二组在配置分块提前计算提交 `e737c0e7ddf4d03e8aab6cc7c0f62e2ae84874cf` 上比较加入本次实现的结果。各组均冻结了加载器、控制器和缓存管理器的参考源与当前源。

| 项目 | 原始配置计算 | 加入读数据实现 | 配置提前计算 | 配置提前计算与读数据实现 |
|---|---:|---:|---:|---:|
| 逻辑 LUT | 5,658 | 5,561 | 5,724 | 5,676 |
| 触发器 | 3,056 | 3,049 | 3,080 | 3,073 |
| CARRY4 | 434 | 418 | 434 | 418 |
| 分布式 RAM LUT | 176 | 176 | 176 | 176 |
| 最长寄存器间组合单元数 | 15 | 15 | 13 | 12 |
| 寄存器至 `ext_dma_start` | 10 | 9 | 10 | 10 |
| 寄存器至 `load_ia_req` | 12 | 14 | 11 | 11 |
| 寄存器至 `ext_dma_p0` / `ext_dma_q0` | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 |

这四个网表均使用普通逻辑映射，DSP 和块 RAM 数量为零。直接比较时，映射后的请求控制路径由 12 个单元变为 14 个单元；与配置提前计算组合后，请求控制保持 11 个单元，模块最长寄存器间路径降为 12 个单元。组合结果属于冻结源码的综合和连接路径测量；两个修改分别保存完整功能证明，整机组合验证由固定版本测试执行。

## 组合 DSP 的物理连接

Round 7 已完成布局的整机中，三个来自缓存读数据重建表达式的组合 DSP 输出连接分别具有 9.330、9.210 和 9.105 ns 的布局距离延迟估计。这三条连接的起点为 `DSP48_X0Y99`、`DSP48_X0Y97`、`DSP48_X0Y98`，终点分别为 `SLICE_X99Y54`、`SLICE_X95Y51`、`SLICE_X97Y60`。原始路径报告、输出端口和源码位置记录在验证 JSON 中。

使用最小算术宽度为 16、DSP 总预算为 740 的独立宽算术映射时，缓存参考实现的 16 列重建加法均可映射为 DSP。当前重建加法低于该宽度，映射报告中候选数为零。

| 宽算术 DSP 映射后的资源 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 1,768 | 1,944 |
| 触发器 | 354 | 354 |
| DSP | 16 | 0 |
| CARRY4 | 66 | 114 |
| 最长寄存器间组合单元数 | 11 | 11 |

此表与普通逻辑映射使用不同的算术映射设置，分别记录其资源变化。整机受全局 DSP 预算影响，原布局选择了其中三个重建加法。当前实现通过缩小有效算术宽度消除这类候选，RTL 使用普通可综合结构。布局距离估计和组合单元数量用于定位路径，150 MHz 结论需要组合实现的实际布局布线时序结果。

## 功能验证

八组完整状态与输出形式比较共证明 40,681 位等价。

| 比较范围 | 配置 | 等价位数 |
|---|---|---:|
| 完整加载器及原始子模块 | 16 列、64 位总线、32 槽、29 位计数、外部 RAM、有序任务 | 11,392 |
| 完整加载器及原始子模块 | 16 列、32 位总线、4 槽、32 位计数、外部 RAM、通用任务 | 9,772 |
| 完整加载器及原始子模块 | 3 列、32 位总线、4 槽、32 位计数、本地 RAM、有序任务 | 6,601 |
| 默认完整偏移宽度缓存 | 4 列、32 位总线、8 位数据、2 槽、本地 RAM | 832 |
| 默认完整偏移宽度缓存 | 8 列、64 位总线、16 位数据、4 槽、本地 RAM | 5,630 |
| 默认完整偏移宽度缓存 | 16 列、32 位总线、16 位数据、32 槽、外部 RAM | 2,066 |
| 默认完整偏移宽度缓存 | 16 列、64 位总线、16 位数据、32 槽、外部 RAM | 2,130 |
| 默认完整偏移宽度缓存 | 16 列、128 位总线、16 位数据、32 槽、外部 RAM | 2,258 |

完整加载器的通用预取、有序预取和 32 槽分组测试完成 583 个命令或场景、237,282 个周期及 1,083,872 次数值比较。全部 39 个公开输出逐周期比较，包括未声明有效时的数据输出。

真实共享 RAM 测试将九位偏移的外部缓存与完整偏移宽度的本地缓存逐周期比较。测试使用 7 个 2 KiB 存储体，覆盖 IA 分配 1、2、4 个存储体以及 PS 使用剩余容量的配置。每种配置遍历 -127 至 128 的全部 256 个紧凑偏移和全部 INT8 位型，支持宽数据的两种配置分别遍历全部 65,536 个 INT16 位型。

该测试通过 3,857,056 次数值比较、19,265,968 次逐周期数据比较和 1,204,123 个周期；其中包含 640 个 IA 同时读写周期、1,200,675 个 IA 与 PS 并行访问周期、1,280 个掩码组合和 7 次槽位回绕。仿真编译检查位宽、锁存器及组合环路告警，并启用 C++ 未定义行为检查。

全部参数、源码摘要、报告摘要、资源和连接路径结果保存在 `docs/data/ia_compact_read_validation.json`。

## 复跑

先载入项目开源工具环境。在本提交的独立工作目录执行以下功能比较：

```sh
python3 test/ia_timing/run_formal.py \
  --reference-rev b0ccc7a \
  --cases loader_ordered29 loader_generic loader_local3 \
  --out build/ia_compact_read/formal
python3 test/ia_write_layout/run_formal.py \
  --reference-ref b0ccc7a --out build/ia_compact_read/cache_formal
python3 test/ia_timing/run_interface.py \
  --reference-rev b0ccc7a --verilator verilator-modern \
  --out build/ia_compact_read/interface
python3 test/ia_shared/run.py \
  --compact-offset-width 9 --verilator verilator-modern \
  --out build/ia_compact_read/shared
python3 test/ia_timing/run_synthesis.py \
  --reference-rev b0ccc7a --count-width 29 \
  --out build/ia_compact_read/loader_synthesis
```

独立缓存综合从验证 JSON 读取相同的参数设置并保存参考源与当前源：

```sh
python3 - <<'PY'
import json
from pathlib import Path
import subprocess

out = Path('build/ia_compact_read/cache_sources')
out.mkdir(parents=True, exist_ok=True)
report = json.loads(Path('docs/data/ia_compact_read_validation.json').read_text())
cases = report['synthesis']['cache_native']['cases']
source_name = 'rtl/npu/loaders/ia_loader_cache_mgr.sv'
for label in ('reference', 'candidate'):
    source = out / (label + '.sv')
    data = (subprocess.check_output(['git', 'show', report['reference_commit'] + ':' + source_name])
            if label == 'reference' else Path(source_name).read_bytes())
    source.write_bytes(data)
    cases['cache_' + label]['sources'] = [str(source)]
(out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
PY
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/ia_compact_read/cache_sources/cases.json \
  --cases cache_reference cache_candidate \
  --out build/ia_compact_read/cache_synthesis
```

开启宽算术 DSP 测量时增加 `--wide-alu-dsp-budget 740 --wide-alu-minimum-width 16`，输出使用独立目录。并行工作环境可给综合命令增加 `--lock-file`，指定项目共用的综合锁文件。

对每个缓存综合网表执行以下命令取得读出路径：

```sh
python3 test/ia_compact/measure_read_paths.py \
  --mapped build/ia_compact_read/cache_synthesis/cache_candidate/mapped.json \
  --pre-lut build/ia_compact_read/cache_synthesis/cache_candidate/pre_lut.il \
  --out build/ia_compact_read/cache_synthesis/cache_candidate/read_paths.json
```

配置提前计算组合测量将 `e737c0e` 的加载器、控制器、缓存管理器作为参考，只在当前副本加入本次缓存改动及加载器参数连接。使用相同的 29 位计数参数运行综合，组合文件摘要记录在 `synthesis.config_tiles_loader_count29.source_sha256` 中。
