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
| CPU | PicoRV32，RV32IM，硬件乘法和除法启用 |
| CPU 指令缓存 | 关闭 |
| NPU 核心 | 标准核心，`PCR_ENGINE=0` |
| 脉动阵列 | 16×16 |
| VCE | 8 个 PE，`TILE=16` |
| AXI 数据接口 | 32 位 |
| 外部 RAM | 2 MiB |
| RAM 附加固定延迟 | 默认 0，可用 `--latency` 指定 |
| IA 缓冲 | 8 个块 |
| PS 缓冲 | 16 个 frame，799 行物理存储 |
| 输出缓冲 | INT8 32 个块，INT16 4 个块 |
| 静态权重 | Prepare 阶段打包为 16×16 块 |
| 矩阵调度 | Prepare 阶段计算 WS/IS 和复用参数 |
| 张量 arena 上限 | 512 KiB，实际使用量逐模型记录 |
| AXI 未完成读写请求数 | 各 4 |
| DMA 窗口描述在途数 | 最多 4，返回携带 2 位输入区域标识 |
| 共享窗口缓存需求在途数 | 最多 4，按接收顺序返回 |
| 算术 | INT8，最近偶数舍入 |
| 编译 | C 和 C++ 同时设置软件或硬件开关，`-O3`、RV32IM |
| 输入 | 相同模型文件和相同输入字节 |

接口保留总线参数；此测试程序固定选择 32 位配置。
PicoRV32 使用仓库指定提交 `ef203c2b0a3fb793280f5114941416c425c5b461`。
编译器、仿真器、依赖、模型、输入、可执行文件和参与构建的源码均记录 SHA-256。

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
  --jobs 1 --run-jobs 4
```

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

## 周期与占比

完整模型周期由 CPU 在 `Invoke()` 前后读取 `rdcycle` 得到，包含算子执行、
硬件任务配置、DMA、状态轮询和解释器调度。模型初始化、静态权重打包、调度参数计算、张量分配、输入装载和结果检查
分别位于计时区间之外，两种执行模式使用相同边界。

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
