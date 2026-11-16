# 阵列利用率与模型周期分析

`analyze.py` 从模型清单和通过正确性检查的完整模型结果计算算术工作量、WS/IS 空间利用率、数据传输周期下限和目标周期。它支持读取 `+NPU_UTIL_TRACE` 生成的实际 RTL 计数，并核对 IA 有效发送周期与模型维度计算值。

```sh
python3 test/performance_analysis/analyze.py \
  --prepared /path/to/prepared \
  --results /path/to/results/cases \
  --utilization-logs /path/to/utilization_runs \
  --out build/performance_analysis.json
```

每个 `utilization_runs/<model>/run.log` 对应同一模型的一个完整硬件执行，记录通过 `+NPU_UTIL_TRACE` 开启。该参数只增加仿真统计。

`compare_models.py` 比较原始和改进后的完整模型测量，并使用相同的软件参考周期计算加速比：

```sh
python3 test/performance_analysis/compare_models.py \
  --prepared /path/to/prepared \
  --original /path/to/original/results/cases \
  --modified /path/to/modified/results/cases \
  --software /path/to/software/results/cases \
  --original-utilization-logs /path/to/utilization_runs \
  --common-gemm /path/to/common_gemm_modified/summary.json \
  --out build/model_comparison.json
```

默认原始硬件模式为 31，改进后的模式为 63，可以通过 `--original-mode` 和 `--modified-mode` 指定。程序核对模型、输入、输出和 RAM 延迟。完整模型周期使用 `perf` 测量；逐层分析使用 `trace` 测量。性能结果中没有的只读计数可以从原始 RTL 日志补充，来源和样本编号在 JSON 中明确记录。未测量的 VCE 计数保存为 `null`。

## 定义

标准 GEMM 写为 `A[M,K] × B[K,N]`。本项目的 WS 阵列将 K 和 N 放在两个空间维度，M 维随时间连续输入。设阵列边长为 S，空间填充后的计算量为：

\[
Q_{\mathrm{pad}}=M\left\lceil\frac{K}{S}\right\rceil S\left\lceil\frac{N}{S}\right\rceil S.
\]

IS 将 K 和 M 放在两个空间维度，N 维随时间连续输入，其填充计算量为：

\[
Q_{\mathrm{pad,IS}}=N\left\lceil\frac{K}{S}\right\rceil S\left\lceil\frac{M}{S}\right\rceil S.
\]

程序逐层把实测 `array_ia_valid_cycles` 与 `Q_pad / S²` 的两种结果比较。只匹配一种时记录相应数据流；两种结果相同时记录 `ambiguous`，同时保留两个候选。空间填充计算量直接由实测有效行数乘以 `S²` 得到。没有该计数的层记录为 `unmeasured`，算术周期下限采用两个合法方向中的较小值。

空间利用率为 `MKN / Q_pad`。这一指标只描述维度填充。实际硬件吞吐率采用 `MKN / (S² × array_job_busy_cycles)`；其中任务周期包括数据传输、参数装载、计算和结果写回。`array_ia_valid_cycles` 表示阵列的有效行输入周期，独立于上述任务周期。

`dense_macs` 采用神经网络中常用的稠密计算量，包括卷积算法中的空间零填充，不包括阵列维度填充。Depthwise 的理想计算周期单独按 VCE PE 数计算。

数据传输周期下限以测得的读写字节数保持不变为条件，假定独立读写通道均连续工作，并允许传输和计算完全重叠。该值不包含 CPU 调度、池化、Add、Softmax、配置和流水线开始及结束的额外周期，不能直接用作预期模型运行时间。

完整模型周期来自关闭逐层统计的固件；逐层周期来自独立的逐层统计固件。脚本保留两种测量的区别。

初始化周期单独采用固件的 `init_cycles`，包含模型和解释器初始化、`AllocateTensors` 中的算子准备以及输入张量复制。`init_plus_invoke_cycles` 将这一初始化区间与一次 `Invoke` 相加，不包含更早的固件启动和其后的结果检查。结果同时提供单独 `Invoke` 与初始化加一次推理的加速比，并记录软件参考结果文件的 SHA256。

