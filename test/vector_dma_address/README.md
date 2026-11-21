# 向量 DMA 地址与参数准备

普通读取、池化读取和 Softmax 表读取分别计算地址候选，状态信号在末端选择完整结果。普通读取将权重、偏置、乘数、移位参数和线性向量的起点与偏移送入两操作数加法器，按三位分组计算前缀进位。池化读取先将三个地址分量压缩为两项，再计算完整加法。地址输出按 32 位运算处理回绕，专用三操作数模块同时保留两个溢出位。

读取类型、传输尺寸和请求周期保持一致。普通读取在数据含未知值时使用三操作数表达式保存原有四态传播行为；综合后的二值电路使用直接两操作数加法。

写回地址将输出起点、空间或向量偏移、通道偏移直接送入三操作数压缩加法，空间位置与通道号同时参与计算。未知值分支保留原偏移表达式和八位分组加法的四态结果。两种分支的二值结果按完整 32 位地址比较，保持模加法回绕。

参数行步长和连续行资格在 `CHECK` 状态保存，供后续参数 DMA 使用。Softmax 表查询索引在 `SOFT_RUN` 接收查询请求时保存，供 `SOFT_LUT_REQ/SOFT_LUT_WAIT` 使用。四组 DMA 访问范围分别选择起点和字节数，并生成 33 位末地址；关闭的范围输出零值。

## 数学关系与形式证明

参数行步长为 `shift_base - multiplier_base`，按 32 位无符号运算处理。三行连续读取使用的等距条件可以写为：

```text
(multiplier_base - bias_base) mod 2^32
    = (shift_base - multiplier_base) mod 2^32

(bias_base + shift_base) mod 2^32
    = (2 * multiplier_base) mod 2^32
```

两种表达式在模 `2^32` 的加法中等价。`bias_base != 0`、`multiplier_base > bias_base` 和 `shift_base > multiplier_base` 的资格条件保留在实际表达式中。脚本直接提取参考提交和当前源码的组合部分，对全部二值配置进行比较。

`run_formal.py` 将验证分成以下部分：

| 部分 | 比较范围 | 已证明位数或配置 |
| --- | --- | --- |
| 参数描述符准备 | 32 位步长、两行资格、三行资格 | 34 位 |
| DMA 读取配置和地址 | 读取类型、传输尺寸、地址、步长、行列数、突发长度、参数数据合法性、写回起点 | 每组 267 位 |
| DMA 访问范围 | 四组起点、末地址和配置输出 | 555 位 |

读取译码包含 `(BUS_WIDTH,TILE)=(32,16)、(64,16)、(128,16)、(32,3)、(64,32)` 五组参数。证明不限制状态编码、数据或地址取值。

准备值和消费逻辑的组合证明分别进行。读取译码证明对双方提供相同的任意参数描述符和 Softmax 查询索引；真实引擎中这些值的保存时刻、保持关系及实际使用由 `vector_control_datapath_observer` 检查。该观察模块直接比较真实寄存器和原始配置表达式，不添加输入假设。完整说明和数值回归入口见 [向量位置、串行读取与准备寄存器检查](../vector_control_datapath/README.md)。

## 突发长度编码

总线每拍包含 `2^BUS_SHIFT` 个字节。低八位突发长度由字节数减一后的相应位直接生成；每位的借位条件为全部更低位等于零。该表达式保留零长度及 32 位回绕的行为，消除向上取整加法和长度减一的串接。

`run_burst_formal.py` 提取生产函数和参考版本的实际表达式，对 12 种总线位移量证明全部 32 位输入。另以 Icarus Verilog 检查 50,736 组结果，覆盖边界数值、随机输入以及逐位未知值和高阻值。未知控制输入仍使用原算术表达式。

```bash
python test/vector_dma_address/run_burst_formal.py \
  --out build/vector_dma_address/burst
```

## 复现

```bash
python test/vector_dma_address/run_formal.py \
  --reference-rev dde5e7c9 --out build/vector_dma_address/formal

python test/vector_dma_address/check_address_four_state.py \
  --out build/vector_dma_address/address_four_state
```

入口同时运行四组范围证明，并将源码副本、辅助模块、参数配置、证明脚本和日志保存到输出目录。`summary.json` 记录各部分结果和 SHA256；`cases.json` 提供读取译码片段的独立综合配置。本文所列位数由本次形式证明输出统计。

读写地址四态检查从实际引擎提取候选选择与加法逻辑，以分量选择参考模型逐位比较 32 位读取地址和写回起始地址。检查遍历 64 种状态编码和 8 种读取类型，并覆盖随机地址、空间偏移、数据中的未知值和高阻值、状态及类型编码中的未知值，共比较 34,816 组结果。`--source-root` 可指定完整 SoC 测量使用的固定源码目录。
