# 向量结果存储的共享字节写入

## RTL 结构

量化、Softmax 和串行计算各自生成一个字节结果，共用数据选择后送到全部
结果存储项。每项保留独立地址比较与写使能；并行乘积和池化结果在对应
存储项选择。低八位沿原时钟边沿写入，高二十四位保持原有完整整数写入。
`result_buf` 的十六个三十二位存储项全部保留。

## 控制关系与状态比较

`run_control.py` 使用实际状态机及其配置检查逻辑，从复位开始证明五类
写入来源互斥。保留主状态、运算模式、加载类型及量化活动状态，其余
数据寄存器允许任意取值；顶层输入没有附加限制。BUS32 和 BUS64 都
通过归纳证明。

`run_formal.py` 读取修改前后实际源码，检查其余逻辑保持相同。
两份完整结果存储从任意且相同的内容开始，在已证明的写入互斥关系下，
比较每次状态更新的全部位。数据、地址、有效数量及写入使能均参与比较。

| TILE | PE_COUNT | 比较的状态位数 | 结果 |
| ---: | ---: | ---: | --- |
| 16 | 8 | 512 | 通过 |
| 16 | 4 | 512 | 通过 |
| 8 | 4 | 256 | 通过 |
| 3 | 3 | 96 | 通过 |
| 1 | 1 | 32 | 通过 |

## 完整向量综合

以下测量采用 `TILE=16`、`PE_COUNT=8`、`BUS_WIDTH=64` 的完整向量引擎，
保留全部公开端口，并使用相同综合配置。

| 指标 | 修改前 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 10,355 | 10,181 |
| 分布式 RAM LUT | 56 | 56 |
| 触发器 | 6,030 | 6,030 |
| DSP48E1 | 17 | 17 |
| RAMB36E1 | 2 | 2 |
| 最长寄存器间组合单元数 | 15 | 15 |

完整向量减少 174 个逻辑 LUT。源码摘要、证明结果及资源统计保存在
`measurement.json`。组合级数来自综合网表；150 MHz 使用目标器件的
实现时序报告检查。

## 完整数值验证

生产 DMA、八路 PE、官方 Xilinx 原语功能模型与独立整数参考完成 592 个
任务，核对 168,601 个输出。任务覆盖深度卷积、池化、Add、Softmax、
S8/S16 向量、归约、总线等待及错误恢复。

各任务周期合计 2,979,488，全部 592 个任务的周期、DMA 数量、缓存及
重叠统计逐项等于修改前结果。权重独立检查完成 28,838 次计算发射和
461,408 个字节比较。

## 运行方法

```sh
python3 test/vector_result_sources/run_control.py --out build/vector_result32 --bus-width 32
python3 test/vector_result_sources/run_control.py --out build/vector_result64 --bus-width 64
python3 test/vector_result_sources/run_formal.py --out build/vector_result_data
python3 test/vector_arithmetic_domains/prepare_measurement.py --out build/vector_result_sources --reference b2995131
python3 scripts/fpga/open_fpga_synth.py --case-config build/vector_result_sources/cases.json \
  --cases vector_reference vector_current --out build/vector_result_synthesis
python3 test/vector_engine/run.py --verilator verilator-modern --out build/vector_result_numeric \
  --bus-width 64 --pes 8 --jobs 1 --xilinx
```
