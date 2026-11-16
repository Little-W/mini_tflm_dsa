# Gemmini 完整模型运行与逐层验证

本目录将第三方 DWConv Gemmini 接入项目现有的 PicoRV32、系统互连、2 MiB RAM 和 TFLM 完整模型程序。处理器配置、RAM 响应时序、模型文件、输入样本及最近偶数舍入参考与 `test/model_benchmark` 共用。

Gemmini 使用 16×16 INT8 阵列、32 KiB scratchpad、32 KiB accumulator、64 位 AXI、每拍 8 B、最多 256 拍的 AXI INCR 突发和 `spad_read_delay=1`。完整模型的普通卷积具有两种显式测试策略。

| 策略 | 普通空间 Conv | 1×1、stride 1 | Depthwise Conv | Fully Connected |
| --- | --- | --- | --- | --- |
| `native` | 原生 `LoopConv` | WS GEMM | 第三方原生 DWConv | WS GEMM |
| `im2col` | 方形卷积核使用独立硬件 Im2Col；矩形卷积核使用 `LoopConv` | WS GEMM | 第三方原生 DWConv | WS GEMM |
| `auto` | 优先使用可容纳的 `LoopConv` 分块；需要输入通道分块时可选择独立 Im2Col | WS GEMM | 第三方原生 DWConv | WS GEMM |

`run_suite.py` 为每层记录 `execution_path`。`im2col` 策略还检查适用空间卷积的请求与响应计数均大于零。性能比较使用各策略实际执行完整模型的结果。

## 源码版本

