# 权重预取候选字段比较

`kernel_candidate_equal` 每三位并行比较当前字段和已保存字段，再用六路组合树合并。FPGA 综合保留各级中间结果，维持比较树的分组结构。该属性由既有 `p_use_lut` 参数控制，公开接口、完整字段位宽和采样周期保持一致。

有效预取候选已经包含 `PF_EMPTY` 条件。候选等待检查直接合并已保存的比较有效位、候选来源位、字段稳定结果和匹配结果，避免经过通用描述符选择条件。

完整加载器在相同公共源码、综合选项及参数下比较。参数为 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`REG_WIDTH=32`、`COUNT_WIDTH=29`，参考提交 `33bb1f22`。

| 项目 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 4,673 | 4,602 |
| 触发器 | 2,557 | 2,557 |
| RAMB18E1 | 16 | 16 |
| DSP48E1 | 0 | 0 |
| 候选输入至 `o_prefetch_quiescent` 的组合单元数 | 8 | 5 |
| 候选输入至 `prefetch_idle` 的组合单元数 | 9 | 6 |
| 模块内最长寄存器间组合单元数 | 13 | 14 |

该独立比较减少 71 个逻辑 LUT，候选输入与候选保存字段至后台空闲输出均减少 3 级组合单元。完整 SoC 的全局算术映射、后续调度逻辑和物理布局由整机报告统计。

## 验证

实际 FPGA 分支的两个完整模块配置 `COUNT_WIDTH=29/32` 在两个连续修改阶段分别通过 37,306 bit 形式等价比较。所有公开输出、对应寄存状态和存储内容均参加证明，外部输入不添加约束。

权重预取数值回归通过 285 个块、72,960 个权重值及 29,443 个周期，覆盖 S8/S16、尾块、预取命中、未完成传输命中、候选变化、取消、刷新、随机请求和读取发送重叠。运行启用未定义行为检查。

源文件散列、映射路径和运行统计见 [measurement.json](measurement.json)。

```sh
python3 test/frontend_rtl_structure/formal.py \
  --reference 33bb1f22 --cases kernel64 kernel64_c29 \
  --out /tmp/kernel_candidate_formal
python3 test/kernel_count_paths/prepare_measurement.py \
  --reference 33bb1f22 --out /tmp/kernel_candidate_inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config /tmp/kernel_candidate_inputs/cases.json \
  --cases loader_reference loader_current --out /tmp/kernel_candidate_synth
python3 test/kernel_candidate_fields/measure_paths.py \
  --synthesis /tmp/kernel_candidate_synth --out /tmp/kernel_candidate_paths.json
python3 test/kernel_prefetch/run.py --fpga --bus-width 64 \
  --verilator verilator-modern --out /tmp/kernel_candidate_numeric
```
