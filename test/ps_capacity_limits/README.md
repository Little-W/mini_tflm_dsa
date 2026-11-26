# 部分和容量常量表

`ps_capacity_limits` 用于共享物理存储、32 位原始部分和的容量检查。模块按物理存储块数与活动帧数选择编译时常量，只保留运行时选择和比较。

每行占用四个 128 位存储字。设行数为 `rows`、活动帧数为 `frames`、分配的存储块数为 `banks`、每个存储块深度为 `depth`，则对非零帧数有：

\[
\left\lceil\frac{4\,rows}{banks}\right\rceil frames \leq depth
\quad\Longleftrightarrow\quad
rows \leq
\left\lfloor\frac{banks\left\lfloor depth/frames\right\rfloor}{4}\right\rfloor.
\]

表覆盖帧数信号的全部编码，包含超出实际物理帧数的编码。零帧检查与原始表达式一致。行数上限同时受最大可表示分组行数限制。分帧命令使用两个候选行数的比较结果计算 `min(rows, slice_tiles*SIZE)` 的容量条件。

`npu_top` 保留总字节数、目录行数、参数范围和物理分配检查，配置准备使用八个相位。相位 0 接收有界行数与帧数，相位 1 保存原始及长期保留容量结果，相位 2 保存分片尺寸，相位 3 保存目录行数，相位 4 保存容量无效标志，相位 5 保存分块检查结果，相位 6 保存帧配置错误码，相位 7 等待计算控制器与帧调度器就绪后提交配置。分片选择、目录步长和后续容量检查分别经过寄存器。

## 完整输入形式证明

```sh
python3 test/ps_capacity_limits/run_formal.py \
  --out build/ps_capacity_limits_formal

python3 test/ps_capacity_limits/run_formal.py \
  --out build/ps_capacity_limits_production_formal \
  --bank-counts 7 --bank-bytes 8192 --max-rows 512

python3 test/ps_capacity_limits/run_formal.py \
  --out build/ps_capacity_limits_wide_frame_formal \
  --bank-counts 6 9 --bank-bytes 2048 8192 \
  --max-rows 128 --frames-width 7

python3 test/ps_capacity_limits/run_top_formal.py \
  --out build/ps_capacity_limits_top_formal

python3 test/ps_capacity_limits/run_pipeline_formal.py \
  --out build/ps_configuration_pipeline_formal

python3 test/ps_capacity_limits/run_pipeline_four_state.py \
  --out build/ps_configuration_pipeline_four_state
```

独立模块证明共 17 组参数配置，全部通过。默认组合覆盖 6、7、8、9 个物理存储块以及每块 2048、4096、8192 字节。比较直接使用原始定宽截断、向上取整和乘法表达式，覆盖所有行数编码、所有帧数编码、全部 32 位分片尺寸、两种命令方式，以及原始数组内的全部索引，包括索引零与预留项。

顶层组合证明从参考提交和当前 `npu_top.sv` 提取实际容量表达式，将行数、帧数及容量阶段寄存器作为任意共享输入状态，并将分片、目录寄存器展开为各自输入公式。8 组配置均证明原始容量结果、长期保留容量结果、容量无效标志、目录行数及分片尺寸一致。容量无效标志和目录行数的比较覆盖全部 32 位物理分配输入；前两个结果在原始数组定义的索引范围内比较。

配置流水证明直接提取实际相位计数器和各组捕获过程。在第 2 级入口保存任意配置字段，直到配置提交时保持这些字段，逐相位证明容量结果、分片尺寸、目录行数和容量错误标志等于参考公式。8 组配置均通过无界归纳；首个采样周期为复位，后续复位、控制器就绪和调度器就绪信号均可任意变化。

四态测试覆盖 6、7、9 个物理存储块，每组运行 20,000 个周期，检查等待、运行中复位、合法及非法配置，以及包含未知位的配置字段。三组共完成 4,509 次配置提交、13,491 次等待和 177,597 次寄存值比较。结果与源码摘要保存在 [pipeline_measurement.json](pipeline_measurement.json)。配置准备增加两个内部周期，全部数据、存储容量和错误码保持；运行期数据传输不增加阶段。

## 综合测量

```sh
python3 scripts/fpga/open_fpga_synth.py \
  --case-config test/ps_capacity_limits/cases.json \
  --cases capacity_reference_production capacity_candidate_production \
  --out build/ps_capacity_limits_production_synthesis \
  --lock-file /path/to/synth-small.lock
```

测量模块在输入和输出两侧加入相同的寄存器，报告连通寄存器之间的路径。生产配置采用 512 行分组上限、5 位帧数、7 个 8192 字节物理存储块。

| 配置 | 版本 | LUT | DSP | 最长寄存器间组合路径 |
| --- | --- | ---: | ---: | ---: |
| 生产参数 | 原始算术 | 267 | 1 | 36 个单元 |
| 生产参数 | 容量常量表 | 127 | 0 | 11 个单元 |
| 1024 行上限、每块 2048 字节 | 原始算术 | 294 | 1 | 39 个单元 |
| 1024 行上限、每块 2048 字节 | 容量常量表 | 109 | 0 | 10 个单元 |

输入寄存器的实际保留位数由各版本的输出依赖关系决定，独立模块本身为组合逻辑。上述路径长度用于定位逻辑深度，时钟周期由器件布局布线后的延迟决定。

## 完整 NPU 回归

```sh
python3 test/ps_capacity_limits/run_npu.py \
  --out build/ps_capacity_limits_npu \
  --verilator verilator-modern --jobs 2 --bus-width 64
```