## 仿真观测字段

`tb_model_benchmark.sv` 记录以下统计：

| 字段 | 含义 |
|---|---|
| `array_jobs_busy_cycles` | Conv/GEMM 任务期间 NPU 忙碌周期 |
| `array_ia_valid_cycles` | 主阵列有效输入行周期 |
| `array_weight_commits` | 主阵列权重切换次数 |
| `array_controller_cycles` | 主阵列控制器记录的任务周期 |
| `array_wait_weight_tail` | 等待前一个计算数据流完成的周期 |
| `array_wait_weight_data` | 等待权重数据就绪的周期 |
| `array_wait_ia_data` | 等待输入分块就绪的周期 |
| `array_wait_bias` | 等待偏置就绪的周期 |
| `array_wait_quant` | 等待量化参数就绪的周期 |
| `array_wait_output` | 等待输出缓冲空间的周期 |
| `array_wait_ia_done` | 等待本次输入数据流结束的周期 |
| `window_cache_hits`、`window_cache_misses` | 完成窗口请求任务时累计的缓存计数 |
| `window_cache_read_bytes` | 窗口缓存从外部读取的字节数 |
| `vector_compute_cycles` | VCE 的 EXECUTE、Add 运算及 Softmax 运算状态周期 |
| `vector_dma_wait_cycles` | VCE 处于数据装载等待、权重装载等待、输出传送或响应等待，以及 DMA 请求尚未获准的周期 |
| `softmax_jobs`、`softmax_done` | 实际启动和完成的硬件 Softmax 任务数 |

七个 `array_wait_*` 字段在每个控制器有效周期中至多有一个增加。`WEIGHT_START` 状态先统计前一个计算数据流尚未结束，再统计权重数据尚未就绪；`IA_START` 状态依次检查输入数据、偏置、量化参数和输出空间；`IA_WAIT` 单独统计输入流完成等待。这些条件没有覆盖全部控制器周期，脚本使用 `controller_other_cycles` 记录剩余周期。条件表达式保存在输出 JSON 中，并检查七项之和不超过控制器有效周期。

等待输入流完成的周期可以包含有用计算和流水线结束过程。`array_ia_valid_cycles`、传输统计和这些控制器统计描述不同活动，不能直接相加作为总周期。

`vector_dma_wait_cycles` 在多个 DMA 条件的逻辑或为真时增加一次。其中 `WB_DATA` 包括正在传送输出数据的周期；独立的权重读取和结果写回状态机也可以与运算状态同时工作。因此该字段可以与 `vector_compute_cycles` 重叠，表示发生 DMA 活动或等待的周期，不能解释为全部可以删除的空闲周期。脚本保留原始 RTL 字段名称，并记录其精确条件。

## 外部存储器对 GEMM 等待周期的约束

共同 GEMM 测试的 32 位存储器每两个周期返回一拍，所以读取 `R` 字节至少需要 `ceil(R/2)` 个周期。它在读突发之间还需要一个额外周期；保持实际请求数量和每次请求长度不变时，从首次 AR 到最后 R 的服务下界为 `2×read_beats+read_requests`。

例如，当前 IA8、PS799 配置下，`M=1024,N=16,K=144` 选择 IS、`R=1,W=16`。输入读取 147,456 B，权重跨四个输出位置组读取 `4×144×16=9,216 B`，偏置读取 64 B，总计 156,736 B。`M=64,N=64,K=576` 选择 WS、`R=4,W=4`，读取输入 36,864 B、权重 36,864 B、偏置 256 B，总计 73,984 B。脚本根据实际调度、布局和计数核对这些公式。

这一分析给出保持当前数据流量时的改进范围。权重重载、短突发数量和外部服务速度直接影响周期下界；控制器的数据等待计数包含传输这些必要数据所花费的时间。

## 调度与物理传输检查

