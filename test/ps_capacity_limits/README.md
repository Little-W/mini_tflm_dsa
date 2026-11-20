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

`npu_top` 保留总字节数、目录行数、参数范围和物理分配检查。配置第 0 阶段接收有界行数与帧数，第 1 阶段保存原始及长期保留容量结果，第 2 阶段保存容量无效标志；本模块不增加寄存器或配置周期。

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
```

独立模块证明共 17 组参数配置，全部通过。默认组合覆盖 6、7、8、9 个物理存储块以及每块 2048、4096、8192 字节。比较直接使用原始定宽截断、向上取整和乘法表达式，覆盖所有行数编码、所有帧数编码、全部 32 位分片尺寸、两种命令方式，以及原始数组内的全部索引，包括索引零与预留项。

顶层证明从参考提交和当前 `npu_top.sv` 提取实际容量表达式，将原有阶段寄存器作为任意共享输入状态。8 组配置均证明原始容量结果、长期保留容量结果、容量无效标志以及目录行数一致。容量无效标志和目录行数的比较覆盖全部 32 位物理分配输入；前两个结果在原始数组定义的索引范围内比较。

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
