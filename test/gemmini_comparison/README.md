# Gemmini 与 mini_tflm_dsa 共同算子测试

本目录使用相同的数学输入、权重、偏置和参考输出，测量两个加速器完成同一算子的周期。GEMM、普通卷积和逐通道卷积（Depthwise）分别统计。输入数据为确定性的合成整数；其中 GEMM 的模型形状从四个准备完成的 TFLite 模型中提取。

主测试使用原生 64 bit AXI、相同的 64 KiB 主数据 RAM、同步内存的 8 周期首拍延迟和每周期一个读数据拍。配置说明见 [AXI64 实验配置](../../docs/axi64_configuration.md)，逐项结果见 [AXI64 算子比较](../../docs/axi64_operators_sync8.md)。

## 数值计算

输入和权重均为有符号 INT8，取值范围为 −3 至 3；偏置为 INT32，取值范围为 −8 至 8。所有零点为 0。每个输出先完成 INT32 累加，再计算：

\[
y=\operatorname{clip}_{[-128,127]}\left(\operatorname{RNE}\left(\frac{a}{32}\right)\right).
\]

`RNE` 表示舍入到最近整数，中点舍入到偶数。Gemmini 使用精确的 FP32 比例 `0.03125`；mini_tflm_dsa 使用 `multiplier=1073741824`、`shift=-4`。生成程序验证所有累加值的绝对值小于 \(2^{24}\)，并保留 INT32 与 INT8 两种参考输出。NumPy INT64 计算通过独立的标量点积或卷积循环进行交叉检查。

每个张量文件都附带数据类型、形状、字节数、存储顺序和 SHA-256。两侧运行结果必须引用相同的 `case.json` 指纹。NPU 测试比较完整外部内存，既验证输出，也检查其他内存内容保持原值。

## GEMM

`prepare.py` 读取准备完成的四个模型的 `manifest.json`，生成 26 个互不相同的 Conv/FC 矩阵形状和 5 个基本形状：16、32、64 阶方阵，带尾部的 `17×19` 乘 `19×23`，以及 `M=1,N=64,K=64`。同一形状的所有原模型位置均保留在来源信息中。

数学定义为 `A[M,K] × B[K,N] + bias[N]`。共享权重 `b_s8.bin` 按 `[K,N]` 排列；NPU 的普通权重布局按 `[N,K]` 排列。NPU 还支持 `[ceil(rows/16),ceil(K/16),16,16]` 的块状布局，最后一维对应归约维度 K，补充元素为零。布局转换在计时前完成。此项测量包含加速器内部的数据装载、计算、量化和输出写回。

卷积转换为矩阵的计算在这组测试的计时之前完成。它衡量矩阵执行效率；实际卷积的输入窗口生成由下一组测试测量。

```bash
python3 test/gemmini_comparison/prepare.py \
  --prepared "$PREPARED_MODELS" --out build/common_gemm_workloads

python3 test/gemmini_comparison/run_mini.py \
  --repo . --workloads build/common_gemm_workloads \
  --out build/common_gemm_modified --verilator "$VERILATOR" --jobs 2 \
  --cache-sets 128 --cache-policy 3 --ia-cache-blocks 8 \
  --ps-frames 16 --ps-storage-rows 720 --s16-output-banks 4 \
  --bus-width 64 --read-beat-cycles 1 \
  --memory-timing pipelined --first-read-latency 8 \
  --schedule auto --dataflow auto --layout auto
```

上述命令显式指定本组的存储容量与内存时序。`--layout auto` 使用驱动的同一成本模型比较普通布局、仅打包 A、仅打包 B 和同时打包两者；每个布局分别枚举合法的 WS/IS、IA 复用数 R 和权重复用数 W。结果保留各候选布局的估算值和选中的实际配置。`--layout row-major`、`lhs-packed`、`rhs-packed`、`both-packed` 可以固定布局，`--dataflow ws/is` 可以固定数据流。

`--cases` 可以选择用例，`--skip-build` 在源文件和配置的指纹相符时复用已编译的仿真器。`--schedule legacy --layout row-major --dataflow ws` 使用按容量决定复用数的策略；比较其他硬件容量时应同时显式设置四个矩阵存储参数。

## 原始 NHWC 输入的卷积与 DW

`prepare_conv.py --extended` 生成以下五个算子。批量大小为 1，核大小为 3×3，膨胀率为 1，DW 的通道倍数为 1。