`test_schedule.py` 使用独立编译的 C 入口检查 C/Python 对合法数据流、复用参数、PS 容量、布局和整数溢出的处理是否一致。它同时验证 INT8/INT16 打包结果、打包边界、尾部读取的物理字数和 IS 输出合并的地址条件。WS 的写请求估计另与逐描述、逐物理突发的计算比较，覆盖尾行、连续大描述、非整数倍地址和页边界。

```sh
python3 test/performance_analysis/test_schedule.py --out build/schedule_validation
python3 test/prepared_dispatch/run.py --out build/prepared_validation
python3 test/prepared_dispatch/run.py --legacy-is 0 --out build/prepared_ws_default_validation
```

矩阵驱动通过 `MATRIX_CAPS` 的 bit 2 读取 IS 能力。硬件未实现 IS 时，AUTO 只枚举 WS，显式 IS 返回不支持。能力寄存器为零的旧设备使用 `DSA_ENABLE_IS_MODE` 的编译设置，默认值为 1；`--legacy-is 0` 检查仅支持 WS 的旧平台设置。Prepare 保存选中的参数，Invoke 提交已准备的配置。

实际 RTL 验证包含完整 AXI-Lite 配置、参考整数计算、逐字节读写范围、固定与随机 AXI 等待，以及错误后的下一次任务：

```sh
python3 test/matrix_layout/run.py --profiles 8 4 16 --out build/matrix_validation
python3 test/matrix_layout/run.py --profiles 8 --ws-only --out build/matrix_ws_validation
python3 test/is_output_coalesce/run.py --out build/is_output_validation
python3 test/ws_output_coalesce/run.py --out build/ws_output_validation
python3 test/ws_output_coalesce/small_banks.py --out build/ws_output_small_banks
```

`audit_schedule_traffic.py` 从共同 GEMM 的实际配置重新计算读取字节数与写请求数，并与 AXI 计数比较：

```sh
python3 test/performance_analysis/audit_schedule_traffic.py \
  --mini build/common_gemm_modified/summary.json \
  --out build/schedule_traffic.json
```

普通矩阵的未对齐尾行先按 4 字节取整，再为非零地址余数增加一个物理字。调度模型的读请求估算没有计入 4 KiB 分段，偏置与量化表的请求数按 16 个通道分组估算；输出字数采用稠密行估算。检查结果保留这些估计与实际计数的差值。空间卷积的输入项对应前端交付的 INT16 块流量，实际外存流量应读取 RTL 的 `ar_bytes`。

`compare_reference_set.py` 可将多种 Gemmini 硬件配置的有效结果与同一份 NPU 测量比较。脚本检查数学张量、输出摘要、非输出内存和事务完成状态，并分别保留各硬件配置的结果。未覆盖全部共同形状的配置仅参与已有项目的比较，其总周期为 null。

```sh
python3 test/performance_analysis/compare_reference_set.py \
  --npu build/common_gemm_modified/summary.json \
  --gemmini build/gemmini_config_a/results.json build/gemmini_config_b/results.json \
  --out build/reference_comparison.json
```

## 窗口请求和连续返回

`collect_window_pipeline.py` 读取八次硬件逐层检查结果，按照模型的输入尺寸、输出尺寸、核、步幅、扩张率和填充独立计算有效窗口元素数。每个任务的已接受描述数、终止响应数、有效返回元素数与几何计算必须一致。报告另外统计最多在途描述数、连续响应拍数以及同周期接收请求和返回数据的次数。

```sh
python3 test/performance_analysis/collect_window_pipeline.py \
  --measurements build/model_measurements \
  --previous build/previous_model_measurements
python3 test/performance_analysis/collect_window_cache_models.py \
  --repo . --measurements build/model_measurements \
  --native-conv build/common_conv/summary.json
```

缓存结果的 `passed` 表示统计与数据检查通过，`target_passed` 单独表示所测 DW 项是否达到 99% 需求命中率。命中率在请求接受时统计，包含初次访问；连续返回比例和返回时间单独测量。`collect_comparison.py` 可通过 `--window-pipeline`、`--bottlenecks`、`--timing` 和 `--depthwise-mapping` 将窗口吞吐、性能下界、Gemmini 启动时间和官方 DW 映射分析一并保存到正式结果中。
