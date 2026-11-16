# Gemmini 与 mini_tflm_dsa 共同算子测试

本目录使用相同的数学输入、权重、偏置和参考输出，测量两个加速器完成同一算子的周期。GEMM、普通卷积和逐通道卷积（Depthwise）分别统计。输入数据为确定性的合成整数；其中 GEMM 的模型形状从四个准备完成的 TFLite 模型中提取。

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
  --ps-frames 16 --ps-storage-rows 799 --s16-output-banks 4 \
  --schedule auto --dataflow auto --layout auto
```

这些参数也是程序的默认设置。`--layout auto` 使用驱动的同一成本模型比较普通布局、仅打包 A、仅打包 B 和同时打包两者；每个布局分别枚举合法的 WS/IS、IA 复用数 R 和权重复用数 W。结果保留各候选布局的估算值和选中的实际配置。`--layout row-major`、`lhs-packed`、`rhs-packed`、`both-packed` 可以固定布局，`--dataflow ws/is` 可以固定数据流。

`--cases` 可以选择用例，`--skip-build` 在源文件和配置的指纹相符时复用已编译的仿真器。`--schedule legacy --layout row-major --dataflow ws` 使用按容量决定复用数的策略；比较其他硬件容量时应同时显式设置四个矩阵存储参数。

## 原始 NHWC 输入的卷积与 DW

`prepare_conv.py` 生成以下三个算子。批量大小为 1，核大小为 3×3，膨胀率为 1，DW 的通道倍数为 1。

| 算子 | 输入 | 输出 | 步长 | 上、左填充 | 下、右填充 |
|---|---|---|---|---|---|
| 普通卷积 | 96×96×3 | 48×48×8 | 2 | 0 | 1 |
| DW | 48×48×8 | 48×48×8 | 1 | 1 | 1 |
| DW | 48×48×8 | 24×24×8 | 2 | 0 | 1 |

普通卷积的 NPU 权重布局为 `[Cout,Kh,Kw,Cin]`，Gemmini 布局为 `[Kh,Kw,Cin,Cout]`。DW 的 NPU 权重布局为 `[Kh,Kw,C]`，Gemmini 布局为 `[C,Kh,Kw]`。各文件中的数值表示同一组卷积核。

`run_mini_conv.py` 连接完整的生产 `npu_top`。普通卷积经过硬件输入窗口生成器和 16×16 主阵列；DW 使用 8 个 PE 的向量引擎。两者都经过生产 DMA，并使用同一个外部 AXI 存储器模型。计时包含输入窗口生成和所有输出写应答。

```bash
python3 test/gemmini_comparison/prepare_conv.py --out build/common_conv_workloads

python3 test/gemmini_comparison/run_mini_conv.py \
  --repo . --workloads build/common_conv_workloads \
  --out build/common_conv_modified --verilator "$VERILATOR" --jobs 2 \
  --cache-sets 128 --cache-policy 3 --windowed --prefetch \
  --ia-cache-blocks 8 --ps-frames 16 --ps-storage-rows 799 \
  --s16-output-banks 4 --schedule auto --dataflow auto --rhs-layout auto
```

普通卷积使用同一调度模型选择 WS/IS、R、W，以及普通或块状权重布局；动态输入保持原始 NHWC，硬件生成 INT16 窗口数据。`--rhs-layout raw/packed` 可固定权重布局。DW 保持向量引擎的原生输入和权重布局。共同数学张量摘要与实际物理缓冲区摘要分别记录，打包后的分配范围也参与完整内存检查。

程序依据所选仓库的 `npu_axil_reg_if.sv` 寄存器复位设置选择普通卷积的默认输入模式。`--windowed`、`--prefetch` 和对应的 `--no-windowed`、`--no-prefetch` 可用于显式指定模式。结果文件记录实际选择。DW 的生产向量引擎在内部根据空间运算类型配置共享 DMA，在当前实现中主动启用窗口输入与预取。

官方 Gemmini 调度程序的命令生成与 CPU 算子参考检查见 `gemmini_command_trace/`。普通卷积调用 `tiled_conv_auto`，DW 调用 `tiled_conv_dw_auto`，均使用 WS 模式。

## 计时和外部存储器

每个用例独立启动一个仿真进程并复位完整设备。只有外部张量内存预先初始化，设备内部缓存不预热。周期 0 定义为启动命令被接受的上升沿；完成时刻为首次在上升沿观察到 `done_valid`。`axi_monitor.sv` 独立记录首次和末次总线事件，并检查完成时所有读事务和写应答均已结束。最后一次写应答时间单独保存在 `timing.last_b` 中。

两个 NPU 测试使用 `test/conv_npu/axi_memory.sv` 和 `NO_RANDOM_WAIT`，其服务规则为：

- 总线为 32 位。读地址队列深度为 16，读请求按顺序服务。
- 队列为空时，读地址握手到首个读数据握手相隔 3 个周期。
- 同一读突发每 2 个周期传输一拍。跨读突发时，两次相邻数据握手至少相隔 3 个周期。
- 写数据最多每周期一拍。存储器同时服务一个写事务，最后一拍写数据后的下一周期可返回写应答。
- 读写通道独立。DMA 的读、写未完成事务参数均为 4；每个用例另行记录实际观察到的最大数量。

读数据的两周期间隔来自此测试存储器的状态转换，即使关闭随机等待仍然存在。与其他存储器模型比较时，应使用相同的服务规则，并同时比较数据传输量和请求数量。

GEMM 计时排除输入生成、布局转换、主机描述符计算和完成信号的背压检查。结果不包含 RISC-V CPU 执行 TFLM 的时间。整模型推理周期由 `test/model_benchmark` 单独测量。

## NPU 主数据缓冲

以下是当前默认测试配置中声明的 RAM 有效载荷容量。参数为 `SIZE=16`、`IA_CACHE_BLOCKS=8`、`PS_FRAME_COUNT=16`、`PS_STORAGE_ROWS=799`、`OA_S16_FIFO_BANKS_MAX=4`，输入和权重的内部数据宽度均为 16 位。

| 缓冲区 | 容量公式，单位字节 | 容量 |
|---|---|---:|
| IA | 8×16×16×2 | 4,096 B |
| 权重双缓冲 | 2×16×16×2 | 1,024 B |
| 部分和 | 799×16×4 | 51,136 B |
| INT8 输出 FIFO | 32×16×16 | 8,192 B |
| INT16 输出 FIFO | 4×16×16×2 | 2,048 B |
| 合计 | | 66,496 B，64.9375 KiB |

INT16 输出 FIFO 在当前顶层配置中仍被实例化，本组 INT8 用例不使用它。表中未计入窗口缓存、偏置与量化参数表、PE 寄存器、向量引擎临时数据和控制队列。综合后的 SRAM 宏面积及外围逻辑需要单独测量。

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
