# S8 恢复的行为级 SIMD 加法

`select_add` 在 `p_width=48`、`p_split_12bit=1` 时执行四个独立的 12 位模加。每个 `lane_sum` 保留普通加法表达式，`p_use_dsp=1` 为其设置 `use_dsp="simd"`。综合工具据此选择器件实现。输入选择、加法使能、通道边界和组合输出周期均保持一致。

生产 S8 恢复调用包含 16 个有符号 8 位数据和一个共享的有符号 9 位偏移。每个结果先保留完整的 10 位有符号和，再扩展为 16 位。`restore_bank.sv` 按这一调用关系构建独立测量模块。

## 功能检查

`run.py` 先检查接口及通用位宽分支的源码结构一致性，再检查 10 种位宽与 `p_use_dsp`、`p_split_12bit` 两个参数的全部二值组合，共 40 种配置。位宽为 1、8、12、16、17、24、32、48、64、128。

修改涉及的四路 12 位分支在 146 位完整输入上进行无约束二值等价证明。四态检查覆盖选择和使能的 0、1、X、Z 值，逐位注入操作数 X/Z，并覆盖通道边界、符号位、进位与多处未知数据。全部配置共完成 1,080,320 次严格逐位比较。

```bash
python test/select_add_simd/run.py \
  --reference test/select_add_simd/reference_select_add.sv \
  --candidate rtl/npu/compute/select_add.sv \
  --out build/select_add_simd/formal
```

## 默认映射及映射后检查

`measure.py` 使用项目默认的 `synth_xilinx -family xc7 -noiopad -noclkbuf -flatten` 流程。两份输入使用相同的调用模块、综合选项和器件模型。

| 16 通道 S8 恢复 | 参考实现 | SIMD 实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 144 | 0 |
| CARRY4 | 48 | 0 |
| DSP48E1 | 0 | 4 |
| 输入至输出的组合单元级数 | 4 | 1 |
| 新增寄存周期 | 0 | 0 |

四个推断 DSP 均使用 `FOUR12` 模式，内部寄存参数全部为 0。测量脚本读取综合器的 DSP 功能模型，展开实际映射网表，对 137 位完整调用输入和 256 位输出进行无约束二值等价证明。

```bash
python test/select_add_simd/measure.py \
  --reference test/select_add_simd/reference_select_add.sv \
  --candidate rtl/npu/compute/select_add.sv \
  --out build/select_add_simd/measurement \
  --lock-file /tmp/npu_area_leaf_20261121.lock
```

`summary.json` 记录形式与四态结果；`measurement.json` 记录资源、完整端口路径、源文件摘要和映射后证明。组合单元级数用于检查结构深度，150 MHz 的实际裕量由布局布线时序报告确认。

## 工具支持

AMD 的 [Vivado 2024.2 UG912 USE_DSP](https://docs.amd.com/r/2024.2-English/ug912-vivado-properties/USE_DSP) 列出 `SIMD` 属性值，并注明该属性适用于全部器件。对应的 [Vivado 2024.2 UG953 DSP48E1](https://docs.amd.com/r/2024.2-English/ug953-vivado-7series-libraries/DSP48E1) 说明 7 系列 DSP 的加法和 SIMD 功能；[UG479](https://docs.amd.com/v/u/en-US/ug479_7Series_DSP48E1) 定义四路 12 位模式。

当前源码同时供默认 Yosys 流程与 Vivado 使用。资源表来自默认 Yosys 映射；Vivado 的最终资源占用由对应器件的实现报告记录。
