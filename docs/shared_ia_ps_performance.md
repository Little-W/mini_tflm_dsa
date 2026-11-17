# 共享 IA/PS 的正确性与性能测量

## 硬件配置

测试使用统一 NPU 计算路径，Conv 和 Dense 共享控制器、IA/kernel loader、计算阵列、量化及写回。VCE 处理 DW、池化、Add 和 Softmax，并与矩阵路径共享 DMA 和窗口缓存。

| 参数 | 默认值 | 可选范围 |
|---|---:|---|
| `SIZE` | 16 | 共享 PS 配置使用 16×16 阵列 |
| `NPU_AXI_DATA_WIDTH` | 64 位 | 32、64 位 |
| `SHARED_BANK_BYTES` | 2048 字节 | 1024、2048、4096 字节 |
| `SHARED_BANK_COUNT` | 7 | 6、7、8、9 |
| IA/PS 数据 RAM | 14336 字节 | bank 大小与数量的乘积 |
| PS 目录 | 1024 行 | 与数据 RAM 分别统计 |
| DMA 窗口缓存 | 4 KiB | 完整模型默认配置 |
| VCE PE | 8 | 完整模型默认配置 |

NPU AXI-Lite 配置接口保持 32 位数据和 16 位地址。`NPU_AXI_DATA_WIDTH` 控制张量传输的 AXI4 数据宽度。每个共享 bank 使用独立的同步 128 位 1R1W 存储端口。

软件为每层选择 1、2 或 4 个 IA bank，PS 使用其余 bank。真实 S16 输入至少需要两个 IA bank；跨 K 保存 RAW32 部分和至少需要四个 PS bank，采用 S24 容量上限时至少需要三个 PS bank。S24 上限由输入类型、offset 和归约长度检查。运行中的分配保持固定。

## 比较条件

每一对 RAW32 和 adaptive 测量使用同一个 RTL 可执行文件、同一个固件 ELF、相同模型与输入、相同张量地址和内存时序。固件在 AllocateTensors 和 Prepare 前调用 `dsa_set_ps_force_raw()` 选择 PS 策略；两种策略分别进行参数规划。

两种模式都允许驱动选择合法的 WS/IS、R、W、IA 分配和连续或逐 frame 调度。RAW32 强制使用原始 INT32 部分和；adaptive 根据输入范围与容量选择无损编码或 RAW32。比较包含驱动自动选择的结果，并保留实际配置，以便分析软件规划和硬件执行各自的影响。

物理容量按整个硬件配置核对，包括 IA/PS 数据、PS 目录、解码队列、输出缓冲、窗口缓存及其元数据。压缩后的有效字数用于衡量存储复用，物理 RAM 大小保持为编译时选定的容量。

## 模块与参数检查

```bash
make ps-stream-verify VERILATOR=/path/to/verilator
make shared-memory-test VERILATOR=/path/to/verilator

python3 test/performance_analysis/validate_configuration_bounds.py \
  --out build/ps_compression/configuration_bounds \
  --verilator /path/to/verilator

python3 test/shared_ia_ps/run.py \
  --out build/ps_compression/shared_4096x8 \
  --bank-bytes 4096 --bank-count 8 \
  --verilator /path/to/verilator
```

参数检查覆盖 AXI32/64、全部合法 bank 大小与数量组合、非法配置的能力报告、DMA 长度限制和 4 KiB 分段。共享存储测试检查独立 IA/PS 接口、同周期访问、字节写掩码、容量边界与逐行恢复。NPU 测试用独立整数计算检查最终 INT32 累加值和量化输出，覆盖 WS/IS、S8/S16、尾部、packed 权重以及容量压力调度。

## 完整模型测试

准备模型、参考张量和依赖的方法见 [完整模型测试说明](../test/model_benchmark/README.md)。测试需要 Verilator、RV32IM 裸机 C/C++ 工具链和仓库指定的 PicoRV32 源码。

```bash
export PICORV32_ROOT=/path/to/picorv32
python3 test/ps_compression/run_soc.py \
  --out build/ps_compression/soc_axi64 \
  --prepared /path/to/prepared \
  --gcc /path/to/riscv-none-elf-gcc \
  --verilator /path/to/verilator \
  --bus-width 64 --shared-bank-bytes 2048 --shared-bank-count 7 \
  --pool-bytes 12288 --dataflow 2 --samples 0 1 \
  --kind both --jobs 4 --run-jobs 2
```

