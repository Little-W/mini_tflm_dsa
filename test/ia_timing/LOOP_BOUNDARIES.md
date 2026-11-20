# IA 组索引的并行增量比较

`ia_loader_ctrl` 使用两个 `add_equal` 实例，分别检查 `l2_idx + 1 == l2_group_last_idx` 和 `w_group_idx + 1 == w_group_last_idx`。两个实例的第二操作数为零，输入进位为一，保留 `COUNT_WIDTH` 位模运算。每个比较结果由循环末组标志与下一组的预取参数共用。

修改只替换组合比较，原有索引更新、事件优先级、复位值和公开接口保持一致。RTL 使用显式实例边界信号和中文注释，不新增函数或寄存器。

## 功能验证

参考提交为 `2d62bc00d98f373e4eaecd2718a10054e9071dc4`。最终控制器源码 SHA-256 为 `9ba475394471c73c8c9c1b9807e6c99f004c53529d536b07a3c292523f6f0931`。

| 形式配置 | 已证明的状态和输出位数 |
| --- | ---: |
| 控制器 SIZE3、BUS32、CACHE4、COUNT32 | 1,622 |
| 控制器 SIZE16、BUS64、CACHE32、COUNT32 | 2,444 |
| 控制器 SIZE32、BUS64、CACHE32、COUNT32 | 2,570 |
| 完整加载器 SIZE16、BUS64、CACHE32、COUNT29、有序任务 | 11,276 |
| 完整加载器 SIZE16、BUS32、CACHE4、COUNT32、通用任务 | 9,644 |
| 合计 | 27,556 |

全部输入不作取值约束，完整状态与公开输出比较均通过。三组数值测试继续逐周期比较全部 39 个公开输出，共 583 个命令或用例、237,282 个周期和 1,083,872 次数值检查，全部通过。

```sh
python3 test/ia_timing/run_formal.py \
  --out build/ia_loop_formal --reference-rev 2d62bc0 \
  --cases ctrl3 ctrl16 ctrl32 loader_ordered29 loader_generic
python3 test/ia_timing/run_interface.py \
  --out build/ia_loop_interface --reference-rev 2d62bc0 \
  --verilator verilator-modern
```

## 独立模块配置与测量

各版本均采用 SIZE16、BUS64、CACHE32、外置 RAM、有序任务，同一版 Yosys 和公共模块。分别测量 29 位与 32 位计数器配置。

| 指标 | COUNT29 参考 | COUNT29 并行比较 | COUNT32 参考 | COUNT32 并行比较 |
| --- | ---: | ---: | ---: | ---: |
| 逻辑 LUT | 5,616 | 5,658 | 5,750 | 5,811 |
| 触发器 | 3,056 | 3,056 | 3,083 | 3,083 |
| 分布式 RAM 的名义 LUT 数 | 176 | 176 | 176 | 176 |
| CARRY4 | 434 | 434 | 434 | 434 |
| DSP / BRAM | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 模块内最长寄存器路径 | 15 | 15 | 17 | 15 |
| 寄存器到 `load_ia_req` | 13 | 12 | 13 | 12 |
| 寄存器到 `ext_dma_start` | 11 | 10 | 9 | 10 |
| `l2_idx` 到 `pf_r_target` | 14 | 8 | 17 | 9 |
| `l2_idx` 到 `is_last_l2_group` | 13 | 7 | 16 | 8 |
| `w_group_idx` 到 `w_cur_r` | 15 | 10 | 15 | 11 |
| `w_group_idx` 到 `is_last_w_group` | 13 | 6 | 13 | 7 |

29 位配置增加 42 个逻辑 LUT，32 位配置增加 61 个逻辑 LUT，触发器数量均保持一致。坐标端口 `ext_dma_p0`、`ext_dma_q0` 的最长路径均保持 1 个单元。两个配置当前最长路径均从 `global_reduction_q` 进入 `u_ctrl.l2_group_row_step_b`，长度为 15 个单元。

表中的路径长度表示实际连接的组合单元数量，器件时钟频率由布局布线后的延迟报告确定。

```sh
python3 test/ia_timing/run_synthesis.py \
  --out build/ia_loop_synthesis --reference-rev 2d62bc0 \
  --count-width 29 --lock-file /path/to/synth.lock
python3 test/ia_timing/measure_loop_paths.py \
  --mapped build/ia_loop_synthesis/results/loader_candidate/mapped.json \
  --pre-lut build/ia_loop_synthesis/results/loader_candidate/pre_lut.il \
  --out build/ia_loop_synthesis/candidate_loop_paths.json
```

源码摘要、形式结果、逐周期结果、资源与具体路径保存在 [IA 循环边界验证数据](../../docs/data/ia_loop_boundaries_validation.json)。
