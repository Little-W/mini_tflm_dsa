# 前端配置范围与预读步长

短通道组的末端匹配使用扩展为 17 位的 `add_equal`，比较当前通道加常量偏移是否等于通道总数。扩展位保留溢出条件，各偏移的匹配结果并行归并为有效范围。

预读距离分别使用 `stride_w` 和 `dilation_w` 计算，两个结果保存组合边界，`kernel_w` 只选择最终结果。四态选择条件使用对应的原生定宽运算，保持 X、Z 输入的逐位传播。两项实现均保持原有寄存器边沿和公开周期。

## 检查范围

`check_configuration_selection.py` 提取当前 `conv_im2col_frontend.sv` 的完整组合表达式，并与 `configuration_reference.sv` 中保存的参考表达式比较。参考表达式取自完整前端文件 SHA-256 `122b4286b0d86cf28853810488b84a6f46a0a8d0dcd80f7d218ffbff459625c3`，保留输入和结果的完整位宽。

- 通道范围覆盖 `LANES=1/2/4/5/7/8`。
- 预读距离覆盖 `LINE_BYTES=1/8/16/32/64/128`。
- 12 组无约束 SAT 证明全部通过，不限制输入字段的值或相互关系。
- 124,416 次严格四态比较通过，包含单独 X、Z 位、混合未知位及随机已知数据。

## 局部映射

实际组合表达式两端加入相同的测试寄存器。范围案例使用 8 个通道，预读案例使用 16 字节缓存行；结果位宽完整保留。

| 表达式 | 逻辑 LUT：参考→当前 | 触发器：参考→当前 | 最长寄存器间路径：参考→当前 |
|---|---:|---:|---:|
| 通道范围 | 105→67 | 41→41 | 10→6 级 |
| 预读距离 | 95→117 | 103→103 | 8→7 级 |

预读表达式中，`kernel_w` 对应的输入寄存器至 `cfg_pf_step` 对应的输出寄存器路径由 8 级缩短至 4 级。所有映射组合图完整；当前两式均未推断 DSP 或块存储器。完整 DMA 与 SoC 的跨模块路径由相应完整模块测量检查。

[configuration_measurement.json](configuration_measurement.json) 保存当前前端源码 SHA-256、测试与生成表达式 SHA-256、逐配置证明结果，以及局部映射和固定端点路径。汇总程序核对证明与映射使用完全相同的生成表达式。

## 复现

在仓库根目录执行，需要 `pyosys` 和 Icarus Verilog：

```bash
python test/frontend_depth_timing/check_configuration_selection.py \
  --out build/frontend_configuration/validation
python scripts/fpga/open_fpga_synth.py \
  --case-config build/frontend_configuration/validation/cases.json \
  --cases group_reference group_current prefetch_reference prefetch_current \
  --max-register-path-cells 14 --out build/frontend_configuration/mapping \
  --lock-file /tmp/npu_synthesis_20261121.lock
python test/frontend_depth_timing/collect_configuration_selection.py \
  --validation build/frontend_configuration/validation \
  --group-reference build/frontend_configuration/mapping/group_reference \
  --group-current build/frontend_configuration/mapping/group_current \
  --prefetch-reference build/frontend_configuration/mapping/prefetch_reference \
  --prefetch-current build/frontend_configuration/mapping/prefetch_current \
  --out build/frontend_configuration/measurement.json
```

需要比较另一份完整前端源码时，给检查入口传入 `--reference-root`。默认参考表达式文件随测试代码保存。