| 算子 | 输入 | 输出 | 步长 | 上、左填充 | 下、右填充 |
|---|---|---|---|---|---|
| 普通卷积 | 96×96×3 | 48×48×8 | 2 | 0 | 1 |
| DW | 48×48×8 | 48×48×8 | 1 | 1 | 1 |
| DW | 48×48×8 | 24×24×8 | 2 | 0 | 1 |
| 普通卷积 | 32×32×16 | 32×32×16 | 1 | 1 | 1 |
| 普通卷积 | 8×8×64 | 8×8×64 | 1 | 1 | 1 |

普通卷积的 NPU 权重布局为 `[Cout,Kh,Kw,Cin]`，Gemmini 布局为 `[Kh,Kw,Cin,Cout]`。DW 的 NPU 权重布局为 `[Kh,Kw,C]`，Gemmini 布局为 `[C,Kh,Kw]`。各文件中的数值表示同一组卷积核。

`run_mini_conv.py` 连接完整的生产 `npu_top`。普通卷积经过硬件输入窗口生成器和 16×16 主阵列；DW 使用 8 个 PE 的向量引擎。两者都经过生产 DMA，并使用同一个外部 AXI 存储器模型。计时包含输入窗口生成和所有输出写应答。

```bash
python3 test/gemmini_comparison/prepare_conv.py --extended --out build/common_conv_workloads

python3 test/gemmini_comparison/run_mini_conv.py \
  --repo . --workloads build/common_conv_workloads \
  --out build/common_conv_modified --verilator "$VERILATOR" --jobs 2 \
  --cache-sets 128 --cache-policy 3 --windowed --prefetch \
  --ia-cache-blocks 8 --ps-frames 16 --ps-storage-rows 720 \
  --bus-width 64 --read-beat-cycles 1 \
  --memory-timing pipelined --first-read-latency 8 \
  --s16-output-banks 4 --schedule auto --dataflow auto --rhs-layout auto
```

普通卷积使用同一调度模型选择 WS/IS、R、W，以及普通或块状权重布局；动态输入保持原始 NHWC，硬件生成 INT16 窗口数据。`--rhs-layout raw/packed` 可固定权重布局。DW 保持向量引擎的原生输入和权重布局。共同数学张量摘要与实际物理缓冲区摘要分别记录，打包后的分配范围也参与完整内存检查。

程序依据所选仓库的 `npu_axil_reg_if.sv` 寄存器复位设置选择普通卷积的默认输入模式。`--windowed`、`--prefetch` 和对应的 `--no-windowed`、`--no-prefetch` 可用于显式指定模式。结果文件记录实际选择。DW 的生产向量引擎在内部根据空间运算类型配置共享 DMA，在当前实现中主动启用窗口输入与预取。

第三方优化 DW 分支的完整 RTL 构建与运行见 [Gemmini 构建说明](gemmini_dw_rtl/README.md)。GEMM 使用配套软件的 WS 自动分块。普通卷积分别运行原生 `LoopConv` 调度和启用独立硬件 `Im2Col` 的调度；DW 使用该分支的 `gemmini_loop_dwconv_dw_ws` 专用指令。结果记录实际 Im2Col 请求、响应及 DW 启动次数。

## 计时和外部存储器

每个用例独立启动一个仿真进程并复位完整设备。只有外部张量内存预先初始化，设备内部缓存不预热。NPU 的周期 0 为 `calc_start` 被接受的上升沿，完成时刻为首次在上升沿观察到 `done_valid`。Gemmini 同时保留从首条计时配置命令开始的完整周期，以及从首条循环启动命令开始的周期。`axi_monitor.sv` 独立记录首次和末次总线事件，并检查完成时所有读事务和写应答均已结束。最后一次写应答时间单独保存在 `timing.last_b` 中。

两个 NPU 测试使用 `test/conv_npu/axi_memory.sv` 和 `NO_RANDOM_WAIT`，其服务规则为：

- 数据总线为 64 位，最大突发为 256 拍，并在 4 KiB 边界拆分。读地址队列深度为 16，读请求按顺序服务。
- 每个请求在 AR 握手时独立记录最早响应周期 `t_AR + 8`，后续请求可以同时等待响应时间。存储器在时钟边沿读取数据并写入响应寄存器。
- 同一读突发每周期传输一拍。下一请求已成熟时，前一突发最后 R 握手与后一突发首个 R 握手相隔 1 周期，即连续相邻周期传输，中间没有空闲数据拍。
- 写数据最多每周期一拍。存储器同时服务一个写事务，最后一拍写数据后的下一周期可返回写应答。
- 读写通道独立。DMA 的读、写未完成事务参数均为 4；每个用例另行记录实际观察到的最大数量。

