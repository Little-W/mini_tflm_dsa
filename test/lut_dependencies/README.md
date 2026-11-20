# 查找表逐输出组合依赖

`scripts/fpga/lut_dependencies.py` 根据实际 `INIT` 和输入连接，分别计算 `LUT1` 至 `LUT6`、`LUT6_2` 各输出的输入敏感性。常量输入保持固定，连接到同一信号的多个引脚同时变化；未连接及未知输入作为独立自由变量。真值表缺失或含未知值时保留该输出全部可能的依赖。

`map_wide_alu.py` 为查找表每个输出建立独立节点，其他组合单元继续保留其输入依赖。`netlist_metrics.py`、`open_fpga_synth.py` 的组合深度统计，以及读取地址 DSP 的上游检查，使用相同的逐输出函数。综合清单和算术转换报告保存依赖分析模块的 SHA256。

配置接收原语的 `INIT=64'h8000_0000_8000_8000` 在 `I5=1` 时，`O5` 只依赖 `I0` 至 `I3`，`O6` 依赖 `I0` 至 `I4`。各输出独立参与拓扑排序及组合路径计数。寄存器分界、现有 DSP 的组合连接限制和选中 DSP 的级数限制保持完整。

## 验证

工具测试共76项，全部通过。其中逐输出依赖测试包括：

- 两输入及三输入查找表的全部真值表，分别结合常量和重复信号连接，共16,640种情况。
- 一至六输入查找表的600组固定随机真值表和连接，包含未知输入。
- 双输出共享输入、`I5` 固定值、重复信号抵消及重复信号仍有影响的函数。
- 实际配置接收反馈结构在三个分析入口中的完整拓扑排序和组合深度。
- 具有真实组合循环的函数，以及选中 DSP 和现有 DSP 的上下游组合限制。

`check_checkpoint.py` 使用原始引脚地址枚举独立计算敏感性，沿组合连接反向检查实际选中的算术单元。该检查独立于共享依赖函数，并逐项比较转换前后的网表内容。

R19 的实际算术网表检查结果如下：

| 项目 | 结果 |
| --- | ---: |
| 原有 DSP | 362 |
| 转换为 DSP 的算术单元 | 378 |
| 总 DSP 数量 | 740 |
| 按输出寄存参数检查的现有 DSP | 112 |
| 选中 DSP 的组合前驱数量 | 0 |
| 选中 DSP 到现有组合 DSP 的路径数量 | 0 |

转换内容仅包含选中单元的类型从 `$alu` 改为 `$__FPGA_DSP_ALU`；全部连接、参数、属性以及其他单元保持相同。实际输入、输出和工具源码的 SHA256 保存于 [measurement.json](measurement.json)。

## 重现

以下命令在仓库根目录执行，输入路径指向保留的 R19 `pre_alu.json`。

```sh
python3 -m unittest discover -s scripts/fpga -p 'test_*.py'
mkdir -p build/lut_dependencies/r19
python3 scripts/fpga/map_wide_alu.py \
  --input /path/to/round19/pre_alu.json \
  --output build/lut_dependencies/r19/mapped_alu.json \
  --report build/lut_dependencies/r19/mapping.json \
  --top soc_top --budget 740 --reserve 0 --minimum-width 8
python3 test/lut_dependencies/check_checkpoint.py \
  --input /path/to/round19/pre_alu.json \
  --mapped build/lut_dependencies/r19/mapped_alu.json \
  --selection build/lut_dependencies/r19/mapping.json \
  --top soc_top --out build/lut_dependencies/r19/verification.json
```
