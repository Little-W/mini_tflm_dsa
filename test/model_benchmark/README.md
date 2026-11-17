# 完整模型性能测试

本测试由 PicoRV32 执行 TFLM 和 NMSIS，比较纯软件与 NPU 加速的完整
`MicroInterpreter::Invoke()`。测试模型为 MNIST CNN、MobileNetV1 Visual Wake Words、
DS-CNN Keyword Spotting 和 ResNet-8 CIFAR-10，每个模型使用两个已记录来源的真实输入。

| 模型 | 输入形状（NHWC） | 配置 |
|---|---|---|
| MNIST CNN | 1×28×28×1 | Conv 通道数 8/16，隐藏全连接层 64 个单元 |
| MobileNetV1 VWW | 1×96×96×3 | 通道宽度系数 0.25 |
| DS-CNN KWS | 1×49×10×1 | Speech Commands v2 的 MFCC 输入 |
| ResNet-8 CIFAR-10 | 1×32×32×3 | CIFAR-10 输入 |

## 测试配置

| 项目 | 配置 |
|---|---|
| CPU | PicoRV32，RV32IM，`performance` 配置，快速乘法、硬件除法和桶形移位器启用 |
| CPU 寄存器与运算 | 双读端口；`TWO_CYCLE_ALU=0`，`TWO_CYCLE_COMPARE=0` |
| CPU 指令缓存 | 默认开启，64 行，每行 4 个 32 位字，数据容量 1 KiB |
| NPU 核心 | 统一路径，普通 PS 存储，`PCR_ENGINE=0` |
| 脉动阵列 | 16×16 |
| VCE | 8 个 PE，`TILE=16` |
| AXI 数据接口 | 64 位，`--bus-width 32` 可选择 32 位 |
| 外部 RAM | 2 MiB |
| RAM 读取 | 上升沿同步读取，数据经过寄存器返回 |
| RAM 最早首拍延迟 | 默认 8 周期，从 RAM 的 AR 握手开始计算，使用 `--first-read-latency` 设置 |
| RAM 连续返回 | 每周期一拍；就绪的相邻突发之间有 0 个空闲周期 |
| RAM 附加固定延迟 | 默认 0，可用 `--latency` 指定 |
| IA 缓冲 | 8 个块 |
| PS 缓冲 | 16 个 frame；公平比较配置使用 720 行物理存储 |
| 输出缓冲 | INT8 32 个块，INT16 4 个块 |
| 静态权重 | Prepare 阶段打包为 16×16 块 |
| 矩阵调度 | Prepare 阶段计算 WS/IS 和复用参数 |
| 张量 arena 上限 | 512 KiB，实际使用量逐模型记录 |
| AXI 未完成读写请求数 | 各 4 |
| AXI 突发 | INCR 最多 256 拍，遵守 4 KiB 边界；64 位时每个完整数据拍传输 8 B |
| DMA 窗口描述在途数 | 最多 4，返回携带 2 位输入区域标识 |
| 共享窗口缓存需求在途数 | 最多 4，按接收顺序返回 |
| 算术 | INT8，最近偶数舍入 |
| 编译 | C 和 C++ 同时设置软件或硬件开关，`-O3`、RV32IM |
| 输入 | 相同模型文件和相同输入字节 |

测试程序默认选择 64 位 AXI。CPU 原生数据通路和指令缓存保持 32 位，
互连按地址选择共享 64 位总线中的字节位置。CPU 与加速器使用同一块 2 MiB RAM，
RAM 的物理行数随总线宽度调整。稀疏 32 位固件和数据镜像在运行前合并，
再按小端格式组合为 64 位 RAM 数据，生成文件及其 SHA-256 写入测量记录。
PicoRV32 使用仓库指定提交 `ef203c2b0a3fb793280f5114941416c425c5b461`。
编译器、仿真器、依赖、模型、输入、可执行文件和参与构建的源码均记录 SHA-256。

