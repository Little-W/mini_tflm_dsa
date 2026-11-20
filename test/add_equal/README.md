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

模块检查最低位所需进位等于 `i_carry_in`，并检查其余每一位所需进位等于相邻低位产生的进位。各位条件同时计算，随后合并为比较结果。最高位产生的进位由 `unused_final_carry` 接收，保留完整的模运算语义。模块使用显式位运算和连接，不含函数、时钟或状态。

## 全部输入形式比较

```sh
python3 test/add_equal/run_formal.py --out build/add_equal_formal
```

测试直接实例化实际 RTL，与原生无符号加法的低 `p_width` 位比较结果进行 SAT 等价证明。所有输入均无约束，包含输入进位为零或一、连续进位、模运算溢出和目标值不匹配的情况。

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

源码与证明日志摘要保存在 [加法等式检查验证数据](../../docs/data/add_equal_validation.json)。
