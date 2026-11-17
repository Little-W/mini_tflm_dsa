# 仿真与 FPGA

以下命令在仓库根目录运行。首先执行 `git submodule update --init --recursive`，确保 PicoRV32 源码可用。

## 共享 IA/PS、DiP 与初始化配置

Verilator 检查使用统一 NPU 路径，并以独立整数模型比较输出。驱动、配置和原生接口测试可在主机执行。

```bash
make capacity-test
make dip-array-test VERILATOR=/path/to/verilator
make ps-stream-verify VERILATOR=/path/to/verilator
make shared-memory-test VERILATOR=/path/to/verilator
```

| 检查范围 | 内容与入口 |
|---|---|
| DiP | 完整行输入、对角传递、权重旋转、逐行选择与两组权重的重叠加载，见 [阵列测试](../test/dip_array/README.md)和[权重测试](../test/dip_weights/README.md) |
| 计算核心 | 生产 `compute_core`、多 K tile 的 INT32 中间和、PS 恢复与最终输出时序，见[计算核心测试](../test/compute_core/README.md) |
| 无损 PS | COPY、literal、Rice、Sparse128、frame 分配与逐行恢复，见 [PS 测试](../test/ps_compression/README.md) |
| 共享 bank | IA/PS 独立端口、同周期访问、字节写掩码、bank 分配、结构及物理映射，见[共享 RAM 映射](shared_ram_mapping.md) |
| AUTO 驱动 | 物理 AXI 读写拍、请求开销、WS/IS、R/W、bank 分配、严格范围与输出容量，见[容量检查](../test/capacity/README.md) |
| Prepared 接口 | 两套驱动 API、NMSIS 适配、arena 指针与软件回退，见 [TFLM 接口](../drivers/tflm/README.md) |
| 重复 Invoke | 模型、权重、持久配置、arena 用量和规划计数保持稳定，见[生命周期测试](../test/prepared_lifecycle/README.md) |

8 KiB bank 配置另行运行完整 NPU 的最大复用测试：

```bash
python3 test/shared_ia_ps/run_geometry_npu.py \
  --bank-count 7 --bus-width 64 --jobs 2 \
  --verilator /path/to/verilator --out build/shared_geometry
```

该测试覆盖 WS/IS、S8 R64、S16 输入 R32、硬件 im2col、packed 尾部、连续 K 与 frame 调度。固定与随机 AXI 等待共 36 个用例，检查 753,232 个 INT32 结果。输出缓冲与寄存器能力报告分别检查，确保完整行组的输出均有存储空间。

## 逐行权重选择与计算核心

阵列测试检查每个有效物理行的选择位和驻留权重，覆盖相邻组在不同物理行同时计算、选择与下一块加载同周期发生、加载空隙、输入空隙、连续选择及复位。权重加载测试使用生产 `kernel_loader_buffer`，逐项检查旋转后的权重和矩阵输出。

计算核心测试直接实例化生产 `compute_core`，可通过 Verilator 的 SystemVerilog 时序模式运行：

```bash
python3 test/compute_core/run.py --verilator /path/to/verilator \
  --out build/compute_core --jobs 1
```

默认用例为 SIZE/K=4/15、8/27、16/51，均包含四个 K tile 和尾部零填充。SIZE=16 同时检查 FIFO 存储，以及同一个 codec 可执行文件中的 RAW32 和 adaptive。五个用例共检查 3,392 个中间累加值、2,544 个恢复值和 848 个最终输出值，并检查完成信号与矩阵行的位置。每项结果记录源码、可执行文件和日志的 SHA-256。

完整 NPU 的权重切换测试同时检查 RAW32 与 adaptive，记录选择权重时阵列中的有效行、相邻 IA 组的重叠、FIFO 占用及 AXI 等待。直接输出用例覆盖单 K tile 的 WS 任务、S8 输出、逐张量量化、零偏置地址和额外输出容量；其他用例覆盖 PS 更新、偏置、逐通道量化、IS、S16 输出与逐 frame 调度。

```bash
python3 test/weight_switch/run.py --out build/weight_switch/default \
  --verilator /path/to/verilator --jobs 2
python3 test/weight_switch/run.py --out build/weight_switch/fpga \
  --bank-bytes 8192 --verilator /path/to/verilator --jobs 2
```

同一组输入分别在两个源码版本运行时，第二次执行可用 `--reference` 指向第一次的 `summary.json`。工具先检查输入、参考输出和物理配置，再计算周期比。完整用法见[权重切换测试](../test/weight_switch/README.md)。

## C7 检查汇总

下表按测试范围分别列出已完成的检查，源码和报告摘要保存在[当前结构化结果](measurements/row_weight_selection_20261116.json)中。