每个读请求独立记录最早响应时间。设置 `--first-read-latency 8` 后，空闲读通道且
`RREADY=1` 时，RAM 在接受 AR 后第 8 个上升沿完成首拍数据握手。
后续已接受请求的等待与当前 burst 的返回重叠；下一个请求已就绪时，其首拍可以
紧接前一个 burst 的 `RLAST`，在下一个上升沿传输。RAM 记录实际首拍延迟，
运行程序检查最小值不低于设置值。SoC 仲裁、时序缓冲、读通道占用和接收端暂停
造成的额外等待计入实际测量。参数定义和公式见
[64 位 AXI 比较配置](../../docs/axi64_configuration.md)。

CPU 参数通过 `--cpu-profile` 选择，指令缓存通过 `--icache 0|1` 单独配置。
软件和硬件使用同一份 SoC 仿真程序及相同 CPU 参数。实际展开后的参数在仿真中
输出为 `SOC_NETWORK_CPU_PROFILE`，运行程序检查其与 `sim/build.json` 一致。

| PicoRV32 参数 | `standard` | `performance`（默认） |
|---|---:|---:|
| `ENABLE_MUL` | 1 | 1 |
| `ENABLE_FAST_MUL` | 0 | 1 |
| `ENABLE_DIV` | 1 | 1 |
| `BARREL_SHIFTER` | 0 | 1 |
| `ENABLE_REGS_DUALPORT` | 1 | 1 |
| `TWO_STAGE_SHIFT` | 1 | 1 |
| `TWO_CYCLE_COMPARE` | 0 | 0 |
| `TWO_CYCLE_ALU` | 0 | 0 |
| `COMPRESSED_ISA` | 0 | 0 |

`ENABLE_FAST_MUL=1` 时，PicoRV32 选择快速乘法实现。两个配置均执行相同的 RV32IM
固件。`--cpu-profile standard --icache 0` 可复现原有 CPU 参数；
`--cpu-profile performance --icache 0` 用于单独检查处理器内部性能选项的影响。

## 数据准备

交付的测试结果包包含 `prepared/`，其中包括模型、输入、逐层 RNE 参考输出、
图结构、量化参数和来源记录。所有运行首先验证文件长度和 SHA-256。

```bash
python test/model_benchmark/model_data.py \
  --prepared /path/to/prepared
```

`--out` 可以将验证后的数据复制到新的目录。模型和生成的二进制结果放在构建目录，
源码 patch 包含测试程序。

## 构建与执行

需要 Verilator、主机 C++ 编译器、GNU Make、Python 3.10 或更新版本，
以及带 RV32IM/ILP32 newlib 和 C++ 标准库的 RISC-V 工具链。
可使用 xPack RISC-V GCC 14.2.0-3。`--gcc` 指向该工具链的 GCC，
其他工具通过相同文件名前缀找到。

```bash
export PICORV32_ROOT=/path/to/picorv32
python test/model_benchmark/run_suite.py \
  --out build/model_benchmark \
  --prepared /path/to/prepared \
  --gcc /path/to/riscv-none-elf-gcc \
  --verilator /path/to/verilator \
  --cpu-profile performance --icache 1 --bus-width 64 --ps-storage-rows 720 \
  --first-read-latency 8 --latency 0 \
  --jobs 1 --run-jobs 4
```

与 Gemmini 进行等容量测试时，在上述命令中增加
`--ia-cache-blocks 8 --ps-storage-rows 720 --s16-output-banks 4`。
CPU、外部 RAM、阵列、VCE 和 DMA 均采用上表配置。驱动在每次模型初始化时读取
实际 PS 容量，并据此重新计算复用参数。不同容量的测量应分别保存到独立目录。

默认构建一个 SoC 仿真器和四份固件，完成 32 次独立仿真：

- 纯软件完整推理计时。
- 硬件加速完整推理计时。
- 纯软件逐层周期和输出记录。
- 硬件加速逐层周期和输出记录。

