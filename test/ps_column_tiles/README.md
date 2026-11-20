# 部分和调度器列分块寄存

配置接收时保存列分块数，后续调度直接比较该寄存值与当前列位置。分块数通过高位整数部分和低位非零条件计算，保留零输入时原有定宽运算的结果。任务接收、帧顺序、容量处理和全部公开输出周期保持一致。

## 资源与路径

独立综合采用 `SIZE=16`、`FRAME_COUNT=16`、`MAX_REUSE_TILES=32`，参考提交为 `2f06471c`。

| 项目 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,308 | 1,309 |
| 分布式 RAM LUT 位置 | 108 | 108 |
| 触发器 | 895 | 892 |
| CARRY4 | 150 | 134 |
| DSP48E1 | 2 | 2 |
| 最长寄存器间组合单元数 | 19 | 14 |

实际连接图完整，无组合环。完整 SoC 的面积与时序由整合源码重新测量。

## 验证

三个完整状态比较配置全部通过，共 7,637 个比较点，外部输入未添加限制。配置包含单帧、十六帧生产参数，以及未限制复用分块数的四帧配置。

独立调度模型检查通过 975 个场景、182,426 个命令，覆盖普通调度、切片调度、压力处理、提前完成、帧编号复用、尾部分块和无效配置。全部 C++ 编译单元启用未定义行为检查。参数、源码摘要、实际报告与路径保存在 [measurement.json](measurement.json)。

## 运行

在仓库工具环境中执行：

```sh
python3 test/config_onehot/run_control_equivalence.py \
  --reference-ref 2f06471c \
  --cases scheduler_single scheduler_bounded scheduler_unbounded \
  --out build/ps_column_tiles/formal
python3 test/ps_compression/run_window_scheduler.py \
  --verilator verilator-modern --out build/ps_column_tiles/simulation
python3 test/ps_column_tiles/prepare_measurement.py --out build/ps_column_tiles/measure
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/ps_column_tiles/measure/cases.json --cases reference current \
  --out build/ps_column_tiles/synthesis --lock-file /path/to/synthesis-small.lock
```
