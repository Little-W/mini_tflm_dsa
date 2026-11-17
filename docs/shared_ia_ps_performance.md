# 共享 IA/PS 的正确性与性能测量

## 硬件配置

测试使用统一 NPU 计算路径，Conv 和 Dense 共享控制器、IA/kernel loader、计算阵列、量化及写回。VCE 处理 DW、池化、Add 和 Softmax，并与矩阵路径共享 DMA 和窗口缓存。

| 参数 | 默认值 | 可选范围 |
|---|---:|---|
| `SIZE` | 16 | 共享 PS 配置使用 16×16 阵列 |
| `NPU_AXI_DATA_WIDTH` | 64 位 | 32、64 位 |
| `SHARED_BANK_BYTES` | 2048 字节 | 2048、4096、8192 字节 |
| `SHARED_BANK_COUNT` | 7 | 6、7、8、9 |
| IA/PS 数据 RAM | 14336 字节 | bank 大小与数量的乘积 |
| PS 目录 | 1024 行 | 与数据 RAM 分别统计 |
| DMA 窗口缓存 | 4 KiB | 完整模型默认配置 |
| VCE PE | 8 | 完整模型默认配置 |

NPU AXI-Lite 配置接口保持 32 位数据和 16 位地址。`NPU_AXI_DATA_WIDTH` 控制张量传输的 AXI4 数据宽度。每个共享 bank 使用独立的同步 128 位 1R1W 存储端口。

软件为每层选择 1、2 或 4 个 IA bank，PS 使用其余 bank。以完整 S16 行存入 IA RAM 时至少需要两个 IA bank；IS 的流式 IA 保存 S8 权重，可使用紧凑存储。跨 K 保存 RAW32 部分和至少需要四个 PS bank，采用 S24、S16 容量上限时分别至少需要三个、两个 PS bank。S16/S24 容量上限由输入类型、offset、权重和全部保留的 K tile 前缀计算，检查包含中间累加值。运行中的分配保持固定。

FPGA 使用 [`config/npu_fpga.mk`](../config/npu_fpga.mk)，默认七个 8 KiB bank，共 56 KiB。两种配置的完整 RTL 状态量分别为 442,003 位与 998,190 位，同一配置中的 RAW32 和 adaptive 状态量完全相同。状态量包括逻辑数组和顺序状态；共享 RAM 的物理映射单独核对。默认 S8 输出 FIFO 在 2 KiB bank 配置下为 8 KiB，在 8 KiB bank 配置下为 16 KiB，均包含在完整容量统计内。FPGA 和 ASIC 的物理容量见[共享 RAM 映射](shared_ram_mapping.md)。

## 比较条件

每一对 RAW32 和 adaptive 测量使用同一个 RTL 可执行文件、同一个固件 ELF、相同模型与输入、相同张量地址和内存时序。固件在 AllocateTensors 和 Prepare 前调用 `dsa_set_ps_force_raw()` 选择 PS 策略；两种策略分别进行参数规划。

两种模式都允许驱动选择合法的 WS/IS、R、W、IA 分配和连续或逐 frame 调度。RAW32 强制使用原始 INT32 部分和；adaptive 对跨 K 保存的部分和启用无损编码，必要时使用 RAW32 literal。比较包含驱动自动选择的结果，并保留实际配置，以便分析软件规划和硬件执行各自的影响。

物理容量按整个硬件配置核对，包括 IA/PS 数据、PS 目录、解码队列、输出缓冲、窗口缓存及其元数据。压缩后的有效字数用于衡量存储复用，物理 RAM 大小保持为编译时选定的容量。

`RAW32` 表示部分和以原始 INT32 形式保存。`AXI32` 和 `AXI64` 表示外部 DMA 数据总线位宽。以下加速比均为同一硬件配置中的 RAW32 周期除以 adaptive 周期。

## 已完成的测量

