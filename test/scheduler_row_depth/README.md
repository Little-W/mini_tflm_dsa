# 帧调度器的行准备阶段

`ps_window_scheduler` 在已有准备阶段保存当前行组结束后的剩余行数和完成标志。行起点使用公共分组进位加法器更新，列分块数的单比特向上取整使用并行进位表达式。帧目标数量在 `PREPARE_TARGET` 保存，在 `OPENING`、`SWEEPING` 和 `DRAINING` 消费；进入准备阶段时清零该内部状态。

初始切片偏移与帧索引在同一个边沿保存。候选命令阶段直接使用该偏移或同步读取的元数据，通过分组进位加法器生成完整行地址。实际命令缓冲区写入条件下的偏移相等关系参加状态归纳证明。

帧索引、列索引和 K 进度的单步进位分别并行计算。切片取整使用已有 `PREPARING` 边沿保存行数减一，剩余列数使用公共分组进位加法器。

命令接受、暂停、背压、完成与错误响应的周期保持。16 个帧继续保留 688 bit 元数据、448 bit K 进度和两个元数据读取端口。

## 验证结果

- 5 组实际完整状态归纳比较，包含 `SIZE=1`、`FRAME_COUNT=3/17`、生产 16 帧配置及无限制复用配置。每周期比较全部公开输出和原有状态；`target` 在三个实际消费阶段的每个周期比较。存储返回每周期可任意变化，同时比较全部读写地址、数据、掩码和使能。外部输入没有范围或握手假设。
- 40,960 组四态样本检查实际列数取整、行地址、帧和列计数、K 进度、剩余列数及切片取整。参考算术的已知结果位保持，部分未知位可确定化；该测试不声明普遍四态等价。
- 975 个实际调度场景检查 182,426 条命令，包含切片、整组、背压、帧复用、提前完成、尾帧和错误配置。全部 C++ 翻译单元启用 UBSan。
- 4 个源码入口的 8 个完整调度器模型完成 Slang 展开、层次检查和连线检查。

生产参数为 `SIZE=16`、`FRAME_COUNT=16`、`MAX_REUSE_TILES=32`。完整模块使用相同的普通 RTL 映射参数，结果和源文件摘要保存于 [measurement.json](measurement.json)。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 1,232 | 1,298 |
| FF | 892 | 945 |
| RAM LUT | 56 | 56 |
| RAMB36E1 | 2 | 2 |
| DSP48E1 | 2 | 2 |
| 到 `phase` 的最长组合路径 | 14 | 8 |
| 到 `target` 的最长组合路径 | 14 | 8 |
| 到 `prepare_rows` 的最长组合路径 | 13 | 5 |
| 到 `row_base` 的最长组合路径 | 10 | 9 |
| 到 `command_buffer_row` 的最长组合路径 | 13 | 9 |
| 完整模块最长组合路径 | 14 | 9 |

上述数字来自开源映射和寄存器连接分析，实际 Vivado 面积、布线与 150 MHz 时序由整机工具报告确认。

## 复现

```bash
export PYTHONDONTWRITEBYTECODE=1
SCHEDULER_ROW_OUT=/tmp/scheduler_row_depth
python3 test/scheduler_row_depth/prove.py --out "$SCHEDULER_ROW_OUT/formal"
python3 test/scheduler_row_depth/check_four_state.py --out "$SCHEDULER_ROW_OUT/four_state"
python3 test/ps_compression/run_window_scheduler.py --out "$SCHEDULER_ROW_OUT/numeric"
python3 test/scheduler_row_depth/check_sources.py --out "$SCHEDULER_ROW_OUT/source_checks"
python3 test/scheduler_row_depth/prepare_measurement.py --out "$SCHEDULER_ROW_OUT/inputs"
python3 scripts/fpga/open_fpga_synth.py \
  --case-config "$SCHEDULER_ROW_OUT/inputs/cases.json" --cases reference current \
  --through pre_lut --out "$SCHEDULER_ROW_OUT/pre"
for version in reference current; do
  python3 scripts/fpga/remap_fpga_luts.py \
    --source "$SCHEDULER_ROW_OUT/pre/$version" --out "$SCHEDULER_ROW_OUT/mapped/$version" \
    --mode physical-cost --small-lut-area-cost 1 --max-lut-inputs 6 \
    --wire-delay-ps 500 --delay-target-ps 6667
done
python3 test/scheduler_row_depth/collect_report.py \
  --formal "$SCHEDULER_ROW_OUT/formal" --four-state "$SCHEDULER_ROW_OUT/four_state" \
  --numeric "$SCHEDULER_ROW_OUT/numeric" --source-checks "$SCHEDULER_ROW_OUT/source_checks" \
  --inputs "$SCHEDULER_ROW_OUT/inputs" --mapped "$SCHEDULER_ROW_OUT/mapped" \
  --out "$SCHEDULER_ROW_OUT/measurement.json"
```
