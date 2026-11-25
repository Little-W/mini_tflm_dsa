# PicoRV32 完整算术验证

项目 CPU 的主文件是 `rtl/soc/picorv32_npu.v`，乘除法模块位于同一目录。当前关系比较、跳转加法、顺序地址和除法结果符号变换的设计与量化结果见 [CPU 组合路径验证](../pico_operand_paths/README.md)。

本目录保留与固定上游实现比较的完整状态和程序执行检查。参考为 PicoRV32 提交 `ef203c2b0a3fb793280f5114941416c425c5b461`。程序先核对上游文件 SHA-256，再解析每份实现所使用的 RTL 模块，固定全部依赖文件并分别展开。

```sh
python3 test/pico_pc_arithmetic/run.py \
  --reference-source picorv32/picorv32.v \
  --candidate-source rtl/soc/picorv32_npu.v \
  --stages formal execution \
  --out build/pico_upstream_comparison
```

四组参数覆盖生产配置、压缩指令与中断及 64 位计数器、两周期 ALU 与比较，以及 16 个单端口寄存器并关闭乘除法和计数器。形式检查包含全部已匹配状态和公开输出，输入不附加限制。

执行程序覆盖条件分支、循环、子程序调用和返回、访存及 32 位地址回绕。两个复位地址为 `0x00000000` 和 `0xfffff000`。两个 CPU 使用各自的乘除法实现及独立内存模型，逐周期比较有效输出，检查等待期间的请求稳定性，并核对独立数值结果。

```sh
python3 test/pico_pc_arithmetic/run_four_state.py --out build/pico_arithmetic_four_state
```

四态检查提取当前 CPU 中的加减法、返回地址和计数器表达式，以及实际关系比较模块。20,000 组二值输入与 20,000 组四态输入完成 240,000 项比较，控制和数据包含 `0`、`1`、`X`、`Z`。

当前源码的综合统计和功能结果保存在 [组合路径验证记录](../pico_operand_paths/validation.json)。完整 CPU 的当前同流程比较使用 `test/pico_operand_paths/run.py`。