每份固件运行四个模型的两个输入。每次输入均启动新仿真进程并复位 SoC。
纯软件固件在 C 和 C++ 编译时关闭 Conv、VCE 和 FC 加速；运行时加速掩码为 0。
硬件固件使用掩码 63，启用 Conv、DW、Pool、FC、Add 和 Softmax。
DW 核面积上限为 49，池化窗口上限为 256；DS-CNN 的 25×5 和 ResNet-8 的
8×8 平均池化均属于硬件测试范围。ResNet-8 的三个 Add 节点采用独立输入缩放、
输出缩放与三次最近偶数舍入。TFLM 通用软件 Add 用于纯软件性能比较。

可以按模型、运行类别或执行模式选择任务：

```bash
python test/model_benchmark/run_suite.py \
  --out build/model_benchmark --prepared /path/to/prepared \
  --skip-build --models mnist_cnn --modes hw --kinds trace
```

`--skip-build` 会检查源码和可执行文件与构建记录相同。
`--resume` 只复用已通过且模型、输入、源码构建结果、RAM 时序完全相同的运行。
`--build-only` 在构建后结束。

32 次运行完成后，可以生成 1000× 目标预算和 DW 供数、MAC 利用率统计：

```bash
python test/performance_analysis/analyze_model_budget.py \
  --measurements build/model_benchmark --target-speedup 1000
```

输出 `model_budget.json` 保留源结果摘要、初始化周期、每模型 Invoke 预算、
算子周期组成和 DW 缓存计数。算子周期来自独立 trace 固件，目标预算使用 perf 固件的
Invoke 周期；两者的差额单独记录。
为另一容量配置生成同样的报告后，可增加 `--reference-measurements /path/to/other_measurements`
比较 PS 容量影响。程序检查两组模型、输入、固件和 RTL 源码相同，且仅 PS 行数发生变化。

## 周期与占比

完整模型周期由 CPU 在 `Invoke()` 前后读取 `rdcycle` 得到，包含算子执行、
硬件任务配置、DMA、状态轮询和解释器调度。模型初始化、静态权重打包、调度参数计算、张量分配、输入装载和结果检查
分别位于计时区间之外，两种执行模式使用相同边界。

`init_cycles` 单独记录初始化周期。`planning_cycles` 记录其中驱动查询参数缓存和
计算调度参数的累计周期，由驱动使用 `rdcycle` 测量。
共享 IA/PS 容量下的 RAW32 与压缩模式比较见
[`test/ps_compression`](../ps_compression/README.md)，使用同一 RTL 可执行文件和固件 ELF。

完整模型加速比按 `软件 Invoke 周期 / 硬件 Invoke 周期` 计算。
多个输入的汇总值使用软件周期总和除以硬件周期总和，并同时保留最小单输入加速比。

逐层固件使用 `MicroProfilerInterface` 记录每个算子的周期和输出。
每层周期由仿真器在该层开始、结束标记之间统计；逐层固件随后提交输出地址和长度，
由仿真器读取输出张量。每个输入中，同类算子的占比为该类累计周期除以该次逐层固件
的 Invoke 周期；多个输入的占比取这些百分比的平均值。算子加速比使用成对软件、
硬件逐层周期总和之比。解释器和记录代码的其余周期单独列出。
完整模型性能结果使用关闭逐层记录的固件。

## 正确性检查

固件检查最终输出的全部字节。逐层运行还检查每个算子的输出张量，
包括 Add、大小窗口平均池化、Conv、DW、FC、Reshape 和 Softmax。
软件和硬件均采用同一 RNE 参考输出。

仿真器从实际信号统计各类 START、DONE、NPU 活跃周期和 AXI 读写字节。
每个硬件算子的任务数量须符合图结构，所有已启动任务须完成，AXI 和 NPU 错误数须为零。
纯软件执行期间 NPU 保持空闲，硬件任务数量和 NPU DMA 读写字节均须为零。
运行结束后再次核对模型与输入内容，确认没有修改。

