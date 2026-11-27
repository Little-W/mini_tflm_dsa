# 二项加法等式的并行进位检查

`rtl/common/add_equal.sv` 检查以下组合关系：

```text
o_equal = ((i_a + i_b + i_carry_in) mod 2^p_width) == i_target
```

参数 `p_width` 指定正整数位宽，默认值为 32。`p_preserve_bits` 选择相邻位比较结构，`p_keep_bits` 和 `p_keep_groups` 分别控制位结果与六位比较组的组合边界。`p_late_carry` 先归并高位匹配，使输入进位只参与末级选择。三个数据输入均为 `p_width` 位无符号数，`i_carry_in` 为一位输入进位，输出在当前周期产生。

目标和值的各位分别确定该位所需的进位。模块比较最低位所需进位与 `i_carry_in`，并比较其余各位所需进位与相邻低位产生的进位，最后归约所有逐位比较结果。最高位输出进位不参与等式，保留模加溢出行为。全部逻辑使用普通位运算与归约运算。

## 验证结果

`run_formal.py` 以原生定宽加法作为参考，对 1、2、4、8、16、28、32、33、64 位分别运行通用和 FPGA 编译配置，共 18 组 SAT。外部输入均无约束，覆盖任意输入进位、连续进位、溢出和目标不匹配。

`run_four_state.py` 使用进位向量的逻辑相等表达式作为参考。1 位与 2 位实例分别穷举全部 256 和 16,384 组四态输入，其余七种位宽各检查 6,000 组，共 58,640 组。比较包含部分已知不匹配位与 X/Z 同时出现的情况。

```bash
python3 test/add_equal/run_formal.py --out build/add_equal_formal
python3 test/add_equal/run_four_state.py --out build/add_equal_four_state
python3 test/add_equal/run_inferred.py --out build/add_equal_configurations
```

跨编译配置的扩展检查见 [配置检查](INFERRED_ARITHMETIC.md)。实际源码与日志摘要分别保存在 [validation.json](validation.json) 和 [inferred_validation.json](inferred_validation.json)。