测量数据及源码提交记录在 [`measurements/shared_ia_ps_20261116.json`](measurements/shared_ia_ps_20261116.json)。使用 16×16 阵列、四项 AXI 读写在途容量、4 KiB 窗口缓存和带 1 KiB 指令缓存的 PicoRV32。外存从接受 AR 到首拍为 8 周期，随后每周期返回一个数据拍；`ram_fixed_lat=0` 不增加额外随机等待。驱动的读拍评分参数为 1 周期。RAW32 和 adaptive 在初始化前分别选择策略，其余条件相同。

### 批量 64 Dense

矩阵形状为 `M=64, K=784, N=64`。权重、偏置和量化参数来自 MNIST 原始训练模型，输入由 prepared 样本 0 和 1 交替组成 64 行。三种配置均运行生产驱动 AUTO，逐值检查输出及 PS 保存、恢复内容。

| 物理配置 | RAW32 调度 | RAW32 周期 | adaptive 调度 | adaptive 周期 | 加速比 |
|---|---|---:|---|---:|---:|
| AXI32，2 KiB × 7 | WS，IA1，R2 W4 | 38,806 | IS，IA1，R4 W4 | 27,269 | **1.423081×** |
| AXI64，2 KiB × 7 | IS，IA1，R4 W2 | 25,503 | IS，IA1，R4 W4 | 19,580 | **1.302503×** |
| AXI64，8 KiB × 7 | IS，IA1，R4 W4 | 19,580 | IS，IA1，R4 W4 | 19,580 | **1.000000×** |

`IA1` 表示一个 bank 分配给 IA。14 KiB 配置中其余 12 KiB 用于 PS，adaptive 的严格 S24 上限使完整输出窗口能够保留，权重读取量从 100,352 B 减少为 50,176 B。56 KiB 配置为 PS 提供 48 KiB，两种策略都能保留整个窗口，因而采用相同调度。

| 物理配置 | RAW32 读取字节 | adaptive 读取字节 | RAW32 AXI 读拍 | adaptive AXI 读拍 |
|---|---:|---:|---:|---:|
| AXI32，2 KiB × 7 | 151,808 | 101,120 | 37,952 | 25,280 |
| AXI64，2 KiB × 7 | 151,296 | 101,120 | 18,912 | 12,640 |
| AXI64，8 KiB × 7 | 101,120 | 101,120 | 12,640 | 12,640 |

批量测试的 PS payload 均由 49,152 个 128 位字减少到 34,356 个，payload 压缩率为 **1.430667×**。2 KiB bank 使用 34 位目录，含目录记录压缩率为 **1.393301×**；8 KiB bank 使用 42 位目录，含目录记录压缩率为 **1.385433×**。

### AXI 位宽与调度的独立比较

固定 WS 的辅助实验使用同一源码、相同模型张量和内存时序。RAW32 固定 `IA1/R2/W4`，adaptive 固定 `IA1/R4/W4`：

| 位宽 | RAW32 周期 | adaptive 周期 | 加速比 | 减少的读取字节 | 减少的 AXI 读拍 |
|---|---:|---:|---:|---:|---:|
| AXI32 | 38,806 | 27,499 | 1.411179× | 50,688 | 12,672 |
| AXI64 | 25,897 | 19,739 | 1.311971× | 50,688 | 6,336 |

相同的读取字节减少量在 AXI64 上对应一半的数据拍，周期收益随之减小。AUTO 进一步把压缩模式选择为 IS，AXI32 降至 27,269 周期，AXI64 降至 19,580 周期。AXI64 的 RAW32 也从固定 WS 的 25,897 周期降至 25,503 周期。AUTO 分别最小化每种策略的预计耗时。

历史 AXI32 测量为 42,373 / 28,755 周期，即 1.473587×；当前 AXI32 为 38,806 / 27,269 周期。当前 RAW32 与 adaptive 的绝对周期分别减少 8.42% 和 5.17%，两者减少的比例不同，因此压缩加速比为 1.423081×。历史环境使用不同的 CPU 缓存与外存首拍时序模型，该历史数值用于版本记录。固定 WS 辅助实验属于提交 `c905b32b0415d0e35d6902b4f87a09934474cbfd`；最终实现另外构建并重测三种 AUTO 配置。

