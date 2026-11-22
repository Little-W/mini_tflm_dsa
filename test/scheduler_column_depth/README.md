# 调度器分组增量与帧选择

`ps_window_scheduler` 将列计数器分成最多八位的局部增量。第一组输入进位为一，其余组的输入进位由全部低位的与归约产生，各组独立求和。生产配置的列计数器为 29 位，依次使用 8、8、8、5 位四组，保留全部结果位和模溢出行为。

帧选择由独立的 `ps_scheduler_priority` 模块完成。每四个位置组成一组，各组并行计算首个有效位置的编号与存在信号，组间选择先前组均为空的首个有效组。含未知位的输入使用平展的优先选择表达式，保持四态行为。

扫描候选资格在独立的组合过程内计算，输入为 `live`、`frame_open` 和 `cursor`。`phase` 与 `protected_valid` 仅参与最终候选编号和存在性选择。原有状态分支的优先顺序及 `if` 条件保持一致，状态含未知位时仍按原分支规则选择输出。

`frame_open` 保存每个帧索引是否小于 `opened`。它在 `opened` 复位、任务开始、初始化命令完成及扫描结束的同一时钟边沿更新。帧选择直接读取该状态，减少计数比较与候选归并的串接。列状态更新、预测流水、命令接收和完成处理保持原有时钟边沿。元数据继续在保存索引的同一边沿同步读取，`frame_k` 保持原存储结构。

## 逐周期等价证明

`run.py` 从实际源码提取列增量表达式，支持对 1 至 33 位的每一种宽度执行无输入假设的组合 SAT 检查。完整调度器检查全部公开输出、共享时钟状态以及展开后的元数据和帧 K 存储。`--relation-nets frame_open` 将两侧的帧开放掩码加入证明输出，检查该派生状态每周期一致。此项关系不作为输入假设。

阶段数组检查使用 `reference_stage_arrays.sv`，其 SHA256 为 `1c084490ac7c4091dbec3fb763fa0fe6a0260c7bffd6e750e25e8a887727a521`。当前源码 SHA256 为 `e1cbd4eb9f8961b0b109213a24d7fe96e21b165c26e4099e9955cc60c41a8399`。生产配置的 29 位列增量检查通过，完整逐周期证明结果如下。

| SIZE | FRAME_COUNT | MAX_REUSE_TILES | 等价位数 |
|---:|---:|---:|---:|
| 16 | 16 | 32 | 2523 |

验证模型在存储展开后为八个数组元素提供对应的寄存器名称，寄存器、更新条件和连接保持不变。`prediction_depth_q[0:2]` 对应直接位置、直接位置选择准备和帧位置三个阶段；`prediction_column_q[0:2]` 保存相同阶段的列索引；`prediction_reads_frame_q[0:1]` 分别保存请求接收和帧选择阶段的元数据读取条件。所有 2523 个等价位均通过，未证明位数为零。结果保存在 [array_validation.json](array_validation.json)。

```bash
python test/scheduler_column_depth/run.py \
  --reference test/scheduler_column_depth/reference_stage_arrays.sv \
  --profiles 16:16:32 --widths 29 \
  --relation-nets frame_open \
  --out build/scheduler_column_depth/arrays
```

`--reference` 同时支持 Git 提交和源码文件；`--candidate` 可指定待检查的独立候选文件。

`support.py` 分别解析两侧实例化的子模块。参考文件内已有的模块定义优先保留，例如 `reference_scheduler.sv` 自带的 `ps_scheduler_any`；当前调度器补齐 `ps_scheduler_priority`。公共依赖包含 `onehot_check`、`parallel_prefix_add`、`regfile` 和 `unsigned_compare`。输入摘要分别记录主文件、子模块文件、组合后的源文件及各模块内容的 SHA256，验证结束时重新检查参与文件。

## 独立调度模型测试

```bash
python test/ps_compression/run_window_scheduler.py \
  --fpga \
  --out build/scheduler_column_depth/numeric
```