该脚本先读取仿真程序的 `build.json`，再根据 `IA_COMPACT_ENABLE`、`PS_FRAME_COUNT`、物理存储块大小和数量生成用例。基本集合包含 21 项 WS/IS 数值、INT8/INT16 输入、分片尺寸、共享容量与非法配置检查；矩阵尺寸和独立数值参考保持固定，输入存储分配及复用数使用实际硬件允许的范围。脚本进一步检查 WS/IS 的最小合法复用、最大合法复用、零复用和越界复用。非紧凑配置还分别检查单个 IA 存储块被拒绝的情况，共执行 31 项检查。

独立构建将 `npu_capacity_observer.sv` 绑定到 `npu_task_configuration`，读取实际容量信号并比较完整定宽算式。原始及长期容量比较要求配置第二级有效、存储块索引位于数组范围内且配置相位不小于 1，接收容量比较要求配置相位不小于 4。构建清单记录该观察器的文件摘要。共享存储采用 7 个 8192 字节物理存储块。

可通过 `--sim /path/to/simulator_directory` 复用容量 RTL 一致的生产仿真器，或通过 `--reference-sim /path/to/simulator_directory` 检查这些用例与既有生产版本的行为。两种复用方式均检查器件参数、64 位或 32 位总线、原始部分和配置及可执行文件摘要；`--sim` 还核对 `npu_top.sv`、`npu_matrix_engine.sv`、`npu_task_configuration.sv` 和 `ps_capacity_limits.sv` 四个文件的 SHA-256。参考版本方式在结果中单独标记为用例预期检查。程序复用直接运行已构建的可执行文件，结果记录实际硬件参数、生成公式、每项合法与非法条件及容量源码。

```sh
python3 test/ps_capacity_limits/run_npu.py \
  --out build/ps_capacity_limits_reuse \
  --sim /path/to/simulator_directory --bus-width 64

python3 test/ps_capacity_limits/test_runner.py

python3 test/ps_capacity_limits/check_observer_phase.py \
  --out build/ps_capacity_limits_observer_phase
```

观察器四态测试直接提取配置相位计数、行数与帧数保存、目录行数保存以及容量计算过程，覆盖 64 次配置、62 次连续配置、复位后首次采样和 128 次等待。645 个周期中完成 1152 次容量比较，并分别确认三项断言在各自有效阶段检测到输入不一致。结果及源码摘要保存在 `summary.json`。入口单元测试覆盖源码确认、可执行文件摘要、两种程序复用方式以及独立构建的观察器来源记录。

对于 `SIZE=16`、`IA_COMPACT_ENABLE=0`、`PS_FRAME_COUNT=16` 的生产配置，每个 8192 字节 IA 存储块包含 16 个 512 字节输入块。双缓冲使每个物理存储块支持 8 个复用 tile，合法任务至少分配两个 IA 存储块，因此最大复用数为 16。紧凑输入每块支持 16 个复用 tile；IS 的流式输入为 INT8 权重，WS 使用左操作数的实际位宽。

| 容量条件 | 生产配置的检查结果 |
| --- | --- |
| 两个 IA 存储块，`r=1` 或 `r=16` | 合法，比较完整数值输出 |
| `r=0` 或 `r=32` | 保存的目录步长为零，返回容量错误 2 |
| 一个非紧凑 IA 存储块，`r=8` | 返回配置错误 1 |
| 非法存储块数量、权重窗口或控制字段 | 返回配置错误 1 |

共享原始部分和路径每帧最多保存 `MAX_IA_REUSE * SIZE = 256` 行，每个物理存储块具有 512 个 128 位存储字。对于 `frames > 0`，行数上限为 `min(256, floor(ps_banks * floor(512 / frames) / 4))`。结果同时记录实际 `PS_STORAGE_ROWS`、INT16 写回 FIFO 容量和矩阵量化并行度，便于识别完整仿真配置。

31 项参数化用例分别用于 ASIC 和 FPGA 编译方式，每种方式比较 192,822 个 INT32 累加值。基本 21 项保留 173,642 个数值结果，新增边界用例覆盖 19,180 个数值结果；原有 84 份输入和独立数值参考文件逐字节保持相同。`r=16`、`w=5`、515 行的任务通过逐帧执行完成，每种 WS/IS 模式产生 594 条帧命令。各次完成情况、实际参数和结果保存在 [configuration_validation.json](configuration_validation.json)。

## 有界列数计算

帧数计算并行比较原始列数和窗口上界，再选择窗口大小或按块向上取整的列数。配置准备相位 0 保存结果，执行阶段和命令时序保持。64 位加法溢出时按照原始定宽表达式返回零。

```sh
python3 test/ps_capacity_limits/run_window_formal.py \
  --reference 2297cb12 --out build/ps_window_count
```

该证明直接提取实际 `npu_top` 中的列数计算，覆盖全部输入编码。19 组参数包含 4、16、32、64 位配置字段，1、3、16、17、32 列的块尺寸，以及不同宽度的窗口和容量计数。

生产参数下，独立寄存器间测量的逻辑 LUT 为 20，最长组合路径为 6 级；相同输入和输出寄存器的参考实现为 13 个逻辑 LUT、11 级。映射使用六输入 LUT、面积成本 1、连线成本 500 ps 和目标 6,667 ps。该结果描述局部逻辑，完整 SoC 与器件时序分别测量。详细结果保存于 [window_measurement.json](window_measurement.json)。

```sh
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/ps_window_count/cases.json \
  --cases reference candidate --through pre_lut \
  --out build/ps_window_count/pre
for version in reference candidate; do
  python3 scripts/fpga/remap_fpga_luts.py \
    --source build/ps_window_count/pre/$version \
    --out build/ps_window_count/mapped/$version \
    --mode physical-cost --wire-delay-ps 500 --delay-target-ps 6667 \
    --max-lut-inputs 6 --small-lut-area-cost 1
done
```