### 原始 batch 1 Dense

默认 AXI64、2 KiB × 7 配置下，五个 Dense、两个输入和两种策略共 20 个用例全部通过。每个算子的两个输入具有相同周期。

| 模型及算子 | RAW32 周期 | adaptive 周期 | 加速比 |
|---|---:|---:|---:|
| MNIST op5 | 6,715 | 6,715 | 1.000000× |
| MNIST op6 | 231 | 231 | 1.000000× |
| MobileNet op29 | 597 | 597 | 1.000000× |
| DS-CNN op11 | 224 | 224 | 1.000000× |
| ResNet op14 | 218 | 218 | 1.000000× |

这些层的 PS 记录更短，外存读取和任务周期保持相同。三种批量配置与这 20 个原始用例共 26 个用例，检查了 24,968 个输出字节、74,592 条 PS 写入记录及 74,592 条 PS 读取记录。

### 四个完整网络

默认 AXI64、2 KiB × 7 配置使用每个模型的两个输入。下表为 perf 运行的两个输入周期之和；Conv、Dense 按模型图分类，Invoke 包含 CPU 提交、等待及其他算子。

| 模型 | Conv RAW32 | Conv adaptive | Conv 加速比 | Dense RAW32/adaptive | Invoke RAW32 | Invoke adaptive | Invoke 加速比 |
|---|---:|---:|---:|---:|---:|---:|---:|
| MNIST CNN | 42,464 | 42,910 | 0.989606× | 13,892 / 13,892 | 120,827 | 121,273 | 0.996322× |
| MobileNetV1 VWW | 263,668 | 260,212 | 1.013281× | 1,194 / 1,194 | 980,089 | 976,633 | 1.003539× |
| DS-CNN KWS | 58,136 | 50,080 | 1.160863× | 448 / 448 | 327,233 | 319,177 | 1.025240× |
| ResNet-8 CIFAR-10 | 585,172 | 562,978 | 1.039422× | 436 / 436 | 944,539 | 922,345 | 1.024063× |
| 合计 | 949,440 | 916,180 | **1.036303×** | 15,970 / 15,970 | 2,372,688 | 2,339,428 | **1.014217×** |

当前 1.2× 性能目标由 14 KiB 配置的批量 64 Dense 达成。四个原始 batch 1 网络的完整 Invoke 加速比见表。MNIST 的 adaptive Conv 增加 446 周期，此差异保留在网络合计中。

FPGA 的 AXI64、8 KiB × 7 配置另外完成四个模型各一个输入、两种策略的 8 次 trace 运行。64 个矩阵任务在两种策略下的 WS/IS、R/W、IA 分配、外存传输量及任务周期逐项相同；Conv 合计为 466,948 周期，Dense 合计为 7,985 周期，加速比均为 1.0×。该组 trace 的 Invoke 包含逐层张量检查，分别为 1,375,208 周期；它单独保留，不与上表 perf 周期混合计算。

### 压缩率与编码比较

完整网络 trace 的 RAW32 与 adaptive 记录分别验证。以下统计选取 adaptive 实际执行产生的 PS 行与 frame 边界，并用相同 INT32 数据计算 RAW32 表示长度。DW、池化、Add、Softmax 及不保存中间 PS 的任务不计入这些记录。

| 物理配置与语料 | Conv 含目录压缩率 | Dense 含目录压缩率 | 矩阵 PS 合计含目录压缩率 |
|---|---:|---:|---:|
| 2 KiB × 7，四模型各两个输入 | 2.068959× | 1.424348× | 2.066198× |
| 8 KiB × 7，四模型各一个输入 | 2.140556× | 1.442987× | 2.137644× |