每次 NPU 的 AXI 读、写请求握手均检查事务字节数不超过配置上限。
运行结束时输出 `SOC_NETWORK_DMA_PROFILE`，保存实际最大读写事务长度；
Python 程序同时核对硬件参数、实际事务长度以及构建记录中的 `bus_width` 和 `dma_max_bytes`。
`dma_max_bytes` 根据 256 拍和总线宽度计算，64 位配置为 2048 B。

汇总中的 `functional_passed` 表示已记录运行的正确性检查结果，`complete` 表示
32 次运行是否全部完成；性能目标分别保存在 `dw_all_layers_above_20x` 和
`model_targets_met`，须结合完整运行结果读取。

DW 的目标检查覆盖每一层、每一个输入，要求加速比超过 20。
四个模型的完整 Invoke 目标均为每个输入达到 1,000 倍加速。
目标检查单独报告；功能检查始终验证实际输出与内存行为。

### 窗口请求和返回统计

每个 DW 或池化任务完成时，仿真器输出 `SOC_NETWORK_WINDOW_JOB`，在
`result.json` 的 `simulator.window_jobs` 中保存请求数、完成数、最大在途数、
返回拍数、连续返回次数、请求与返回同时发生的次数，以及有效返回元素数。
有效元素数只累计成功握手数据拍中的有效通道；请求数按描述握手统计。
任务完成时检查所有已接受描述均已返回，且请求和返回的元素总数相同。

`return_span_cycles` 是首个成功返回拍到最后一个成功返回拍的包含端点周期数。
它包含期间的等待，可用于计算该区间的实际返回吞吐。
`consecutive_responses` 统计相邻周期连续成功返回，不将其作为 PE 利用率。
窗口通道未参与的全局池化任务保留零请求记录。

完成八次硬件逐层运行后，可以独立检查卷积几何与返回元素计数：

```bash
python test/performance_analysis/collect_window_pipeline.py \
  --measurements build/model_benchmark
```

该程序根据输入尺寸、卷积核、步幅、扩张率及填充计算 DW 的有效输入次数，
核对每层描述数与返回元素数，并生成 `window_pipeline.json`。
可选 `--previous` 指向另一个完整模型测量目录，比较相同模型和输入的硬件忙周期。

## 输出文件

| 路径 | 内容 |
|---|---|
| `sim/build.json` | SoC 配置、工具版本、源码和可执行文件标识 |
| `firmware_*/firmware.json` | 固件模式、编译选项、地址和依赖标识 |
| `results/cases/*/*/*/result.json` | 单次运行的周期、检查结果和硬件计数 |
| `results/cases/*/*/trace_*/tensors/` | 仿真中捕获的每层输出 |
| `summary/models.csv` | 完整模型周期、加速比及目标检查 |
| `summary/operators.csv` | 每类算子的周期、占比和加速比 |
| `summary/layers.csv` | 每层、每输入的周期及数据访问量 |
| `summary/summary.json` | 完整结构化汇总 |
| `window_pipeline.json` | 窗口并行请求、返回吞吐与独立几何计数检查 |

可独立重新生成汇总：

```bash
python test/model_benchmark/report.py \
  --out build/model_benchmark --prepared /path/to/prepared
```


## 同容量 RAW32 与压缩比较

`test/ps_compression/run_soc.py` 复用本目录的模型、固件和 SoC 测试程序，
使用同一 RTL 可执行文件和同一 ELF，在 Prepare 前切换 RAW32 或无损压缩策略。
共享 IA/PS 数据 RAM 为 14 KiB，按七个 2 KiB bank 分配；Conv、点卷积、Dense、
DW、池化、Add 和 Softmax 均使用实际硬件实现。

详细命令、周期定义和输出文件见 [PS 压缩测试说明](../ps_compression/README.md)。
