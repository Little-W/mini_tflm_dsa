# IA 尾组行数准备

`ia_loader` 在接收配置的时钟边沿保存尾组行数，与复用数、矩阵尺寸和尾部分块参数使用相同的配置使能。二的幂分块尺寸根据尾部余数选择完整分块数量，并直接连接低位行数；其他尺寸使用完整三十二位行数表达式。

`ia_loader_ctrl` 的 `p_precomputed_frame_rows` 参数默认关闭，独立实例保持组合计算。生产 `ia_loader` 明确启用该参数，并提供已保存的 `cfg_frame_rows_last`。普通组通过复用数移位得到行数，尾组使用保存结果。

复位时的行数、计数截断、三十二位回绕、忙碌期间配置输入以及所有命令周期均保持原有行为。RAM 容量和存储访问接口不变。

## 完整模块结果

生产参数为 `SIZE=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=29`、`CACHE_BLOCKS=32`、`EXTERNAL_RAM=1`、`ORDERED_JOB=1`。参考源码为 `a0e01073`。

| 映射方法 | 版本 | 逻辑 LUT | FF | 最长寄存器路径 |
| --- | --- | ---: | ---: | ---: |
| 普通 Xilinx 映射 | 参考 | 5,676 | 3,073 | 12 |
| 普通 Xilinx 映射 | 当前 | 5,728 | 3,080 | 12 |
| 物理面积成本映射 | 参考 | 5,080 | 3,073 | 13 |
| 物理面积成本映射 | 当前 | 5,005 | 3,080 | 13 |

两种映射中，全部寄存器到 `ps_frame_rows` 输出的最长路径均从 9 级缩短为 1 级。物理面积成本映射中，`row_tail_tiles` 和 `k` 配置输入到尾组行数寄存器分别为 9 级和 11 级。

这些级数来自完整映射图的实际连接，包含存储、进位和选择原语。配置输入和公开输出的边界只在路径分析中添加，未加入综合网表。完整 SoC 的连接和 6.667 ns 器件时序由整机综合及布线报告检查。

## 验证

完整加载器验证包含生产配置、完整三十二位计数、通用预取、小尺寸本地 RAM 以及非二的幂尺寸。独立控制器验证覆盖 `SIZE=3/16/32`，并使用默认组合计算参数。

八组形式比较共验证 51,526 位等价结果。形式比较使用完整 RTL 和全部存储状态，比较所有匹配状态与公开输出，不限制外部输入值或握手序列。参考设计增加的组合观察表达式描述已保存配置对应的尾组行数；归纳检查验证新寄存器与该表达式在复位、配置接收及保持周期的一致性。

逐周期接口比较复用了完整 IA 数值测试，同时向参考和当前实现输入相同事务，并在未使能周期继续检查公开输出。三个场景合计 237,282 个周期和 1,083,872 个数值，全部通过：

| 场景 | 周期 | 数值检查 |
| --- | ---: | ---: |
| 通用预取 | 57,160 | 179,920 |
| 有序任务预取 | 57,835 | 179,920 |
| 32 个缓存块，81 个分组任务 | 122,287 | 724,032 |

实际源码、测试、映射和路径文件的 SHA-256 保存在 `measurement.json`。

## 复现

```sh
python3 test/ia_frame_rows/run_formal.py --out build/ia_frame_rows/formal

python3 test/ia_timing/run_interface.py \
  --reference-rev a0e01073 --verilator /path/to/verilator \
  --out build/ia_frame_rows/interface

python3 test/ia_frame_rows/prepare_measurement.py --out build/ia_frame_rows/inputs

python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/ia_frame_rows/inputs/cases.json \
  --cases loader_reference loader_current --out build/ia_frame_rows/native \
  --lock-file /tmp/mini_tflm_dsa_synthesis.lock

python3 scripts/fpga/remap_fpga_luts.py \
  --source build/ia_frame_rows/native/loader_current \
  --out build/ia_frame_rows/physical/loader_current \
  --lock-file /tmp/mini_tflm_dsa_synthesis.lock

python3 test/ia_frame_rows/measure_paths.py \
  --mapped build/ia_frame_rows/physical/loader_current/mapped.json \
  --pre-lut build/ia_frame_rows/native/loader_current/pre_lut.il \
  --out build/ia_frame_rows/physical/loader_current/paths.json
```
