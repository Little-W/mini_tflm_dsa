# 帧调度扫描与优先编码

`ps_scheduler_priority` 将候选帧分成两帧一组。组内编号与前序分组的空资格并行计算，
各组编号按空资格合并。`ps_window_scheduler` 分别准备开帧、保护帧、游标之后的候选帧
以及绕回后的候选帧编号，最终按位归并四类结果。
帧目录、命令状态和同步读取边沿保持不变。

## 验证范围

完整调度器证明比较全部公开输出、共同寄存器状态、完整元数据存储和归约进度存储。
五种参数配置为 `(SIZE, FRAME_COUNT, MAX_REUSE_TILES)`：
`(1,1,1)`、`(4,3,4)`、`(16,16,32)`、`(16,16,0)`、`(16,17,64)`。
证明不限制外部输入序列。

扫描选择检查编号宽度 1、2、4、5、8，完成 409,610 次四态比较。
优先编码检查 13 种帧数与编号宽度组合，包括 1 至 129 帧、非二次幂帧数、
较窄及较宽的输出编号。每种配置均完成任意二态输入的组合证明，四态检查次数
记录于 `priority_validation.json`。未知值按完整优先级表达式传播。

```sh
python test/scheduler_scan_selection/measure.py --out build/scheduler_scan/measure
python test/scheduler_column_depth/run.py \
  --reference build/scheduler_scan/measure/reference_rtl/ps_window_scheduler.sv \
  --out build/scheduler_scan/state --widths 29 \
  --profiles 1:1:1 4:3:4 16:16:32 16:16:0 16:17:64
python test/scheduler_scan_selection/run.py --out build/scheduler_scan/scan
python test/scheduler_scan_selection/priority.py --out build/scheduler_scan/priority
```

测量程序从参考提交分别保存调度器和优先编码模块，两侧各自解析实际依赖。
因此完整模块比较同时覆盖优先编码结构和扫描结果选择。

## 测量结果

参数为 `SIZE=16`、`FRAME_COUNT=16`、`MAX_REUSE_TILES=32`，采用 xc7 LUT 映射。
映射执行 ABC9 功能验证，全部组合图无环且已遍历完整。

| 指标 | 参考提交 `92f722e6` | 当前设计 |
|---|---:|---:|
| 完整调度器 LUT 数量 | 1,113 | 1,141 |
| 完整调度器最长寄存器路径 | 10 | 10 |
| `frame_open` 到任一寄存器 | 10 | 8 |
| `frame_open` 到候选编号寄存器 | 9 | 7 |
| `frame_open` 到帧归约进度同步读取寄存器 | 10 | 8 |

`state_validation.json`、`scan_validation.json`、`priority_validation.json` 保存验证摘要；
`measurement.json` 保存资源统计、实际路径和源文件摘要。
目标器件的 150 MHz 建立与保持时间由完整布局布线报告确认。
