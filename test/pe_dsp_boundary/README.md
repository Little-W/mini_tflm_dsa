# 计算单元 DSP 输入寄存边界

`ws_systolic_cell` 在 FPGA 综合时保留模块边界，并保留 `weight_prefetch` 的寄存输出节点。数据寄存、活动权重、预取权重、部分和、乘加表达式及所有使能条件均保持原来的逐周期行为。16×16 阵列仍包含 256 个计算单元，支持十六位数据、十六位权重和三十二位累加结果。

`KEEP_HIERARCHY` 限制跨计算单元的综合重组；`KEEP` 保留预取权重的输出信号。两个属性由 `XILINX_FPGA` 启用。属性语义见 AMD [UG901 的 KEEP_HIERARCHY 说明](https://docs.amd.com/r/2024.2-English/ug901-vivado-synthesis/KEEP_HIERARCHY)和 [KEEP 说明](https://docs.amd.com/r/2024.2-English/ug901-vivado-synthesis/KEEP)。

## 行为验证

```sh
python3 test/pe_dsp_boundary/run_formal.py \
  --out build/pe_dsp_boundary/formal

python3 test/weight_prefetch/run_array.py \
  --out build/pe_dsp_boundary/array --verilator verilator-modern --jobs 1

python3 -m unittest discover -s test/pe_dsp_boundary -p 'test_*.py' -v
```

形式比较直接读取参考提交与当前 RTL，覆盖两种 `p_exchange_weights` 模式，以及五组数据、权重和累加位宽。全部状态和公开输出按周期比较，输入序列没有额外约束。四态比较覆盖未知数据、未知装载及提交条件，并同时检查活动权重、预取权重、数据和部分和寄存器。

阵列数值测试使用真实权重加载缓冲、交换模式和完整装载模式，覆盖大小 3、4、16，以及八位和十六位权重。测试包含尾部补零、连续分块、装载间隔、提交与装载同时发生、部分装载后的清空以及运行中复位。检查程序单元测试使用人工构造的连接图，检查属性读取、按位连接合并、寄存截断、跨 PE 级联、完整 PE 覆盖和错误返回。

## Vivado 专项综合

```sh
vivado -mode batch -source test/pe_dsp_boundary/vivado.tcl \
  -tclargs build/pe_dsp_boundary/vivado
```

脚本综合完整生产阵列，在输出端添加与计算输出阶段对应的寄存器，使用 `xc7a200tfbg484-3` 和 6.667 ns 时钟约束。输出文件包含源码 SHA256、利用率、层次利用率、时序报告、综合检查点及 DSP 连接检查。

对于已经打开的板级或 SoC 综合网表，可直接调用辅助过程：

```tcl
source test/pe_dsp_boundary/check_vivado.tcl
pe_dsp_boundary::check build/dsp_connections \
    {*u_compute_core/u_systolic_array/*} 16 0 9
```

参数依次指定输出目录、阵列 DSP 的名称匹配模式、阵列边长、允许的跨 PE 未寄存 B 传播级数和允许的连续组合 B 通路 DSP 数量。独立阵列使用名称模式 `{u_array/*}`。

检查过程输出下列文件：

| 文件 | 内容 |
| --- | --- |
| `all_dsp_cells.tsv` | 设计内全部 DSP48E1 的 `B_INPUT`、`BREG`、`BCASCREG`、`AREG`、`ACASCREG`、`MREG` 和 `PREG` |
| `dsp_cells.tsv` | 阵列内各 PE 的 DSP 参数 |
| `dsp_connections.tsv` | 真实网表中 `BCOUT` 到所选 `B` 或 `BCIN` 端口的逐位连接 |
| `dsp_b_cascade.json` | 完整 PE 覆盖、寄存边界、组合级数、最长连接序列、输入摘要和通过状态 |

`BCASCREG` 决定 B 级联输出是否经过寄存器。检查程序依照该参数结束组合路径，在相邻 DSP 间统计实际跨 PE 的未寄存传播。参数组合依据 AMD [DSP48E1 属性说明](https://docs.amd.com/r/2024.1-English/ug953-vivado-7series-libraries/DSP48E1)检查。默认要求所有 PE 均有 DSP 实现、跨 PE 未寄存 B 传播为零、连续组合 B 通路 DSP 数量不超过九；任何一项不满足均返回失败。

DSP 输入连接检查用于确认阵列综合结构。150 MHz 还需要完整设计的布局布线时序报告；全部寄存器间组合路径的九级限制由完整设计报告检查。

本目录的 [measurement.json](measurement.json) 保存本地行为验证结果。实际 Vivado 资源和时序由上述脚本运行后生成。
