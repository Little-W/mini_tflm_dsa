# 向量单元共享 RAM：设计与验证

## 实现与存储分配

完整 NPU 在 `SHARED_RAM_ENABLED=1` 时启用 VCE 的 `SHARED_STORAGE_ENABLE`。
DW 权重和量化前的 INT32 结果使用已有 IA/PS RAM，物理 RAM 数量保持为一套。
`vector_shared_store` 提供 128 位权重访问和 512 位部分和访问，支持固定 PS 通道与
轮转 bank 两种生产映射。此共享接口使用 `TILE=16`。

| 数据 | 默认数据容量 | 存储位置 | 访问方式 |
| --- | ---: | --- | --- |
| 当前通道段的 DW 权重 | 784 B | 共享 IA 分区 | IA 端口 0，128 位同步读取，按字节掩码写入 |
| 已完成像素的 INT32 结果 | 64 B | 共享 PS 逻辑行 0 | 四个 128 位端口并行读写 |
| 当前 PE 累加值 | 64 B | `acc_buf` 工作寄存器 | 连续乘加反馈，供池化和向量运算复用 |

接收向量任务的时钟边沿完成 RAM 配置。配置周期禁止数据访问，之后由向量任务
持有端口。默认 49 个卷积核位置、16 个通道只需一个 2 KiB IA bank。
后续矩阵任务使用自己的分配重新配置 RAM；软件继续通过原有描述符启动任务。

完成一个像素时，VCE 将完整 INT32 向量写入 PS，下一周期发起同步读取。
读取有效信号与 RAM 输出同时返回，数据保持到量化输入全部接收。
与此同时，PE 在工作寄存器中继续计算下一像素。量化使用已有本地单路或共享
16 路流水，结果写回仍由原有队列处理。

共享配置的实际展开中，私有权重模块数量为零，私有 `dw_snapshot` 数据声明为空。
未启用共享 RAM 的配置使用本地存储分支，继续支持已有独立实例。
详细时序见[向量计算引擎](vector_engine.md)和[共享 RAM 物理映射](shared_ram_mapping.md)。

## RTL 与软件接口

| 文件 | 职责 |
| --- | --- |
| [vector_shared_store.sv](../rtl/npu/buffers/vector_shared_store.sv) | 地址映射、同步返回、配置及访问范围检查 |
| [vector_engine.sv](../rtl/npu/conv/vector_engine.sv) | 权重读写、PS 结果保存与读取、量化消费和错误处理 |
| [npu_top.sv](../rtl/npu/top/npu_top.sv) | 任务开始时分配 RAM、选择端口来源、等待访问结束及汇总错误 |
| [model.py](../scripts/capacity/model.py) | 共享数据容量与私有数据容量的条件统计 |
| [elaboration.py](../scripts/capacity/elaboration.py) | 实际 RAM 实例、工作寄存器与私有存储移除检查 |

共享存储适配模块只有配置、错误和读取有效状态。本次比较配置的状态总量为
15 位，读取数据直接使用物理 RAM 输出，不增加宽数据暂存阵列。
非法配置、越界访问与同地址同时读写产生错误。顶层等待已接受外存事务结束，
复位内部执行状态并报告错误；后续任务可重新配置并执行。

新增 RTL 和修改部分使用中文注释，端口明确区分输入输出，连接保留模块归属。
仿真、ASIC 和 FPGA 的静态源码清单均包含新模块。

## 容量测量

测量采用与 Gemmini 共同算子比较相同的配置：16×16 矩阵阵列、16 个 VCE PE、
AXI64、8 个 4 KiB 共享 RAM bank、8 KiB 输入缓存、16 个 PS frame 和 RAW32 部分和。
容量包括实际展开的 RAM、ROM、元数据、PE 状态、流水寄存器及门控时钟锁存器。

| 项目 | 数值 |
| --- | ---: |
| 共享 IA/PS 数据 RAM | 32,768 B |
| 迁移前固定通道配置总容量 | 76,885.375 B |
| 当前固定通道配置总容量 | 76,023.375 B |
| 减少的存储与寄存状态 | **862 B** |
| 当前轮转映射配置总容量 | 75,862.875 B |
| 当前固定通道配置距 80 KiB 上限的剩余容量 | 5,896.625 B |

848 B 的私有权重与结果数据移入已有 RAM。计入原权重同步读返回寄存器及一位读取范围状态、
VCE 两位读取状态以及适配模块后，实际净减少 6,896 位，即 862 B。
起始版本 `33c994c` 在独立工作目录中按相同参数实际展开，
71 个源码摘要和全部共同硬件参数均已核对。

