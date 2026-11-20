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

该脚本生成 21 项 WS/IS 数值、分片尺寸、共享容量与非法配置检查，在测试副本中加入原始容量表达式断言，检查 `npu_top` 的模块连接。共享存储采用 7 个 8192 字节物理存储块。

可通过 `--sim /path/to/simulator_directory` 复用容量 RTL 一致的生产仿真器，或通过 `--reference-sim /path/to/simulator_directory` 检查这些用例与既有生产版本的行为。两种复用方式均检查器件参数、64 位或 32 位总线、原始部分和配置及可执行文件摘要；参考版本方式在结果中单独标记为用例预期检查。

21 项用例已在 64 位总线、7 个 8192 字节物理存储块、`force_raw=True` 的生产参考仿真器上通过，完成 173,642 次 INT32 累加值检查。`r=32`、`w=5`、515 行的任务通过逐帧执行完成，每种 WS/IS 模式产生 594 条帧命令。两项传统窗口模式的非法行复用配置返回容量错误，其余五项非法配置返回参数错误。

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
