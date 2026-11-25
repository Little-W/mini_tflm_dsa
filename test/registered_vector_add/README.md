# INT32 向量加法

每个通道同时计算低 16 位加法和高 16 位加法，寄存两个部分和及低半字进位。输出端将该进位加入高半字，保留 32 位模加法结果。数据、有效信号和行结束标志均前进一拍；输入未被接收时保持数据，清空信号立即抑制输出有效信号。

低半字与高半字分别使用普通加法表达式，组合结果的 `use_dsp="simd"` 属性允许综合工具自动推断两个并行运算。原有寄存器、使能和输出进位修正保持在相同时钟位置。

数据寄存器不复位。四态仿真按字节保留已确定结果，并将未知值及其进位传播到相关字节。

## 验证

```sh
python test/registered_vector_add/run.py --out build/vector_add_numeric
python test/registered_vector_add/compare_revision.py --out build/vector_add_equivalence
python test/registered_vector_add/check_inferred_mapping.py --out build/vector_add_mapping
```

`compare_revision.py` 从指定 Git 提交读取完整参考模块，分别证明 1、3、8、16 个通道在任意二态输入下的无限时序等价。比较覆盖有效信号、行结束标志，以及首次接收输入后的全部数据周期。另用 Icarus Verilog 比较四态输入、暂停、清空和复位过程中的完整输出。

`run.py` 用直接 INT32 加法检查边界值和随机值，同时检查无效周期的数据保持。脚本将编译副本写入输出目录，以兼容不同 Icarus Verilog 版本支持的整数参数声明形式，项目 RTL 保持不变。

`check_inferred_mapping.py` 执行原生 Xilinx 7 系列映射，完整展开所生成的器件功能模型，并证明全部 514 位测量输出的无限时序等价。结果包括每个通道的 32 位数据和两个控制输出。

## 映射结果

Xilinx 7 系列映射采用 16 个通道。测量模块在输入和输出各增加一组寄存器，表内资源包含这些测量寄存器。

| 项目 | 参考提交 `22471449` | 当前设计 |
| --- | ---: | ---: |
| 逻辑 LUT | 634 | 20 |
| `CARRY4` | 272 | 64 |
| 触发器 | 2,103 | 1,815 |
| DSP | 0 | 16 |
| 最长寄存器间组合路径 | 5 | 5 |

以上统计来自同一工具配置。目标器件的频率由布局布线后的时序分析确定。