`--read-beat-cycles 2` 可测量较低读带宽；`--memory-timing legacy` 可选择顺序响应的时序配置。比较程序检查双方的首拍延迟、数据拍间隔、突发转换间隔、独立请求等待方式、同步读寄存器和实际读写数量。

GEMM 计时排除输入生成、布局转换、主机描述符计算和完成信号的背压检查。结果不包含 RISC-V CPU 执行 TFLM 的时间。整模型推理周期由 `test/model_benchmark` 单独测量。

## NPU 主数据缓冲

以下是本组测试配置中声明的 RAM 有效载荷容量。参数为 `SIZE=16`、`IA_CACHE_BLOCKS=8`、`PS_FRAME_COUNT=16`、`PS_STORAGE_ROWS=720`、`OA_S16_FIFO_BANKS_MAX=4`，输入和权重的内部数据宽度均为 16 位。

| 缓冲区 | 容量公式，单位字节 | 容量 |
|---|---|---:|
| IA | 8×16×16×2 | 4,096 B |
| 权重双缓冲 | 2×16×16×2 | 1,024 B |
| 部分和 | 720×16×4 | 46,080 B |
| INT8 输出 FIFO | 32×16×16 | 8,192 B |
| INT16 输出 FIFO | 4×16×16×2 | 2,048 B |
| 主缓冲合计 | | 61,440 B，60 KiB |
| 共享窗口缓存 | 128×2×16 | 4,096 B |
| 含窗口缓存合计 | | 65,536 B，64 KiB |

INT16 输出 FIFO 在当前顶层配置中仍被实例化，本组 INT8 用例不使用它。表中单独列出窗口缓存；偏置与量化参数表、PE 寄存器、向量引擎临时数据和控制队列另行统计。综合后的 SRAM 宏面积及外围逻辑需要单独测量。

Gemmini 的 SPAD 和 accumulator 可以分别设置容量。容量比较应同时报告两者的容量，以及 NPU 各缓冲区的用途；部分和存储空间不能直接当作任意输入或权重的缓存空间。

## 利用率

GEMM 的有效 MAC 数为 `M×N×K`。两种数据流的阵列槽位数为：

\[
W_{\mathrm{WS}}=M\left\lceil\frac{K}{16}\right\rceil16
\left\lceil\frac{N}{16}\right\rceil16,
\qquad
W_{\mathrm{IS}}=N\left\lceil\frac{K}{16}\right\rceil16
\left\lceil\frac{M}{16}\right\rceil16.
\]

WS 的 M 方向和 IS 的 N 方向按有效行数流入阵列。形状占用率为 `M×N×K / W_padded`；整个加速器任务的有效利用率为 `M×N×K / (256×cycles)`。`ia_row` 统计有效输入向量进入阵列的周期，其值可与所选数据流的 `W_padded/256` 核对。

控制器按状态和条件优先级记录的等待原因互斥；DMA 活动、IA 有效周期、控制器总周期等统计与这些原因计数重叠。等待输入数据期间，外部存储器可能正在连续传输所需字节。等待本次输入完成也可能包含有效计算和流水线结束阶段。因此，计数所示的等待周期需要结合实际传输量和存储器服务下界分析。

DW 使用独立向量引擎，结果报告每个完整任务周期的有效 MAC 数。比较 DW 时应同时报告两侧实际参与计算的 PE 数量和硬件路径。

## 严格比较与复现

`compare_axi64_operators.py` 验证全部输入、输出、运行日志和构建文件的 SHA-256，以及相同的硬件容量与同步内存时序。GEMM 的逐项目标为 `NPU cycles < Gemmini cycles`。Dense 的五个 FC 来源和 `vector_m1` 分别检查整数条件 `6 × NPU cycles <= 5 × Gemmini cycles`，严格目标要求 Gemmini 的完整命令周期和首条循环启动周期均满足该条件。

```bash
python3 test/gemmini_comparison/compare_axi64_operators.py \
  --data-root /absolute/path/to/measurement_root --require-all-targets

python3 test/gemmini_comparison/test_compare_axi64.py \
  --report docs/axi64_operators_sync8.json \
  --out build/axi64_comparison_checks.json
```

默认输入位于测量目录的 `measurements/axi64/sync_latency8/`。各输入路径都可通过命令行参数显式指定；生成的 JSON 与 Markdown 保留完整复现命令。真实模型权重、输入和逐通道量化的单层检查及完整 `Invoke` 测量见 [模型适配说明](model_runtime/README.md)。