完整数据：[固定通道容量](data/vector_shared_ram_20261121/capacity_generic.json)、
[轮转映射容量](data/vector_shared_ram_20261121/capacity_asic.json)、
[本地存储容量](data/vector_shared_ram_20261121/capacity_private.json)、
[起始版本容量](data/vector_shared_ram_20261121/capacity_reference_generic.json)、
[版本与参数检查](data/vector_shared_ram_20261121/capacity_reference_check.json)。

## 共同算子性能

45 项共同硬件算子全部通过逐元素验证，并全部满足相对 Gemmini 至少 1.2 倍的要求。
31 项 GEMM 和 3 项普通卷积的周期数与原结果相同。11 项 DW 每个通道组增加一个
周期，整层增加 1 至 16 个周期，最大周期增幅为 0.323363%。

外存条件为 AXI64、首个读响应至少 8 周期、连续读取每周期一拍、最大 burst 2 KiB。
计时从接受启动请求开始，到加速器完成且 AXI 响应结束为止。
Gemmini 时间来自已有专用 DW 分支的[共同算子结果](data/dw_shared_quant_20261121/operator_targets.csv)。
迁移前的 11 项 DW 使用
`33c994c` 在相同输入和配置下重新执行，周期与保存结果完全一致。

| DW 算子 | 迁移前周期 | 共享 RAM 周期 | 增加周期 | Gemmini 周期 | 相对 Gemmini |
| --- | ---: | ---: | ---: | ---: | ---: |
| `dw3x3_s1_48_c8` | 24,145 | 24,146 | +1 | 32,705 | 1.354469× |
| `dw3x3_s2_48_c8` | 10,216 | 10,217 | +1 | 17,802 | 1.742390× |
| `model_dw3x3_s1_25x5_c64` | 6,520 | 6,524 | +4 | 14,089 | 2.159565× |
| `model_dw3x3_s2_48x48_c16` | 9,816 | 9,817 | +1 | 19,689 | 2.005603× |
| `model_dw3x3_s1_24x24_c32` | 12,496 | 12,498 | +2 | 17,837 | 1.427188× |
| `model_dw3x3_s2_24x24_c32` | 7,790 | 7,792 | +2 | 10,733 | 1.377438× |
| `model_dw3x3_s1_12x12_c64` | 7,688 | 7,692 | +4 | 9,837 | 1.278861× |
| `model_dw3x3_s2_12x12_c64` | 5,258 | 5,262 | +4 | 6,813 | 1.294755× |
| `model_dw3x3_s1_6x6_c128` | 5,263 | 5,271 | +8 | 6,365 | 1.207551× |
| `model_dw3x3_s2_6x6_c128` | 3,212 | 3,220 | +8 | 4,645 | 1.442547× |
| `model_dw3x3_s1_3x3_c256` | 4,948 | 4,964 | +16 | 6,573 | 1.324134× |

DW 最低比率为 `6×6 C128 stride 1` 的 **1.207551×**。
全部 45 项中的最低比率为 `model_m1_n64_k784` 的 **1.202988×**，对应 NPU
6,493 周期和 Gemmini 7,811 周期。

完整结果：[45 项性能表](data/vector_shared_ram_20261121/operator_comparison.csv)、
[性能汇总](data/vector_shared_ram_20261121/performance_summary.json)、
[GEMM 逐项结果](data/vector_shared_ram_20261121/operators_gemm.json)、
[Conv/DW 逐项结果](data/vector_shared_ram_20261121/operators_conv.json)、
[仿真构建记录](data/vector_shared_ram_20261121/operator_build.json)。
`33c994c` 的 45 项参考算子也已实际执行，记录见
[参考 GEMM](data/vector_shared_ram_20261121/reference_operators_gemm.json)、
[参考 Conv/DW](data/vector_shared_ram_20261121/reference_operators_conv.json)和
[参考构建记录](data/vector_shared_ram_20261121/reference_operator_build.json)。

## 功能与错误恢复验证

