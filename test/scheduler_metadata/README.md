# 帧调度元数据的同步读取

`ps_window_scheduler` 将帧列坐标、行分块编号和有效行数合并存储。候选帧和预测帧分别使用一个同步读端口，在保存索引的同一时钟边沿读取元数据。命令和预测结果继续在原有周期产生，帧进度、容量检查和压力处理保持一致。

## 验证

形式比较覆盖5组矩阵尺寸、帧数和复用上限，包括单帧、3帧、16帧和17帧，以及有限和未限定复用参数。15,814位公开输出、寄存状态及完整帧元数据全部通过归纳等价检查。外部输入不附加取值约束。

独立数值模型完成975个配置场景、182,426个帧命令，覆盖切片、尾帧、帧编号复用、压力处理和无效配置。仿真同时启用未定义行为检查。

## 资源

完整调度器采用 `SIZE=16`、`FRAME_COUNT=16`、`MAX_REUSE_TILES=32`。

| 项目 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑LUT | 1,323 | 1,324 |
| RAM LUT | 108 | 56 |
| 名义LUT合计 | 1,431 | 1,380 |
| 触发器 | 892 | 892 |
| DSP48E1 | 2 | 2 |
| RAMB36E1 | 0 | 2 |
| 最长寄存器间组合路径 | 13级 | 13级 |

参考提交为 `954ed7c9`。两份独立综合网表的输入至输出最长组合路径均为17级；整机采用完整数据通路映射后单独检查组合深度。

```sh
python test/scheduler_metadata/run_formal.py --out build/scheduler_metadata/formal
python test/ps_compression/run_window_scheduler.py \
  --out build/scheduler_metadata/numeric --verilator verilator-modern
python test/scheduler_control/prepare_measurement.py --reference-rev 954ed7c9 \
  --out build/scheduler_metadata/inputs
python scripts/fpga/open_fpga_synth.py \
  --case-config build/scheduler_metadata/inputs/cases.json \
  --cases scheduler_reference scheduler_current --out build/scheduler_metadata/synthesis
```

源文件、工具、日志摘要和完整结果保存在 `measurement.json`。