默认配置的 16 份 trace 包含两种策略共 292,704 条 PS 记录，逐值重放检查 4,683,264 个 INT32。FPGA 配置的 8 份 trace 包含 153,312 条记录，逐值重放检查 2,452,992 个 INT32。13 种离线比较配置分别检查 60,882,432 和 31,888,896 个 INT32 恢复值。

RTL 使用 COPY、S16/S24 literal、Rice128/256/384、Sparse128 和 RAW32。默认语料中最短的软件候选为 `rice_plus_sparse_bitpack`，相对当前 RTL 表示再减少 736 B，约占含目录记录尺寸的 0.0152%；FPGA 语料中的 `rice_plus_base8` 再减少 2,352 B，占 0.094712%。保留当前 RTL 编码，并提供可重复执行的候选比较工具。候选的压缩记录大小单独统计，硬件周期采用已实现编码器的实测值。

### 模型初始化与 arena

TFLM 在 AllocateTensors/Prepare 中分配持久配置，并计算每层 WS/IS、R/W、IA/PS bank 分配、packed 布局和累加值范围。NMSIS 调用接收配置指针。Invoke 使用保存的配置提交任务。

生命周期测试覆盖 4 个模型、2 个输入和 2 种策略建立的 16 个解释器，每个解释器连续运行 3 次 Invoke，共 48 次。总计保存 240 份配置并使用 720 次 prepared 执行；全部 Invoke 的规划计数、Prepare 计数和 arena 使用量保持不变，720 次配置区域比较及 2,424 次常量区域比较全部一致。arena 用量分别为 MNIST 66,308 B、MobileNet 314,580 B、DS-CNN 49,156 B、ResNet 138,628 B。初始化和规划周期在结果文件中单独报告。

默认配置下，adaptive 相对 RAW32 增加的一次性初始化周期为 MNIST 3,876,578、MobileNet 16,622,365、DS-CNN 4,864,131、ResNet 18,271,580。按同一实例的重复 Invoke 计算，MobileNet、DS-CNN 和 ResNet 分别在第 9,620、1,208 和 1,647 次 Invoke 时抵消增加的初始化耗时；MNIST 的 Invoke 本身增加 223 周期，因此本次测量没有对应的累计时间交点。

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

8 KiB bank 的完整 NPU 测试覆盖 S8 R64 和 S16 输入 R32、连续 K 和 frame 调度，并以固定和随机 AXI 等待分别执行：

```bash
python3 test/shared_ia_ps/run_geometry_npu.py \
  --out build/ps_compression/geometry_8192x7 \
  --bank-count 7 --bus-width 64 --jobs 2 \
  --verilator /path/to/verilator
```

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

### Dense 和压缩语料

批量 64 Dense 使用上述 SoC 模拟器：

```bash
python3 test/ps_compression/sweep_dense_shapes.py \
  --sim build/ps_compression/soc_axi64/sim \
  --prepared /path/to/prepared --gcc /path/to/riscv-none-elf-gcc \
  --out build/ps_compression/dense_batch64 \
  --suite batch --layers mnist_cnn:5 --rows 64 \
  --selection auto --literal-bound --run-jobs 2
```

使用 `--suite actual --samples 0 1` 检查五个原始 Dense，省略 `--layers` 和 `--rows`。AXI32 比较须另行构建 `--bus-width 32` 的模拟器；8 KiB bank 比较使用 `--shared-bank-bytes 8192 --shared-bank-count 7 --pool-bytes 49152` 构建完整 SoC 测试。

完整网络运行完成后，使用该构建的模拟器和 `soc_summary.json` 比较编码：

```bash
python3 test/ps_compression/run_codec_corpus.py \
  --sim build/ps_compression/soc_axi64/sim \
  --summary build/ps_compression/soc_axi64/soc_summary.json \
  --out build/ps_compression/codec_corpus
```

工具核对模拟器、源码、日志和 PS 事件摘要，检查每个恢复值，并为 13 种候选记录 payload 取整、目录开销、opcode 分布和累计记录大小。更换 bank 大小时，目录位宽由实际硬件配置取得。

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