| 验证范围 | 配置与数量 | 结果 |
| --- | --- | --- |
| 共享存储适配器 | 13 种配置，2/4/8 KiB bank、6 至 9 个 bank、全部合法 IA 分配、两种映射 | 全部通过 |
| VCE 共享存储与共享量化 | PE16、AXI64、16 路窗口，615 个场景、172,195 个输出 | 全部通过 |
| VCE 共享存储与本地量化 | PE8、AXI32、4 路窗口，615 个场景、170,802 个输出 | 全部通过 |
| VCE 本地存储兼容配置 | PE8、AXI32，615 个场景、170,971 个输出 | 全部通过 |
| 窗口错误与恢复 | 16 次错误和 16 次恢复任务 | 全部通过 |
| 生产 C 驱动与固定通道顶层 | 固定、随机延迟各 106 个场景、57,673 个输出 | 全部通过 |
| 生产 C 驱动与轮转映射顶层 | 固定、随机延迟各 106 个场景、57,673 个输出 | 全部通过 |
| 容量统计与结构检查 | 108 项单元测试，三种实际 RTL 展开配置 | 全部通过 |

适配器测试共执行 103,082 个周期，检查 254,683 次 128 位读取，比较
4,074,928 个字节。测试覆盖连续访问、字节掩码、数据保持、地址边界、读写冲突、
重新配置、复位以及另一任务写入后由 VCE 读回。

真实顶层使用生产驱动与实际 AXI-Lite、NPU 和 AXI RAM。测试读取 CSR 确认
1、2、4 个 IA bank 的实际选择，并交替执行 GEMM、Conv、DW 和池化。
三类实际 AXI 错误覆盖权重读取、输入读取和结果写入；另外检查适配器和物理 RAM
错误。每次错误之后均在不复位整个设备的情况下继续执行并验证后续数值任务。

两种顶层映射通过 Verilator 检查，没有锁存器、多重驱动或组合环路警告。
新增适配模块的 `--lint-only --Wall` 检查无警告。
功能验证与性能运行使用 Verilator 5.054，构建记录保存源码和执行文件摘要。

完整验证文件：[统一汇总](data/vector_shared_ram_20261121/verification.json)、
[适配器](data/vector_shared_ram_20261121/adapter_validation.json)、
[VCE](data/vector_shared_ram_20261121/vce_validation.json)、
[固定通道联合仿真](data/vector_shared_ram_20261121/cosim_generic.json)、
[轮转映射联合仿真](data/vector_shared_ram_20261121/cosim_asic.json)。

## 当前上游兼容验证

当前实现包含远端 `main` 的 `33c994c`。写回组合移位、预测器索引和上游测试修改
均已保留。预测器正常与运行中重新配置两种模式各检查 40 组配置、13,303 个向量；
AXI32、AXI64 写回各执行 30,000 周期的逐周期比较。DMA 响应排空、连续任务及
门控时钟复位测试全部通过。完整记录见
[上游兼容检查](data/vector_shared_ram_20261121/upstream_review.json)。

## 复现入口

共享适配器：

```bash
python3 test/vector_shared_store/run.py \
  --verilator /path/to/verilator --out build/vector_shared_store
```

共享存储与 16 路量化：

```bash
python3 test/vector_engine/run.py \
  --verilator /path/to/verilator --out build/vector_shared_storage_pe16 \
  --pes 16 --bus-width 64 --window-lanes 16 --shared-quant --shared-storage \
  --cache-line-bytes 128 --cache-sets 32 --jobs 2
```

生产驱动与共享 RAM 顶层：

```bash
python3 test/vector_engine_cosim/run.py \
  --verilator /path/to/verilator --out build/vector_engine_cosim_shared \
  --pcr --size 16 --pe-count 16 --bus-width 64 \
  --bank-bytes 4096 --bank-count 8 --cache-bytes 8192 --target generic --jobs 2
```

轮转映射使用 `--target asic`。两种实现均检查随机延迟实际启用的状态。
容量检查使用 `test/capacity/check_elaboration.py`。

共同算子的输入由已提供的 `npu_gemmini_bird_axi64_80k_20261117.tar.xz`
恢复，并通过模型几何补充 DW 场景：

```bash
NPU_REFERENCE_ROOT=/path/to/npu_gemmini_bird_axi64_80k_20261117
python3 test/gemmini_comparison/prepare_model_dw.py \
  --prepared "$NPU_REFERENCE_ROOT/prepared" \
  --existing-workloads "$NPU_REFERENCE_ROOT/workloads" \
  --out build/vector_shared_workloads --seed 20261121

python3 test/gemmini_comparison/run_storage_operators.py \
  --repo . --reference-root "$NPU_REFERENCE_ROOT" \
  --workloads build/vector_shared_workloads \
  --out build/vector_shared_operators --verilator /path/to/verilator \
  --bank-bytes 4096 --bank-count 8 --cache-bytes 8192 --pe-count 16 --jobs 2
```

完整参数、源码摘要与命令保存在对应 JSON 记录中。
