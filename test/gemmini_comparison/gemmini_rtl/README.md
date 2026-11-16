# Gemmini 完整 RTL 比较

这个目录使用官方 Gemmini 的完整加速器实现，测量共同 GEMM、Conv 和 DW 的执行周期。顶层包含 RoCC 命令入口、循环展开器、调度器、Load/Execute/Store 控制器、scratchpad、accumulator、16×16 阵列和 DMA。外部存储器接口使用官方 RocketChip `TLToAXI4` 和 `AXI4UserYanker` 转换为 32 位 AXI。

`GemminiCompare.scala` 提供物理地址模式下的命令和内存接口，并导出三个控制器的 busy 信号及卷积活动信号用于统计。Gemmini、RocketChip、HardFloat 和 Diplomacy 的官方源代码保持原样。顶层没有实例化宿主 CPU；测量包括加速器配置命令握手、DMA、执行、量化、写回和完成检查。

## 固定依赖

完整版本和提交编号保存在 [dependencies.json](dependencies.json)。测试使用 Java 17、sbt 1.9.7、Scala 2.13.10、Chisel 3.6.1 和 Verilator 5.054，另外需要 Python 3、支持 C++17 的 G++ 和 GNU Make。

| 仓库 | 固定提交 |
|---|---|
| [Gemmini](https://github.com/ucb-bar/gemmini) | `b82d49cca798a59f010488a6f6de7243f0616536` |
| [gemmini-rocc-tests](https://github.com/ucb-bar/gemmini-rocc-tests) | `7ac28e7e7f447d4131db03292de405e5bd978410` |
| [Chipyard 1.12.2](https://github.com/ucb-bar/chipyard/tree/1.12.2) | `dccedae00f4dd626425f8f89c93f55ee11e4193e` |
| RocketChip | `306467d50305a0c0b115e0527f2965583aedea68` |
| HardFloat | `4225367ed282aadd70f4cbd131f6959f4d00c502` |
| Diplomacy | `6b7dc988a771ff21237b102fd02a1f2d2c2e7b72` |
| CDE | `2bcaeae2b9914bd25497ce3c6fa62dc5ca80e09f` |
| FireSim targetutils | `4e0ccc390834876d0f6fb70d69518f3c517cc8b6` |

只需获取表中使用的子模块：

```bash
COMPARE_DEPS=/absolute/path/to/dependencies
git clone --depth 1 --branch 1.12.2 https://github.com/ucb-bar/chipyard.git "$COMPARE_DEPS/chipyard"
git -C "$COMPARE_DEPS/chipyard" submodule update --init --depth 1 generators/rocket-chip generators/hardfloat generators/diplomacy tools/cde sims/firesim
git clone https://github.com/ucb-bar/gemmini.git "$COMPARE_DEPS/gemmini"
git -C "$COMPARE_DEPS/gemmini" checkout b82d49cca798a59f010488a6f6de7243f0616536
git -C "$COMPARE_DEPS/gemmini" submodule update --init --depth 1 software/gemmini-rocc-tests
```

构建脚本检查全部固定提交和已跟踪源文件的完整性，然后把本目录的构建文件复制到指定工作目录。第三方仓库与编译缓存保存在用户指定的位置。

## 构建

从本目录执行：

```bash
python3 build.py \
  --chipyard "$COMPARE_DEPS/chipyard" \
  --gemmini "$COMPARE_DEPS/gemmini" \
  --work-dir /absolute/path/to/gemmini-build \
  --java /absolute/path/to/jdk17/bin/java \
  --verilator /absolute/path/to/verilator \
  --sp-kib 64 --acc-kib 16
```

默认调用 PATH 中的 `sbt`。使用单独的启动脚本时，可以增加 `--sbt python3 /absolute/path/to/sbt.py`。`--jobs` 控制 C++ 并行编译数量。`--reuse-generated` 编译工作目录中已有的 RTL，并检查其参数头与请求的存储容量及硬件配置一致。`--dma-max-bytes` 设置硬件 DMA 最大事务字节数以及 AXI 接口的 `TransferSizes`，默认值为 64；128 字节配置的生成目录和仿真目录分别增加 `_dma128` 后缀。

主要输出为：

- `generated_sp64_acc16/GemminiCompare.sv`：完整 RTL。
- `generated_sp64_acc16/gemmini_params.h`：官方硬件生成的参数头。
- `generated_sp64_acc16/build_manifest.json`：仓库版本、硬件配置、源文件摘要、RTL 摘要和仿真程序摘要。
- `obj_sp64_acc16/VGemminiCompare`：启用 RTL 断言的周期仿真程序。
- `generate_sp64_acc16.log`、`verilate_sp64_acc16.log`：生成和编译日志。

本次比较使用以下四个配置。它们的阵列尺寸、数据精度、DMA 总线宽度和最大未完成请求数相同。

| 配置参数 | Scratchpad | Accumulator | 合计 | 最大 DMA 事务 |
|---|---:|---:|---:|---:|
| `--sp-kib 64 --acc-kib 16` | 64 KiB | 16 KiB | 80 KiB | 64 B |
| `--sp-kib 32 --acc-kib 32` | 32 KiB | 32 KiB | 64 KiB | 64 B |
| `--sp-kib 256 --acc-kib 64` | 256 KiB | 64 KiB | 320 KiB | 64 B |
| `--sp-kib 256 --acc-kib 64 --dma-max-bytes 128` | 256 KiB | 64 KiB | 320 KiB | 128 B |

64 KiB 和 80 KiB 配置用于分析相近存储容量及存储分配，320 KiB 配置用于分析较大存储容量及最大事务长度。存储端口、各区域用途、乘法器位宽及控制器结构分别记录。

固定版本官方生成的 `gemmini_params.h` 把软件 `MAX_BYTES` 定义为 64。硬件 `LoopMatmul` 和 `LoopConv` 的载入分组使用实际 `dma_maxbytes`；OS 软件命令继续使用官方参数头中的分组规则。构建清单的 `configuration.dma_max_bytes` 记录硬件值，命令元数据中的 `config.max_bytes` 记录软件值。官方读响应完成字节数使用 8 位字段，单个响应的有效载荷上限为 255 字节；本次完整数值验证和性能比较使用上述 64 B 与 128 B 配置。

## 生成官方命令并运行

先使用上一级的共同工作负载生成程序准备数据目录，再让 [gemmini_command_trace](../gemmini_command_trace/README.md) 使用对应硬件的参数头生成命令：

```bash
python3 ../gemmini_command_trace/generate.py \
  --gemmini-tests "$COMPARE_DEPS/gemmini/software/gemmini-rocc-tests" \
  --params-header /absolute/path/to/gemmini-build/generated_sp64_acc16/gemmini_params.h \
  --params-origin hardware-generated \
  --workloads /absolute/path/to/comparison_workloads \
  --out /absolute/path/to/gemmini_traces_sp64_acc16

python3 run_cases.py \
  --sim /absolute/path/to/gemmini-build/obj_sp64_acc16/VGemminiCompare \
  --params-header /absolute/path/to/gemmini-build/generated_sp64_acc16/gemmini_params.h \
  --build-manifest /absolute/path/to/gemmini-build/generated_sp64_acc16/build_manifest.json \
  --traces /absolute/path/to/gemmini_traces_sp64_acc16 \
  --output /absolute/path/to/gemmini_results_sp64_acc16
```

对实际 Conv/DW 工作负载使用相同命令，分别指定其数据、命令和结果目录。`--case NAME` 可以选择一个测试，重复使用该参数可以选择多个测试。

每个测试独立启动仿真程序，先复位 8 个周期，再释放复位 4 个周期。`FLUSH` 和初始 `FENCE` 在主计时范围之前执行。仿真程序随后持续提交官方命令，遵守 RoCC ready 信号；每个 `FENCE` 等待 Gemmini busy 解除和全部外部读写事务结束。

## 共同数值运算

GEMM 的数学输入为 `A[M,K]` 和 `B[K,N]`，输入和权重为 INT8，偏置和最终累加结果为 INT32。Gemmini 的阵列输出宽度为 20 位，跨块累加使用 32 位 accumulator。共同数据的 zero-point 为 0，最终计算 `clip(RNE(accumulator / 32), -128, 127)`。Gemmini 使用精确的 FP32 scale `2^-5`，NPU 使用与该比例对应的 Q31 参数。测试数据使中间整数位于 FP32 可以精确表示的范围内。

GEMM 的矩阵布局准备在计时之前完成。实际 Conv/DW 测试直接输入 NHWC 图像，硬件自身的卷积地址生成、补零和数据复用均进入计时范围。三个实际卷积分别覆盖普通 3×3 stride 2，以及 depthwise 3×3 stride 1 和 stride 2。

## 官方卷积功能

配置显式启用 `has_loop_conv`、`has_dw_convs` 和 `has_first_layer_optimizations`。官方 `tiled_conv_auto()` 和 `tiled_conv_dw_auto()` 提交 `LOOP_CONV_WS` 命令，硬件 `LoopConv` 根据 NHWC 图像地址生成窗口读取和边界补零。DW 使用同一循环控制器的 depthwise 模式。

固定版本还保留一个独立的 `Im2Col` 模块；该模块的 `hasIm2Col` 默认关闭，官方当前卷积 API 使用 `LoopConv`。`--im2col` 用于单独构建并检查独立模块的活动，实际取值保存在 `generated_configuration.json` 和构建清单中。卷积结果同时记录 `loop_conv_launches`、`loop_depthwise_launches` 和独立模块的活动周期及请求响应计数。

## 搜索合法 GEMM 分块

`tune_gemm.py` 使用官方 `tiled_matmul()` 枚举合法的 `I,J,K` 块数，同时保留官方自动分块。WS 使用半份 scratchpad 和 accumulator，以支持官方双缓冲；OS 使用其官方容量限制。分块容量断言由官方 C 实现再次检查。

普通存储同时测试 WS 和 OS。另两次搜索分别测试 WS 的 `A[K,M]` 和 `B[N,K]` 存储；数据生成程序改变物理排列并设置对应官方转置位，数学输入与参考输出保持一致。

```bash
python3 tune_gemm.py \
  --gemmini-tests "$COMPARE_DEPS/gemmini/software/gemmini-rocc-tests" \
  --build-root /absolute/path/to/gemmini-build \
  --workloads /absolute/path/to/comparison_workloads \
  --output /absolute/path/to/search_normal \
  --candidates-per-flow 0 --jobs 2

python3 tune_gemm.py \
  --gemmini-tests "$COMPARE_DEPS/gemmini/software/gemmini-rocc-tests" \
  --build-root /absolute/path/to/gemmini-build \
  --workloads /absolute/path/to/comparison_workloads \
  --output /absolute/path/to/search_transpose_a \
  --flows ws --transpose a --candidates-per-flow 0 --jobs 2

python3 tune_gemm.py \
  --gemmini-tests "$COMPARE_DEPS/gemmini/software/gemmini-rocc-tests" \
  --build-root /absolute/path/to/gemmini-build \
  --workloads /absolute/path/to/comparison_workloads \
  --output /absolute/path/to/search_transpose_b \
  --flows ws --transpose b --candidates-per-flow 0 --jobs 2

python3 select_best.py \
  --searches /absolute/path/to/search_normal \
             /absolute/path/to/search_transpose_a \
             /absolute/path/to/search_transpose_b \
  --output /absolute/path/to/selected_schedules
```

`--candidates-per-flow 0` 考虑全部合法块数。每个完成的仿真均检查输出、非输出内存和事务结束状态。`read_traffic.py` 按固定官方 DMA 的地址选择和循环命令展开规则计算读事务；完成的每次仿真都必须与该计算的实际字节数和请求数相同。已经由严格传输周期下界排除的候选不需要继续仿真。其余候选运行到完成，或运行至已经超过当前最快正确结果的周期数。

读取量计算的 `dma_max_bytes` 默认值为 64。搜索程序从构建清单读取实际硬件值：WS 循环按该值展开输入、权重和 INT32 偏置分组；OS 的显式载入命令保留其编码的列数。128 B 搜索先使用同一硬件构建完成数值测试和读取量检查，再使用传输周期下界。例如：

```bash
python3 validate_traffic.py \
  --results /absolute/path/to/gemmini_results_sp256_acc64_dma128/results.json \
  --traces /absolute/path/to/gemmini_traces_sp256_acc64_dma128 \
  --dma-max-bytes 128 --expected-count 31 \
  --out /absolute/path/to/traffic_validation_dma128.json

python3 tune_gemm.py \
  --gemmini-tests "$COMPARE_DEPS/gemmini/software/gemmini-rocc-tests" \
  --build-root /absolute/path/to/gemmini-build \
  --workloads /absolute/path/to/comparison_workloads \
  --profiles sp256_acc64_dma128 \
  --traffic-validation /absolute/path/to/traffic_validation_dma128.json \
  --output /absolute/path/to/search_dma128_normal \
  --candidates-per-flow 0 --jobs 2
```

同样的 `--profiles` 与 `--traffic-validation` 参数用于另两种转置布局。验证文件记录硬件构建摘要、计算程序摘要和逐项实测读取量。`validate_traffic.py` 也接受重复的 `--search-root`，用于检查既有调度搜索中全部完成的 RTL 运行。可选的 `--seed RESULTS_JSON TRACES_DIR` 复用相同硬件、张量和命令上的已测候选，检查内容摘要后作为搜索的初始结果，合法候选范围保持不变。

`--tensor-alignment` 设置每个张量起始地址的字节边界，默认值为 64，与命令生成器的同名参数一致。128 B 硬件分别测试 64 字节和 128 字节边界，每种地址排列使用独立搜索目录及初始内存摘要。`select_best.py` 可以同时读取这些已完成目录，导出的选择记录保留实际地址边界和硬件 DMA 上限。

每种布局的搜索结果保存在独立目录，输入、生成器和硬件摘要用于检查继续执行的搜索是否仍使用相同条件。`select_best.py` 要求三个搜索均完成，检查共同运算定义一致，然后按每个容量配置分别导出最快的已验证官方命令。最后使用 `run_cases.py` 对导出的 `PROFILE/traces` 重新运行，生成常规的逐项结果。

这些搜索覆盖指定存储容量、官方 WS/OS 数据流、三种受支持物理布局以及全部合法 `I,J,K` 块数。报告中的最短时间指这个明确的搜索范围。

## 外部存储器时序

`sim/run_compare.cpp` 的内存状态转换与 NPU `test/conv_npu/axi_memory.sv` 的 `NO_RANDOM_WAIT` 模式相同。

| 项目 | 设置 |
|---|---|
| 数据宽度 | 32 位 |
| Gemmini DMA 最大事务 | 默认 64 字节；320 KiB 配置另测 128 字节 |
| Gemmini DMA 未完成请求上限 | 每个方向 4 个 |
| 读请求等待队列 | 16 个，当前正在服务的请求另计 |
| 空闲读队列 AR 到首个 R 握手 | 3 周期 |
| 同一次突发的 R 握手间隔 | 2 周期 |
| 相邻突发末 R 到首 R 的最小间隔 | 3 周期 |
| 外部写事务数量 | 1 个 |
| AW 到首个 W 的最小间隔 | 1 周期 |
| W 数据吞吐量 | 每周期最多 1 拍 |
| 最后一个 W 到 B 的最小间隔 | 1 周期 |
| 读写关系 | 独立服务，接收端可以施加背压 |

`read_interval=2` 是正式共同测试的设置。该接口保留请求编号，禁止写入输出张量以外的字节，并检查突发传输的大小、边界和 WLAST。

## 输出检查与统计

运行前检查构建清单、仿真程序、参数头、共同工作负载定义、命令、初始内存和参考输出的 SHA-256。运行后检查每个输出字节、全部非输出内存及额外保护区域，并检查全部 AXI 响应已经完成。实际输出保存为 `NAME.output.bin`。

每个 `NAME.json` 包含：

- `cycles`：从首条计时命令提交开始，至最终完成检查所执行的周期数。
- `first_launch_cycle` 与 `launch_to_complete_cycles`：首条官方循环启动命令的位置，以及从该命令到完成的周期数。直接提交执行指令的 OS 路径没有循环启动命令，这两个字段取 `-1`。
- `first_ar_cycle`、`first_r_cycle`、`last_r_cycle`、`first_aw_cycle`、`first_w_cycle`、`last_w_cycle`、`last_b_cycle`：以起始周期编号 0 记录的 AXI 握手时间。
- `read_bytes`、`write_bytes`、`read_requests`、`write_requests`：实际外部事务和数据量。
- `max_read_burst_bytes`、`max_write_burst_bytes`：实际接受的最大 AXI 读、写突发字节数。
- `load_busy_cycles`、`execute_busy_cycles`、`store_busy_cycles`：控制器 busy 周期，各计数可以重叠。
- `observed_output_sha256`、`expected_output_sha256`：实际输出与独立参考输出的摘要。
- `outside_output_mismatches` 与 `memory_drained`：非输出内存保持和外部事务结束的检查结果。
- `workload_manifest_sha256` 与 `build_manifest_sha256`：对应的共同工作负载和实际硬件构建。
- `dataflow`、`operand_storage_transpose`、`explicit_tile`：实际数据流、物理布局转置方式和显式块数。

`effective_mac_utilization` 使用按张量形状计算的逻辑 MAC 数除以 `256 × cycles`，表示整个测试期间相对于阵列峰值的有效吞吐率。它包含传输、配置、执行和写回所占时间。控制器 busy 计数用于分析阶段重叠，不能直接作为每个 PE 的有效乘法计数。

主周期包含 Gemmini 的实际配置命令提交。NPU 在 `calc_start` 接受时一次锁存配置，因此小规模测试还应同时查看循环启动后的周期和首次内存请求时间。两侧均不包含宿主 CPU 指令执行；本目录的结果用于加速器及内存系统比较。
