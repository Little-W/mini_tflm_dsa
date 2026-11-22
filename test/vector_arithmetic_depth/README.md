# 向量算术接口与组合路径检查

本目录验证三个独立模块的完整公开接口：`vector_reduce_alu.sv`、
`vector_round_shift.sv` 和 `registered_multiplier_s32.sv`。
测试保存当前源码、参考源码、模型、日志及 SHA-256，可选择生成局部综合结果。

## 算术结构

`vector_reduce_alu` 计算完整 INT32 模加法以及有符号极值。
大小比较先检查符号位，再根据高字节是否相等选择较低字节的比较结果。
`i_max` 和 `i_min` 同时有效时，极小值操作优先。

`vector_round_shift` 保存保护位和所有低于保护位的数据位是否非零，
按最近偶数规则形成结果，同时输出算术右移的向下取整结果。
`REGISTER_INPUT` 和 `REGISTER_MIDDLE` 控制输入与移位结果的寄存位置。
各字节分别生成递增结果和进位条件，使用普通定宽 RTL。

`registered_multiplier_s32` 使用四个完整部分积计算有符号 INT64 结果。
部分积寄存器之后先压缩三个加数，再执行完整 48 位加法。
`p_input_register`、`p_b_input_register` 独立选择两个输入寄存器，
所有寄存级受 `i_en` 控制。两个计算边沿的延迟和每个使能边沿接收一项运算的能力保持一致。

INT8、INT16 量化通过同一 `requant_compute_lane` 完成，算术流水为 7 个使能边沿。
量化的完整数值测试见 [`test/requant_compute_lane`](../requant_compute_lane/README.md)，
生产通道与参数读取测试见 [`test/requant_time_share`](../requant_time_share/README.md)。

## 验证范围

`run.py` 比较归约模块、两种舍入中间寄存配置和四种乘法输入寄存配置。
ASIC 与 FPGA 编译宏分别覆盖相同的公开接口，所有操作数和控制输入均不增加取值限制。
`check_four_state.py` 检查两个舍入中间寄存配置的 `result` 和 `floor_value`，
覆盖全部 64 种移位量、边界数值以及 X、Z 数据。
乘法器独立检查覆盖四种输入寄存组合、使能暂停、未知使能和完整 64 位乘积。

```bash
python3 test/vector_arithmetic_depth/run.py \
  --baseline-ref ef0dc75 --out build/vector_arithmetic/formal
python3 test/vector_arithmetic_depth/check_four_state.py \
  --reference-ref ef0dc75 --out build/vector_arithmetic/four_state
python3 test/vector_scalar/run.py --simulate \
  --out build/vector_arithmetic/scalar
python3 test/requant_compute_lane/run.py \
  --verilator verilator --jobs 1 --variants generic fpga \
  --out build/vector_arithmetic/requant_lane
python3 test/requant_time_share/run.py --help
```

在 `run.py` 命令中加入 `--synthesis` 可测量当前工具映射得到的资源数量和组合路径。
归约模块在输入和输出两端加入普通测试寄存器；舍入模块使用中间寄存器并保存公开输入和输出；
乘法器使用实际寄存结构。完整 SoC 的资源与跨模块时序由整机综合报告检查，
150 MHz 的结果由对应器件或标准单元库的实际时序报告确定。
