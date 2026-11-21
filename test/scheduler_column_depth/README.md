# 调度器分组增量与帧选择

`ps_window_scheduler` 将列计数器分成最多八位的局部增量。第一组输入进位为一，其余组的输入进位由全部低位的与归约产生，各组独立求和。生产配置的列计数器为 29 位，依次使用 8、8、8、5 位四组，保留全部结果位和模溢出行为。

帧选择按四个位置分组。组内与组间分别使用按二的幂跨度展开的或前缀，保存各层组合结果。每组的首候选检查先前组和先前位置是否为空，位置编码使用已确定的选择位。此结构限制共享表达式形成的逐帧排除长度。

扫描候选资格在独立的组合过程内计算，输入为 `live`、`frame_open` 和 `cursor`。`phase` 与 `protected_valid` 仅参与最终候选编号和存在性选择。原有状态分支的优先顺序及 `if` 条件保持一致，状态含未知位时仍按原分支规则选择输出。

`frame_open` 保存每个帧索引是否小于 `opened`。它在 `opened` 复位、任务开始、初始化命令完成及扫描结束的同一时钟边沿更新。帧选择直接读取该状态，减少计数比较与候选归并的串接。列状态更新、预测流水、命令接收和完成处理保持原有时钟边沿。元数据继续在保存索引的同一边沿同步读取，`frame_k` 保持原存储结构。

## 逐周期等价证明

`run.py` 从实际源码提取列增量表达式，对 1 至 33 位的每一种宽度执行无输入假设的组合 SAT 检查。完整调度器检查全部公开输出、共享时钟状态以及展开后的元数据和帧 K 存储。`--relation-nets frame_open` 将两侧的帧开放掩码加入证明输出，检查该派生状态每周期一致。此项关系不作为输入假设。以下五种配置全部通过。

| SIZE | FRAME_COUNT | MAX_REUSE_TILES | 等价位数 |
|---:|---:|---:|---:|
| 1 | 1 | 1 | 1242 |
| 4 | 3 | 4 | 1435 |
| 16 | 16 | 32 | 2493 |
| 16 | 16 | 0 | 3460 |
| 16 | 17 | 64 | 2631 |

参考源码保存在 `reference_scheduler.sv`，其 SHA256 为 `34c943d79b79ab67f49a920e875592ba2f6bf64218e83fc06aa78767d56a68cb`。当前源码 SHA256 为 `9f6d1f5376caf4bada59b2f16ee7951c6e5ad249415ec0b6f249b8dc405e4dcb`。两侧使用同一组公共依赖。

```bash
python test/scheduler_column_depth/run.py \
  --reference test/scheduler_column_depth/reference_scheduler.sv \
  --relation-nets frame_open \
  --out build/scheduler_column_depth/formal
```

`--reference` 同时支持 Git 提交和源码文件；`--candidate` 可指定待检查的独立候选文件。

## 独立调度模型测试

```bash
python test/ps_compression/run_window_scheduler.py \
  --out build/scheduler_column_depth/numeric
```

测试使用独立调度模型检查普通窗口和切片窗口，共通过 975 个场景、182426 条命令。检查包含调度压力、帧标识复用、尾部帧、存储预留量、不同存储模式及错误配置。C++ 测试程序启用 UBSan。

## 相同设置综合与路径分析

```bash
python test/scheduler_column_depth/measure.py \
  --reference test/scheduler_column_depth/reference_scheduler.sv \
  --out build/scheduler_column_depth/measurement \
  --lock-file /tmp/npu_synthesis_20261121.lock
```

两侧使用 `synth_xilinx -family xc7 -noiopad -noclkbuf -flatten`，参数为 `SIZE=16`、`FRAME_COUNT=16`、`MAX_REUSE_TILES=32`，公共加法模块 SHA256 为 `746fd83d9dc5c704f6536b9521ab65ea825fa62065e1217e7758fddf92867280`。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 1481 | 1478 |
| 分布式 RAM 标称 LUT | 56 | 56 |
| 打包前标称 LUT 总数 | 1537 | 1534 |
| 触发器 | 950 | 950 |
| CARRY4 | 110 | 110 |
| BRAM36 / BRAM18 / DSP | 2 / 0 / 2 | 2 / 0 / 2 |
| 最长寄存器间组合路径 | 11 | 11 |
| `phase` 至 `selected_id_q` | 6 | 4 |
| `phase` 至帧 K 读取地址寄存器 | 7 | 5 |
| `protected_valid` 至 `phase` | 5 | 5 |
| `protected_valid` 至 `selected_id_q` | 5 | 4 |
| `protected_valid` 至帧 K 读取地址寄存器 | 6 | 5 |
| `protected_valid` 至 `cursor` | 5 | 5 |
| `protected_valid` 至 `next_column_tile` | 5 | 5 |

两侧均使用 16 位 `frame_open` 状态，本次组合结构调整不增加寄存状态或流水级。公开输出从内部寄存器起点计算的最大组合深度为 3 级，对应 `reserve_rows`；其余公开输出均为 0 或 1 级。`selection_paths.py` 保存 `opened`、`protected_valid`、`phase` 以及公开接口的完整逐级路径。接口统计只在内存中的分析对象添加终点标记，综合网表保持原样，标记不计入组合级数。

以上为独立调度器的映射结果。完整 SoC 的综合、布局和布线结果用于确认集成后的路径级数、物理 LUT 数量及 150 MHz 时序。

## 汇总结果

```bash
python test/scheduler_column_depth/collect_report.py \
  --measurement build/scheduler_column_depth/measurement \
  --formal build/scheduler_column_depth/formal \
  --functional build/scheduler_column_depth/numeric \
  --out build/scheduler_column_depth/results.json
```

汇总程序检查综合、形式证明与功能测试中的调度器及公共依赖 SHA256，并保存统一摘要。本次结果见 [measurement.json](measurement.json)。