- 硬件：[dwconv/gemmini-dwconv，4a33b75f975297e309847f41f81f4c0f8b20b81d](https://github.com/dwconv/gemmini-dwconv/tree/4a33b75f975297e309847f41f81f4c0f8b20b81d)。
- 软件：[dwconv/gemmini-rocc-tests-dwconv，576f08c217dfefb9fa2e3e087575f23699565560](https://github.com/dwconv/gemmini-rocc-tests-dwconv/tree/576f08c217dfefb9fa2e3e087575f23699565560)。

`vendor.py` 保留软件头文件的 64 位 RoCC 操作数字段，将命令传输连接到 RV32 MMIO，并将 fence 连接到硬件完成等待。生成的参数头必须来自实际使用的 RTL 配置。构建记录保存源码、参数头、编译器和二进制文件的 SHA-256。

## 数值计算

Gemmini 计算有符号 INT8 乘加与 INT32 偏置，并输出完整 INT32 累加结果。Pico 随后执行输入零点修正、逐通道 Q31 最近偶数舍入、输出零点加法和激活范围裁剪。上述 CPU 操作全部位于完整 `Invoke` 的计时范围内。

对于输出位置 `(y,x)` 和通道 `c`，输入零点修正为：

\[
\Delta(y,x,c)=-z_{in}\sum_{(k_y,k_x,k_c)\in V(y,x)}w(k_y,k_x,k_c,c),
\]

其中 `V(y,x)` 仅包含落在原始输入图像内的卷积采样点。硬件填充区域使用数值零；边沿修正通过有效卷积核范围计算。输入的 `-128` 到 `127` 全部原样传入硬件。

普通空间卷积的权重二维前缀和在 TFLM `Prepare` 阶段计算。Depthwise Conv 按当前通道生成 64 B 临时前缀表，1×1 卷积复用完整权重和。此布局控制常驻存储开销，并使边沿修正采用固定数量的整数运算。

重新量化保留完整有符号 64 位乘积。RV32 快速路径分别使用乘积的高、低 32 位完成舍入位和低位非零信息的检查；输出裁剪在加输出零点前完成，保持整数饱和语义。`test_quantization.py` 使用独立 Python 整数计算检查舍入中点、负数、INT32 极值、全部合法移位及不同输出零点。

## 调度与存储

原生普通卷积按输入窗口、卷积核和 accumulator 占用选择空间与输出通道分块。窄输出行采用较小的行分块。Depthwise Conv 每个 loop 使用一个最多 16 通道的组和最多两阶段输出行。每个原生卷积分块完成后通过完整 accumulator MVOUT 读取结果。

独立 Im2Col 将原始输入图像及填充写入 scratchpad，由硬件生成卷积窗口。权重放入独立 bank；较大的输入通道数分批累加。一次可容纳输入通道时，同一空间块的多个输出通道组复用已装入的输入。尾部输出保留实际写回行数，计算请求使用完整阵列行数。

第三方 DWConv 状态通过局部加速器复位切换回普通矩阵计算。桥接器在复位前等待加速器和 AXI 请求全部完成，维持 Pico 与系统 RAM 的运行。复位等待计入模型推理时间。

## RV32 MMIO

基地址为 `0x50000000`。命令寄存器在局部加速器复位后保持内容；驱动缓存其最近写入值，仅更新发生改变的 32 位部分。

| 偏移 | 操作 | 含义 |
| --- | --- | --- |
| `0x00` | 读 | bit 0：命令可接收；bit 1：加速器或 DMA 忙碌 |
| `0x04`、`0x08` | 读写 | `rs1` 低、高 32 位 |
| `0x0c`、`0x10` | 读写 | `rs2` 低、高 32 位 |
| `0x14` | 写 | 提交 `funct[6:0]`，写响应等待 RoCC 接收命令 |
| `0x18` | 读 | 等待加速器计算及 AXI 读写完成 |
| `0x20` | 读 | 桥接器标识 |
| `0x24` | 读 | 最大 DMA 请求字节数 |
| `0x28` | 写 1 | 等待当前工作完成，执行 8 周期局部加速器复位 |

## 构建与运行

以下命令在仓库根目录执行。`TASK_SOFTWARE` 指向上述固定版本的软件仓库，`TASK_GENERATED` 指向已生成的 SP32/ACC32、AXI64、`spad_read_delay=1` RTL 目录，`TASK_PREPARED` 指向四个模型的已验证数据目录。固定硬件的依赖和生成步骤见 [Gemmini RTL 构建说明](../gemmini_dw_rtl/README.md)。`TASK_BENCH` 指定本组运行输出目录。

```sh
TASK_PARAMS="$TASK_GENERATED/gemmini_params.h"
TASK_BUILD_MANIFEST="$TASK_GENERATED/build_manifest.json"

python3 test/gemmini_comparison/model_runtime/build_sim.py \
  --out "$TASK_BENCH/simulator" --gemmini-generated "$TASK_GENERATED" \
  --verilator "$VERILATOR" --first-read-latency 8 --jobs 2

TASK_SIMULATOR="$TASK_BENCH/simulator/obj/Vtb_model_benchmark"

python3 test/gemmini_comparison/model_runtime/build_firmware.py \
  --out "$TASK_BENCH/firmware_native" --gcc "$RISCV_GCC" \
  --software "$TASK_SOFTWARE" --params "$TASK_PARAMS" \
  --conv-policy native --jobs 4

python3 test/gemmini_comparison/model_runtime/build_firmware.py \
  --out "$TASK_BENCH/firmware_native_trace" --gcc "$RISCV_GCC" \
  --software "$TASK_SOFTWARE" --params "$TASK_PARAMS" \
  --conv-policy native --trace --jobs 4

python3 test/gemmini_comparison/model_runtime/run_suite.py \
  --out "$TASK_BENCH/models_native" --prepared "$TASK_PREPARED" \
  --simulator "$TASK_SIMULATOR" \
  --firmware "$TASK_BENCH/firmware_native" \
  --trace-firmware "$TASK_BENCH/firmware_native_trace" \
  --samples 0 1 --kind both --jobs 4
```

将 `--conv-policy` 和相应输出目录改为 `im2col`，即可执行第二种完整模型策略。

真实算子单独运行使用相同后端生成 RoCC 命令，然后将命令送入完整 Gemmini RTL：

```sh
python3 test/gemmini_comparison/model_runtime/run_layers.py \
  --out "$TASK_BENCH/real_layers_native" --prepared "$TASK_PREPARED" \
  --software "$TASK_SOFTWARE" --params "$TASK_PARAMS" \
  --simulator "$TASK_ACCELERATOR_SIMULATOR" --build-manifest "$TASK_BUILD_MANIFEST" \
  --read-interval 1 --first-read-latency 8 --inter-burst-gap-cycles 1 \
  --read-outstanding-limit 4 --conv-policy native --jobs 4

python3 test/gemmini_comparison/model_runtime/test_quantization.py \
  --out "$TASK_BENCH/quantization" \
  --software "$TASK_SOFTWARE" --params "$TASK_PARAMS"
```

## 结果解释

完整模型性能固件使用 `rdcycle` 测量一次完整 `MicroInterpreter::Invoke`。初始化周期单独保存。逐层验证固件通过现有 profiler 观察每个算子的输出；其中的观察开销与普通性能固件分别报告。输入和模型文件在执行后再次检查 SHA-256。

`run_layers.py` 的周期测量范围为命令注入与硬件计算、DMA 完成，结果为完整 INT32 累加器输出。此测试同时验证实际逐通道重新量化结果与模型参考相同。CPU 命令生成、MMIO 和重新量化的周期由完整模型测试记录。

独立层的同步内存配置对每次 AR 握手分别记录八周期后的最早响应时间。一个突发传输时，后续已接受请求可以同时等待就绪。就绪请求的两个相邻突发可以连续返回数据：前一个突发的 `RLAST` 和下一个突发的首拍在相邻上升沿握手，中间有 0 个空闲周期。`--inter-burst-gap-cycles 1` 表示这两个握手边沿相差一个周期。运行清单保存实际首拍延迟、数据拍间隔、请求并发上限和逐请求延迟计数；参数头与模拟器二进制均与硬件构建清单核对。

完整模型共用 `soc_axi_ram`，使用上升沿同步读取和数据寄存器。构建选项
`--first-read-latency 8` 设置从 RAM 接口接受 AR 到首拍握手的最早周期数，至少为 1。
默认附加等待为 0。所有已接受请求分别计算就绪时间，因此相邻突发可以连续返回。
实际首拍延迟统计保存在 `SOC_NETWORK_DMA_PROFILE` 和运行结果中。

每个完整模型运行目录包含 `case.json`、`result.json`、日志、最终输出和必要的逐层张量；每组顶层 `summary.json` 汇总全部运行。每个独立算子保留实际输入、权重、偏置、Q31 系数、命令、INT32 参考和 RTL 结果。
