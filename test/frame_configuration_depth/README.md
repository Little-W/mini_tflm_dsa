# NPU 配置阶段控制验证

`npu_top` 在现有配置准备阶段保存帧执行资格和输出空间预留值。容量计算、帧模式保存及调度器启动使用同一次配置提交，任务启动周期保持不变。偏置行更新分别形成递增资格和清零资格，保留原有优先级。

## 检查范围

`run.py` 从实际顶层源码提取配置相位、帧资格、目录行数及保存条件，覆盖六组寄存器宽度和帧执行选项。复用次数和控制字按实际配置进入条件保存，其余输入和就绪信号任意。检查相位、启动周期，以及消费阶段的帧资格和目录行数。

`run_output_control.py` 检查五组输出空间预留配置和六组偏置行计数宽度。配置进入、复位、背压和资格输入均按声明的范围变化。20,000 个四态仿真周期包含 1,906 次配置提交、12,845 次预留值比较和 120,000 次偏置行结果比较。

`collect_report.py` 要求上述结果和完整 `npu_top` 的 Slang 严格解析使用相同源码，并核对解析脚本和输出文件。当前结果保存在 [measurement.json](measurement.json)，其中逐项记录源码和测试文件的 SHA-256。

## 复现

在仓库根目录执行，需要 `pyosys` 和 Icarus Verilog：

```bash
python test/frame_configuration_depth/run.py \
  --reference-ref aa0a169c --out build/frame_configuration_depth/frame
python test/frame_configuration_depth/run_output_control.py \
  --reference-ref aa0a169c --out build/frame_configuration_depth/output_control
python scripts/fpga/open_fpga_synth.py \
  --cases npu_top --through elaborate \
  --out build/frame_configuration_depth/elaboration \
  --lock-file /tmp/npu_synthesis_20261121.lock
python test/frame_configuration_depth/collect_report.py \
  --frame build/frame_configuration_depth/frame \
  --output-control build/frame_configuration_depth/output_control \
  --elaboration build/frame_configuration_depth/elaboration/npu_top \
  --out build/frame_configuration_depth/measurement.json
```

这些检查确认配置和公开启动周期的一致性。完整 SoC 的组合级数和布局布线时序由对应的整机报告检查。