默认模型集合为 MNIST CNN、MobileNetV1 VWW、DS-CNN KWS 和 ResNet-8。两个输入、两种 PS 策略、perf/trace 两种执行方式，共产生 32 次 SoC 运行。每次都检查最终输出和模型、输入的只读内容。trace 运行还检查各算子输出与参考张量，并逐行验证 PS 保存、恢复及 frame 生命周期。

perf 运行关闭逐层张量输出，用于完整 Invoke 和 NPU 任务周期测量。trace 运行提供 CPU 算子区间、逐层数值和 PS 事件。点卷积按模型图归入 Conv，即使其物理任务采用 GEMM；`FULLY_CONNECTED` 归入 Dense。

`--latency` 为 RAW32 和 adaptive 设置相同的固定 RAM 延迟。`--resume` 在复用结果前检查模型、输入、固件、RTL、执行类型和内存延迟。更改 RTL 后重新构建仿真器；更改固件或驱动后重新构建对应 ELF。

## 周期与压缩率

| 指标 | 计时或计算范围 |
|---|---|
| `initialization_cycles` | 模型建立、AllocateTensors/Prepare、权重打包、规划及输入复制 |
| `planning_cycles` | 初始化中驱动缓存查询和参数评分的 `rdcycle` 计数 |
| `invoke_cycles` | CPU 调用完整 `Invoke()` 前后，包含提交和等待 |
| Conv/Dense 硬件周期 | NPU 接受任务 START 至该任务完成 |
| Conv/Dense CPU 周期 | trace 的算子开始至结束，包含软件处理和 MMIO |
| PS payload words | 实际保存或恢复的 128 位字数，分别计数 |
| PS RAW32 比例 | `ps_raw_rows / ps_rows` |

相同模型和输入的周期按以下公式汇总：

\[
S = \frac{\sum C_{\mathrm{RAW32}}}{\sum C_{\mathrm{adaptive}}}.
\]

Conv、Dense 和完整 Invoke 分别计算该比值，并分别检查是否达到 1.2×。初始化周期独立列出。若 adaptive 的初始化增加、每次 Invoke 减少，可用增加的初始化周期除以每次 Invoke 节省周期并向上取整，计算累计运行时间开始下降所需的 Invoke 次数。

设保存了 \(L\) 行，每行 16 个 INT32；实际写入 \(P\) 个 128 位字。仅计算数据的压缩率为 \(4L/P\)。同时计入每行 \(D\) 位目录时，表示长度的比值为

\[
\frac{(512+D)L}{128P+DL}.
\]

默认 2 KiB bank 的目录项为 34 位；其他 bank 大小使用实际 RTL 展开得到的目录位宽。保存行数与恢复行数分别报告，PS 事件检查还核对每个保存的 INT32 值、恢复顺序和 frame 释放。编码比例与周期比值分别列出。

## 结果文件

| 文件 | 内容 |
|---|---|
| `settings.json` | 模型、输入、执行类型、RAM 延迟与有效硬件配置 |
| `sim/build.json` | RTL 参数、源码摘要、构建命令及仿真器摘要 |
| 固件目录中的构建记录 | 编译选项、软件源码摘要及 ELF 摘要 |
| `soc_summary.json` | 正确性检查、RAW32/adaptive 配对检查与分类周期 |
| `layers.csv` | 各 Conv/Dense 的配置、硬件周期、PS 字数与外部读取量 |
| `cpu_layers.csv` | CPU 算子周期、NPU 忙碌周期和 MMIO 计数 |
| `timings.csv` | 初始化、规划和 Invoke 周期 |
| 每个用例的 `result.json`、`run.log` | 原始计数、输出检查及日志摘要 |
| 每个用例的 `ps_events.txt` | frame 与 PS 行的保存、恢复事件 |

发布测量结果时同时给出所用提交、有效配置、模型和输入摘要、完整的配对检查以及运行命令。参数变化、驱动变化或存储策略变化对应各自的构建记录和测量结果。