| 检查范围 | 运行数量 | 数值与状态检查 |
|---|---:|---|
| DiP 阵列与生产权重加载器 | 15 个阵列配置、4 个加载器配置 | 901,011 个输出值、4,198,095 次有效物理行的所选权重检查 |
| 生产计算核心 | 5 个用例 | 3,392 个中间和、2,544 个恢复值、848 个最终输出 |
| 完整 NPU | 默认 150 个、8 KiB bank 配置 36 个，共 186 个用例 | 1,725,496 个 INT32 累加值；输出、存储范围及错误完成状态分别检查 |
| C5/C7 权重切换比较 | 默认 88 组、FPGA 92 组，共 180 组版本配对 | 两版共 360 次运行；固定与随机 AXI 等待、RAW32 与 adaptive 均覆盖 |
| 完整网络 | 默认 32 次、FPGA 8 次，共 40 次 | 输出、逐层张量、模型与输入、PS 保存及恢复、初始化和 Invoke 周期 |
| Dense | 26 次 | 3 种批量 64 配置及 5 个原始算子的两个输入，两种 PS 策略分别运行 |
| PS 编码语料 | 24 份 trace、446,016 条记录 | 7,136,256 个恢复值；13 种候选合计检查 92,771,328 个恢复值 |
| 容量展开 | 4 个配置 | 默认与 FPGA 分别运行 RAW32/adaptive，各配置的两种策略具有相同缓冲数组和完整状态量 |

权重切换的完整 NPU 测试中，C7 共观测到 2,104 个不同物理行同时使用两组权重的周期。阵列与加载器测试逐项核对有效物理行的输入、选择位及权重。具体任务的组间间隔和总周期见[性能测量](shared_ia_ps_performance.md)。

## RAW32 与压缩模式比较

每个比较使用同一个 RTL 可执行文件、同一个固件 ELF、相同物理 RAM、相同模型和输入；在初始化前设置 RAW32 或 adaptive，并分别执行生产驱动 AUTO。记录配置、源码 SHA-256、模拟器与 ELF 摘要、硬件周期、CPU Invoke 周期和 PS 保存/恢复内容。

C7 测量包括默认 2 KiB × 7 bank 的 32 次完整网络运行、FPGA 8 KiB × 7 bank 的 8 次完整网络 trace、三种物理配置下的批量 64 Dense，以及五个原始 Dense 的两个输入。结果及复现命令见[性能测量](shared_ia_ps_performance.md)和[当前结构化结果](measurements/row_weight_selection_20261116.json)。perf 与 trace 分别汇总，初始化成本与 Invoke 成本分别报告。每份性能结果使用其记录的实现源码、二进制和固件摘要识别测量版本。

2026-11-16 归档的 [C5 结果](measurements/shared_ia_ps_20261116.json)保留实现提交 `8b4c9d9b9711b52877d2a8959f548979ffd9dfee` 的测量。C7 的 40 次网络运行与对应 C5 运行具有相同的初始化、规划和 Invoke 周期，模型、输入、固件及 PS 保存内容也逐项相同。默认硬件的四组完整 NPU 检查另包含 150 个用例和 972,264 次 INT32 比较。

分阶段导出包为各提交保存独立检查记录，包括 commit、tree、执行报告与 SHA-256。PS 接入、DiP、容量调度、TFLM arena、物理 RAM、测量工具和逐行权重选择分别提交。提交脚本逐阶段生成相应文件状态，并可在任一阶段结束或从已生成阶段继续。

## VCS

```bash
make vcs-unit
make vcs-axil
make vcs-soc
make vcs-nmsis-abi
make vcs-tflm
```

`vcs-unit` 运行 DMA、部分和存储、计算核心和 NPU 顶层测试；`vcs-axil` 和 `vcs-soc` 运行 UVM 测试；`vcs-nmsis-abi` 运行驱动接口测试。`make vcs-pcr-soc` 运行统一路径 PS 压缩的 SoC 测试。运行日志和构建产物分别位于 `build/vcs/` 和 `veri/sim/runs/`。

可用 `SIZE`、`IA_CACHE_BLOCKS`、`PS_FRAME_COUNT`、`SEED` 等变量设置参数，使用 `make help` 查看入口。

## Python 接口

[Python 模型说明](../veri/python_model/README.md)介绍 Verilator 后端的构建及逐周期比较。`veri/pcr_model/` 提供共享计算阵列与 PS 压缩的兼容构建入口，构建命令见 [TFLM 说明](../drivers/tflm/README.md)。

## FPGA

Vivado 工程入口、器件和时钟参数见 [Vivado 工程说明](../fpga/vivado/tflm_ai_dsa_soc/README.md)。例如：

```bash
vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/run_batch_synth.tcl
```

FPGA 默认配置为 `config/npu_fpga.mk`，共享 bank 为 8 KiB。Yosys 实际映射检查覆盖 6、7、8、9 个 bank，对应 12、14、16、18 个 `RAMB36E1`，共享数据容量全部使用。测试命令及独立 parity 容量见[共享 RAM 映射](shared_ram_mapping.md)。

本次已运行 Verilator 和 Yosys。当前环境没有 Vivado，Vivado 综合、布局布线和时序结果由上述工程流程生成。

## ASIC

SMIC40 标准单元、SRAM 宏、综合与功能仿真入口见 [ASIC 综合环境](../asic/README.md)。
