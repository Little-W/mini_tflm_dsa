# 二项加法等式的并行进位检查

`rtl/common/add_equal.sv` 是组合逻辑模块，检查下列等式：

```text
o_equal = ((i_a + i_b + i_carry_in) mod 2^p_width) == i_target
```

参数 `p_width` 默认为 32，合法取值为正整数。`i_a`、`i_b`、`i_target` 均为 `p_width` 位无符号输入，`i_carry_in` 为一位输入进位，`o_equal` 为当前周期的比较结果。普通二项加法将 `i_carry_in` 接零；比较分段加法的高位结果时，可以接入低位产生的进位。

目标和值的每一位决定该位所需的进位：

```text
carry_needed = i_a xor i_b xor i_target
carry_generated = (i_a and i_b) or ((i_a or i_b) and not i_target)
```

模块检查最低位所需进位等于 `i_carry_in`，并检查其余每一位所需进位等于相邻低位产生的进位。最低位条件依赖四个输入信号，其余每位条件依赖本位与相邻低位的六个输入信号，全部条件并行计算为 `bit_equal`，最后通过归约与运算生成输出。最高位的输出进位不参与等式，保留完整的模运算语义。模块使用显式位运算，不含函数、时钟或状态。

参数 `p_use_lut` 控制是否保留 `bit_equal` 的逐位运算边界。定义 `XILINX_FPGA` 时默认启用，定义 `ASIC_SYNTHESIS` 或使用普通配置时默认关闭。属性直接作用于逐位计算结果，帮助综合工具独立实现相邻两位的六输入条件。两种配置具有相同的组合逻辑及四态行为，源码不实例化器件原语。

## 全部输入形式比较

```sh
python3 test/add_equal/run_formal.py --out build/add_equal_formal
```

测试直接实例化实际 RTL，与原生无符号加法的低 `p_width` 位比较结果进行 SAT 等价证明。所有输入均无约束，包含输入进位为零或一、连续进位、模运算溢出和目标值不匹配的情况。每种位宽分别使用普通配置和 `XILINX_FPGA` 配置，每次同时检查默认参数、`p_use_lut=0` 和 `p_use_lut=1`。

| 位宽 | 无约束输入位数 | 结果 |
| --- | ---: | --- |
| 1 | 4 | 通过 |
| 2 | 7 | 通过 |
| 4 | 13 | 通过 |
| 8 | 25 | 通过 |
| 16 | 49 | 通过 |
| 28 | 85 | 通过 |
| 32 | 97 | 通过 |
| 33 | 100 | 通过 |
| 64 | 193 | 通过 |

## 四态比较

```sh
python3 test/add_equal/run_four_state.py --out build/add_equal_four_state
```

测试使用 Icarus Verilog，以 case equality 检查当前实现与进位向量逻辑相等表达式的输出。一位和两位模块分别穷举全部 256 和 16,384 组 `0/1/X/Z` 输入；其余七种位宽各检查 6,000 组输入，共计 58,640 组。宽输入测试覆盖数值相等、已知不匹配位、少量未知位和高阻态位同时出现的情况，每组输入同时检查三种参数设置。

各工具在指定输出目录保存源码快照、逐项日志和 `summary.json`。当前验证摘要保存在 [validation.json](validation.json)。
