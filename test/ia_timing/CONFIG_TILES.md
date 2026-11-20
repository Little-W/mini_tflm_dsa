# IA 配置分块数提前计算

## 实现

`ia_loader` 在接收 `init_cfg` 的原有边沿保存 `packed_k_tiles_q`。该寄存值供
`ia_loader_ctrl` 计算分块字节步长与复用组步长，公开输出和配置生效周期保持一致。

有效 reduction 使用以下选择关系：

- `cfg_global_reduction` 非零时使用该输入。
- `cfg_global_reduction` 为零且当前状态为 `IDLE` 时使用即将接收的 `n`。
- `cfg_global_reduction` 为零且当前状态处于工作阶段时使用已保存的 `cfg_n`。

最后一项保持现有配置行为：`global_reduction_q` 在每次 `init_cfg` 时更新，
`cfg_n` 仅在 `IDLE` 接收配置时更新。分块数的计算保留原表达式：

```text
tiles(x) = (x >> LOG2_SIZE) + ((x & (SIZE - 1)) != 0)
```

当 `SIZE=16` 时，该表达式给出向上取整的分块数。新增寄存器在复位时清零，
未接收 `init_cfg` 时保持。因此每个边沿之后都有：

```text
packed_k_tiles_q = tiles(global_reduction_q != 0 ? global_reduction_q : cfg_n)
```

控制器增加默认关闭的 `p_precomputed_packed_tiles` 参数和
`cfg_packed_k_tiles` 输入。`ia_loader` 启用该参数并显式连接已保存的分块数。
独立实例保持默认参数时，仍直接使用本周期的配置输入完成计算。加法显式保留
`unused_packed_tiles_carry`，新增 RTL 未使用函数。

## 独立模块配置

参考提交为 `b0ccc7a`。两组测量均使用 `SIZE=16`、`BUS_WIDTH=64`、
`CACHE_BLOCKS=32`、`EXTERNAL_RAM=1`、`ORDERED_JOB=1`，分别设置
`COUNT_WIDTH=29` 和 `COUNT_WIDTH=32`。完整 SoC 在地址宽度 32、阵列尺寸 16
时采用 29 位计数器。

| 指标 | 29 位参考 | 29 位当前 | 32 位参考 | 32 位当前 |
|---|---:|---:|---:|---:|
| 逻辑 LUT | 5658 | 5724 | 5811 | 5825 |
| FF | 3056 | 3080 | 3083 | 3107 |
| CARRY4 | 434 | 434 | 434 | 434 |
| 分布式存储 LUT 位置 | 176 | 176 | 176 | 176 |
| DSP48E1 | 0 | 0 | 0 | 0 |
| RAMB18E1 / RAMB36E1 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 寄存器之间的最长组合单元数 | 15 | 13 | 15 | 12 |
| 到 `tile_row_step_b` 的最长组合单元数 | 11 | 1 | 11 | 1 |
| 到 `l2_group_row_step_b` 的最长组合单元数 | 15 | 12 | 15 | 12 |
| 到公开 `load_ia_req` 的最长组合单元数 | 12 | 11 | 12 | 11 |
| 到公开 `ext_dma_start` 的最长组合单元数 | 10 | 10 | 10 | 8 |
| 到公开 `ext_dma_p0` / `ext_dma_q0` 的最长组合单元数 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 |

两组配置均新增 24 个实现后的 FF，保存后续字节步长实际使用的分块数位。
29 位配置增加 66 个逻辑 LUT，32 位配置增加 14 个逻辑 LUT。

分块数计算被移到配置接收边沿之前。单独检查该输入阶段，两组配置下
`cfg_global_reduction` 输入到 `packed_k_tiles_q` 为 12 个组合单元，`n` 输入到
该寄存器为 10 个组合单元，已有 `cfg_n` 寄存器到该寄存器为 9 个组合单元。
`init_cfg` 直接连接寄存器使能。报告同时保留这些输入路径和寄存器之间的路径。

路径测量基于映射网表中的逐位连接关系，包含 CARRY4 的实际进位方向。
150 MHz 的工作频率由完整 SoC 的布局布线时序结果判断。

## 验证

七组完整模块等价检查共证明 **46,000 位**，不限制配置输入变化：

| 配置 | 等价位数 |
|---|---:|
| 独立控制器 `SIZE=3` | 1719 |
| 独立控制器 `SIZE=16` | 2540 |
| 独立控制器 `SIZE=32` | 2666 |
| 有序加载器，29 位计数器 | 11360 |
| 有序加载器，32 位计数器 | 11405 |
| 通用加载器 | 9740 |
| 本地存储加载器，`SIZE=3` | 6570 |

形式比较在参考模块中增加直接由原配置计算的组合观察值，检查
`packed_k_tiles_q` 与原始表达式一致。独立控制器比较为参考模块添加同名闲置
输入，以保持比较端口一致，参考功能保持原样。

数值回归同时逐周期比较全部 **39 个公开输出**，包括未使能时的输出值。
三组回归共运行 **583 项任务、237,282 个周期、1,083,872 次数值检查**。
测试包含紧凑与普通数据格式、分块打包、预取、配置切换、存储槽回绕、尾部行列，
以及预取运行时再次接收配置。全部通过。

## 复跑

```bash
source /workspace/scratch/92f7be750f11/toolchain/env.sh
python3 test/ia_timing/run_formal.py \
  --out build/ia_config_tiles/formal \
  --reference-rev b0ccc7a \
  --cases ctrl3 ctrl16 ctrl32 loader_ordered29 loader_ordered loader_generic loader_local3
python3 test/ia_timing/run_interface.py \
  --out build/ia_config_tiles/interface \
  --reference-rev b0ccc7a --verilator verilator-modern
python3 test/ia_timing/run_synthesis.py \
  --out build/ia_config_tiles/synthesis29 \
  --reference-rev b0ccc7a --count-width 29 \
  --lock-file /workspace/scratch/92f7be750f11/synth-small.lock
python3 test/ia_timing/run_synthesis.py \
  --out build/ia_config_tiles/synthesis32 \
  --reference-rev b0ccc7a --count-width 32 \
  --lock-file /workspace/scratch/92f7be750f11/synth-small.lock
```

对各综合结果目录中的 `mapped.json` 与 `pre_lut.il` 运行
`measure_config_paths.py` 和 `measure_demand_paths.py`，可重建配置路径和公开输出
路径报告。参数为 `--mapped`、`--pre-lut`、`--out`。

源码摘要、测试结果、资源计数、路径计数和原始报告摘要保存在
`docs/data/ia_config_tiles_validation.json`。