测试使用独立调度模型检查普通窗口和切片窗口，包含调度压力、帧标识复用、尾部帧、存储预留量、不同存储模式及错误配置。独立模型运行通过 975 个场景、182426 条命令；普通窗口为 321 个场景、52104 条命令，切片窗口为 654 个场景、130322 条命令。两次构建各有四个 C++ 编译单元，全部启用 UBSan。对应源码摘要和运行结果见 [numeric_validation.json](numeric_validation.json)。

编译命令与源码摘要共用 `with_dependencies` 生成的完整列表，包含 `ps_scheduler_priority`。`dependency_validation.json` 核对形式验证、局部映射和独立模型的主文件及子模块摘要，并确认每个实际编译的 RTL 文件均计入源码检查。

## 相同设置综合与路径分析

```bash
python test/scheduler_column_depth/measure.py \
  --reference test/scheduler_column_depth/reference_scheduler.sv \
  --out build/scheduler_column_depth/measurement \
  --lock-file /tmp/npu_synthesis_20261121.lock
```

以下数值来自 [current_measurement.json](current_measurement.json)。参考源码为 `reference_scheduler.sv`，SHA256 为 `34c943d79b79ab67f49a920e875592ba2f6bf64218e83fc06aa78767d56a68cb`；分组实现的测量输入源码 SHA256 为 `b2576300a71f270a644681de6bec571f4333634cdd9aef7d62c0e6e352701dde`。两侧使用 `synth_xilinx -family xc7 -noiopad -noclkbuf -flatten`，参数为 `SIZE=16`、`FRAME_COUNT=16`、`MAX_REUSE_TILES=32`，公共加法模块 SHA256 为 `f632432a888c1d027c4e1e1c3bfd77b33b10f6c48867ccfc57ce0497e994686f`。

| 项目 | 参考实现 | 分组实现 |
|---|---:|---:|
| 逻辑 LUT | 1469 | 1306 |
| 分布式 RAM 标称 LUT | 56 | 56 |
| 打包前标称 LUT 总数 | 1525 | 1362 |
| 触发器 | 950 | 916 |
| CARRY4 | 110 | 107 |
| BRAM36 / BRAM18 / DSP | 2 / 0 / 2 | 2 / 0 / 2 |
| 最长寄存器间组合路径 | 11 | 9 |
| `next_column_tile` 至预测列第一阶段 | 9 | 8 |
| `next_column_tile[0]` 至预测列第一阶段第 28 位 | 7 | 7 |
| `phase` 至 `selected_id_q` | 6 | 5 |
| `phase` 至帧 K 读取地址寄存器 | 7 | 6 |
| `protected_valid` 至 `selected_id_q` | 5 | 5 |
| `protected_valid` 至帧 K 读取地址寄存器 | 6 | 6 |

两侧连接图均完整，分别识别 `prediction_column_s0` 和 `prediction_column_q[0]` 作为预测列第一阶段。分组实现的公开输出从内部寄存器起点计算的最大组合深度为 3 级，对应 `reserve_rows`；其余公开输出均为 0 或 1 级。`selection_paths.py` 保存 `opened`、`protected_valid`、`phase` 以及公开接口的完整逐级路径。接口统计只在内存中的分析对象添加终点标记，综合网表保持原样，标记不计入组合级数。

以上为独立调度器的映射结果。完整 SoC 的综合、布局和布线结果用于确认集成后的路径级数、物理 LUT 数量及 150 MHz 时序。

## 汇总结果

```bash
python test/scheduler_column_depth/collect_report.py \
  --measurement build/scheduler_column_depth/measurement \
  --formal build/scheduler_column_depth/formal \
  --functional build/scheduler_column_depth/numeric \
  --out build/scheduler_column_depth/results.json
```

汇总程序要求综合与形式证明使用相同的 `--reference` 和 `--candidate`，并检查功能测试中的调度器、公共模块及独立子模块 SHA256。阶段数组证明和上述独立资源测量分别保存在 `array_validation.json` 与 `current_measurement.json`，各自记录对应的参考源码。
