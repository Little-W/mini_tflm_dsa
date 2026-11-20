# 向量运算的范围与共享写数据

## RTL 结构

深度卷积的量化偏移与激活上下限由配置检查器限制在 S8 范围内。
偏移限幅保留完整六十四位舍入结果：低八位完成偏移加法，高五十六位
并行判断进位、借位、零值、全一值和符号。最终限幅结果与六十四位
加法后比较上下限的结果相同，包括六十四位补码回绕。

Add 的偏移加法产生十位有符号结果。激活上下限的高位范围与低十位
比较并行进行，保留任意三十二位上下限的含义和完整三十二位限幅结果。

累加器按 PE 通道共用计算结果和 Softmax 指数的写入数据。两类数据先
按实际写入状态选择，各存储项再与偏置及初始化常量组合。每项保持
独立写使能，全部三十二位累加值和十六位右操作数仍在原时钟边沿更新。

## 控制关系证明

`run_control.py` 使用实际向量状态机、配置检查器和 Softmax 模块。
从复位状态出发，保留配置字段、主状态、加载类型、量化活动状态、
验证器状态及错误寄存器；其余数据寄存器和独立数据比较允许任意取值。
输入配置、读写等待、错误和响应均无附加限制。

BUS32 和 BUS64 均通过归纳证明，确认：

- DW 和 Add 的运行阶段保持 S8 偏移及有序的 S8 激活范围。
- 每次实际量化结果写入都满足上述范围。
- 配置检查期间未启用量化写入。
- Softmax 指数写入仅发生在 `SOFT_LUT_WAIT`，与计算提交、输出初始化及
  向量初始化分属不同状态。

## 数据和存储状态比较

`run_datapath.py` 从修改前后实际源码提取三处表达式，并检查其余 RTL 相同。

| 比较对象 | 输入和状态范围 | 结果 |
| --- | --- | --- |
| DW 偏移限幅 | 任意六十四位数据及任意 S8 偏移、上下限；比较全部三十四位结果及范围标志 | 通过 |
| Add 限幅 | 输入和三十二位配置字段均无附加限制；比较全部三十二位输出 | 通过 |
| 累加器与右操作数 | 两份任意且相同的初始内容，在已证明的控制关系下比较每次状态更新 | 通过 |

存储比较涵盖 `(TILE, PE_COUNT, BUS_WIDTH)` 为 `(16,8,64)`、`(16,8,32)`、
`(8,4,32)`、`(3,3,64)` 和 `(1,1,32)` 的五组表达式参数，分别比较
768、768、384、144 和 48 位状态。所有存储位、有效通道掩码、使能、
数据及地址都参与比较。

## 完整向量资源

下表使用完整 `vector_engine`，参数为 `TILE=16`、`PE_COUNT=8`、
`BUS_WIDTH=64`，保留全部公开端口。源码摘要与测量结果保存在
`measurement.json`。

| 指标 | 修改前 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 11,183 | 10,355 |
| 分布式 RAM LUT | 56 | 56 |
| 触发器 | 6,030 | 6,030 |
| DSP48E1 | 17 | 17 |
| RAMB36E1 | 2 | 2 |
| 最长寄存器间组合单元数 | 17 | 15 |

完整向量减少 828 个逻辑 LUT。表中的组合级数来自综合网表，150 MHz
使用目标器件的实现时序报告检查。

## 完整数值验证

生产 DMA、八路 PE、实际 Xilinx 原语功能模型和独立整数参考完成 592 个
任务，核对 168,601 个输出。其中 Add 为 143 个任务、135,305 个输出，
Softmax 为 273 个任务、2,188 个输出。其余任务覆盖深度卷积、池化、
S8/S16 向量、归约、总线等待和错误恢复。

各任务周期合计 2,979,488；全部 592 个任务的周期、DMA 数量、缓存和
重叠统计逐项等于修改前结果。权重独立检查同时完成 28,838 次计算发射、
461,408 个权重字节比较。

## 运行方法

```sh
python3 test/vector_arithmetic_domains/run_control.py --out build/vector_domain32 --bus-width 32
python3 test/vector_arithmetic_domains/run_control.py --out build/vector_domain64 --bus-width 64
python3 test/vector_arithmetic_domains/run_datapath.py --out build/vector_domain_data
python3 test/vector_arithmetic_domains/prepare_measurement.py --out build/vector_domain_sources
python3 scripts/fpga/open_fpga_synth.py --case-config build/vector_domain_sources/cases.json \
  --cases vector_reference vector_current --out build/vector_domain_synthesis
python3 test/vector_engine/run.py --verilator verilator-modern --out build/vector_domain_numeric \
  --bus-width 64 --pes 8 --jobs 1 --xilinx
```
