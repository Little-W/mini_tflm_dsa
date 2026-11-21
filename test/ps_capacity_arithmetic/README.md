# 部分和帧容量计算

`ps_frame_store_capacity` 分别检查实际行数和预留行数。起始行、请求行数和容量补码先生成并行和值及进位，FPGA 综合分支使用完整加法的最高进位判断范围。该加法通过 `use_dsp` 属性推断算术资源，保持当前周期完成容量检查。

高于物理容量宽度的请求位继续独立检查。大于等于 32 位的容量参数使用完整 64 位表达式，较小参数和事件仿真保留分组进位表达式。配置编码、空请求、定宽运算和未初始化输入的事件语义保持。

## 检查结果

- FPGA 与通用综合配置共 24 组全输入证明通过，比较对象为完整 64 位容量表达式，输入未增加限制。
- 四种位宽配置共 131,072 次严格四态比较通过。
- 14 位起始行、10 位存储深度、4 位存储块数量和两个 32 位请求行数的独立寄存边界测量为 64 个 LUT、79 个触发器、3 个 DSP，最长组合路径为 4 级。同参数参考提交为 77 个 LUT、79 个触发器、1 个 DSP 和 6 级。

```sh
python test/ps_capacity_arithmetic/run.py --out build/ps_capacity_arithmetic
python scripts/fpga/open_fpga_synth.py \
  --case-config test/ps_capacity_arithmetic/cases.json --cases capacity \
  --rtl-dsp-attributes --wide-alu-dsp-budget 740 \
  --out build/ps_capacity_arithmetic/measure
```

源码、参数、形式证明、四态检查及资源统计见 [validation.json](validation.json)。完整 SoC 路径与目标器件时序另行测量。
