# 量化寄存加法验证

`requant_registered_sum` 将完整定宽的左操作数、右操作数与一位进位相加，在使能时钟边沿保存结果。`vec_requant_full` 和 `requant_compute_lane` 使用 36 位配置完成商、输出偏移与舍入增量之和。

## 当前结构

模块通过普通 RTL 加法和 `always_ff` 描述数值及寄存周期。`p_use_dsp=1` 时，结果信号上的 `use_dsp` 属性允许综合工具合并算术与输出寄存器。通用配置使用相同的定宽表达式和时钟使能。

输入到输出为一个有效采样边沿。`i_en=0` 时结果保持；算术寄存器由外部有效位管理，不增加复位条件。结果按 `2^p_width` 取模。完整量化算术通道仍使用十二个寄存阶段，配置清除和数据暂停由调用模块的使能控制。

## 验证

```bash
python test/requant_registered_sum/run.py --out build/requant_registered_sum_formal
```

测试覆盖 1、17、36、48 位和两种 `p_use_dsp` 取值，共 8 组时序等价证明。两个操作数、进位和使能可在任意周期变化，检查完整输出位宽与暂停保持。`measurement.json` 保存实际源文件 SHA256、各组结果和一个有效边沿的延迟要求。

量化的独立整数参考测试见 `test/requant_compute_lane/run.py`，整体数值及控制验证由 `test/fpga_integration/run.py` 执行。资源数量与组合深度使用当前完整 SoC 的映射结果统计。
