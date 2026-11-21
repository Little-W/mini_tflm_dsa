# 分组加法器的平衡前缀检查

`parallel_prefix_add` 保留完整的 `p_width` 位求和结果和最终进位。各组独立计算产生条件、传播条件及局部和值；启用 `p_preserve_groups` 时，组间前缀按二的幂跨度逐层合并。产生条件保留各层节点；传播条件仅在参与下一层产生条件时保留。完整低位传播由输入进位的实际用途决定，组进位别名按使用情况优化。此结构适用于需要限制组合深度的地址和计数运算。

本目录直接编译实际 RTL，比较全部求和位及最终进位。参考实现保存在 `reference_prefix.sv`，使用逐边界展开的产生与传播表达式。

## 检查范围

- 68 组二值组合证明覆盖完整输入范围，包括输入进位、最高位进位、非整组位宽，以及两种 `p_preserve_groups` 设置。
- 参数包含 1、4、7、8、9、16、17、18、32、33、34、35、48、64 位与 4、8 位分组，并补充 1、2、4 位输入和 1、2 位分组。
- 四态仿真使用严格的逐位相等检查。1、2、4 位输入遍历全部 0、1、X、Z 组合；较大位宽逐位注入 X/Z，覆盖进位产生、传播、阻断和跨组传递。
- 本次共完成 2,226,176 次四态比较，全部结果位与最终进位均一致。

## 运行

从仓库根目录执行，需要 `pyosys` 和 Icarus Verilog：

```bash
python3 test/common_prefix_tree/run.py --out /tmp/npu_prefix_tree --jobs 2
```

入口保存输入源码副本、SHA-256、证明脚本、日志和 `summary.json`。组合深度与资源使用由使用该模块的实际电路和完整 SoC 综合报告给出。

## 保留属性与实际映射

`attribute_reference.sv` 保存完整前缀节点保留方案，SHA256 为 `52440e11170bb1397859bf6a777069a426d493877406631deee4c15113a498f8`。当前模块 SHA256 为 `746fd83d9dc5c704f6536b9521ab65ea825fa62065e1217e7758fddf92867280`。两者的算术表达式和前缀层连接一致，差异仅涉及保留属性及指向已有信号的组合别名。

下面的入口直接比较这两种保留方案。已完成 68 组无输入假设的二值证明和 2,226,176 次严格四态比较，全部通过。

```bash
python test/common_prefix_tree/run.py \
  --reference test/common_prefix_tree/attribute_reference.sv \
  --candidate rtl/common/parallel_prefix_add.sv \
  --out build/common_prefix_attributes --jobs 2
```

相同配置的完整 `vector_engine` 局部综合使用 `TILE=16`、`BUS_WIDTH=64`、`PE_COUNT=8`、`WINDOW_LANES=8`，启用共享存储与共享量化。两侧除本模块外的全部源码 SHA256 相同，向量引擎 SHA256 为 `b2ab12deb8b442429b0a1bb794f2b5d1b90efe23e48fc9d7802b0a37f53f92bb`。综合使用 `synth_xilinx -family xc7 -noiopad -noclkbuf -flatten`。

| 项目 | 完整节点保留 | 按传播用途保留 |
|---|---:|---:|
| 逻辑 LUT | 14105 | 13935 |
| 触发器 | 8417 | 8417 |
| CARRY4 | 746 | 744 |
| BRAM36 / BRAM18 / DSP | 0 / 1 / 14 | 0 / 1 / 14 |
| 最长寄存器间组合路径 | 14 | 13 |

这项调整不增加状态或时钟周期。完整摘要、各项输入源码 SHA256 和结果文件位置保存在 [attribute_verification.json](attribute_verification.json)。整机物理 LUT 数量与 150 MHz 时序由完整实现报告确认。
