# 调度器列计数器的分组增量

`ps_window_scheduler` 将 `next_column_tile + 1` 分为最多八位的局部增量。第一组的输入进位为一，其余各组的输入进位等于该组以下所有位的与归约。各组独立求和，最高组允许不足八位。生产配置的列计数器共 29 位，分为 8、8、8、5 位四组。

`column_after_part` 同时提供给列状态更新和预测选择。预测阶段仍在原有时钟边沿保存列号，后续预测寄存器和命令时序保持一致。该实现保持全部结果位、模溢出行为及原有参数范围。

## 无约束等价验证

```bash
python3 test/scheduler_column_depth/run.py
```

脚本从参考提交 `4dee27ffec4dc891daf2681379f8b3fd27fd41f2` 和当前文件提取实际列增量表达式，对 1 至 33 位的每一种宽度执行无输入限制的组合 SAT 证明。完整调度器比较包括全部公开输出、同名状态和展开后的帧存储，使用以下参数执行逐周期等价证明。

| SIZE | FRAME_COUNT | MAX_REUSE_TILES |
|---:|---:|---:|
| 1 | 1 | 1 |
| 4 | 3 | 4 |
| 16 | 16 | 32 |
| 16 | 16 | 0 |
| 16 | 17 | 64 |

结果及生成的 Yosys 脚本保存在 `build/scheduler_column_depth/formal/`。生产配置证明了 3,595 个等价位。

## 独立调度模型测试

```bash
python3 test/ps_compression/run_window_scheduler.py \
  --out build/scheduler_column_depth/functional
```

测试使用独立调度模型检查普通窗口和切片窗口，共 975 个场景、182,426 条命令，包含调度压力、帧标识复用、尾部帧、存储预留量、不同存储模式及错误配置。C++ 测试程序启用 UBSan。

## 相同设置综合

```bash
python3 test/scheduler_column_depth/measure.py
```

参考实现和当前实现采用同一组公共依赖，使用 `synth_xilinx -family xc7 -noiopad -noclkbuf -flatten`、`SIZE=16`、`FRAME_COUNT=16`、`MAX_REUSE_TILES=32`。测量结果保存在 `build/scheduler_column_depth/measurement/`。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT 单元 | 1,416 | 1,378 |
| 分布式 RAM 名义 LUT 数量 | 56 | 56 |
| 打包前名义 LUT 总数 | 1,472 | 1,434 |
| 触发器 | 935 | 935 |
| CARRY4 | 87 | 95 |
| BRAM36 / BRAM18 / DSP | 2 / 0 / 2 | 2 / 0 / 2 |
| 模块最长寄存器间组合路径单元数 | 12 | 11 |
| 列计数器至预测列寄存器的最大组合路径单元数 | 9 | 8 |
| 列计数器至下一列状态的最大组合路径单元数 | 9 | 9 |
| `next_column_tile[0]` 至 `prediction_column_s0[28]` 的组合路径单元数 | 9 | 7 |

当前实现减少 38 个逻辑 LUT 单元，使用综合工具自动推断的进位资源。路径统计使用综合后实际连接的单元，并区分各个输出位的依赖关系。完整 SoC 的布局布线报告用于确认最终 LUT 数量和 150 MHz 时序。

## 汇总结果

```bash
python3 test/scheduler_column_depth/collect_report.py
```

汇总程序检查综合、形式验证和功能测试使用的调度器 SHA-256 是否相同，再保存 `build/scheduler_column_depth/results.json`。本次测量与验证摘要见 [measurement.json](measurement.json)。
