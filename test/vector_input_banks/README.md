# 输入存储的银行共享写数据

`vector_engine` 按总线字节数组织输入写数据选择器。64 位总线使用八个银行，
每个银行共用十六位写数据；32 位总线使用四个银行。每个存储项仍独立比较
DMA 列地址、窗口列地址和池化行地址，并在原有时钟边沿更新。

已保存的 `global_pool` 和 `spatial` 选择当前的数据来源：全局池化使用
`pool_bank_data`，其余空间运算使用 `window_bank_data`，普通向量使用 DMA
数据。S16 普通向量继续从相应半字通道读取。输入存储保持十六位宽度、
两个完整通道组或四个半通道组的容量，八路 PE 和公开接口周期保持原样。

## 控制和数据证明

`run_control.py` 使用完整实际向量源码及实际 `conv_window_queue`。窗口请求
与返回由该队列连接，读写等待、配置、错误和前端返回可任意变化。从复位
状态出发，保留向量状态、操作码、加载类型、池化模式、池化有效位和队列
数量；其余数据寄存器及独立数据比较允许取任意值。所有替换都按完整单元
名称操作，并检查每个位只有一个输出驱动。

BUS32 和 BUS64 均通过十步归纳。证明的关系包括：

- 普通输入加载只在非空间运算中执行。
- 窗口队列占用期间，运算模式保持为空间运算且未启用全局池化。
- 池化寄存数据有效期间，运算模式保持为全局池化。
- 三类输入写入来源互斥，复位时写入禁止。

`run_formal.py` 直接提取修改前后实际输入写入代码。在上述已证明的归属
条件下，比较每个存储项的写使能和全部十六位数据。所有地址和数据位均可
任意取值，存储项的保持、写入边沿及未使用项的常量值保持相同。脚本同时
检查输入写入块以外的 RTL 文本相同。

| BUS_WIDTH | TILE | DMA_SIZE | 比较的有效存储位 | 结果 |
| ---: | ---: | ---: | ---: | --- |
| 32 | 16 | 64 | 512 | 通过 |
| 64 | 16 | 64 | 512 | 通过 |
| 128 | 16 | 64 | 512 | 通过 |
| 64 | 32 | 128 | 1,024 | 通过 |
| 64 | 3 | 16 | 96 | 通过 |
| 32 | 1 | 4 | 32 | 通过 |

## 完整向量数值验证

测试使用生产 DMA、八路 PE、实际 Xilinx 原语功能模型和独立整数参考。
覆盖深度卷积、池化、S8/S16 向量、归约、Add、Softmax、总线等待、地址
边界和错误恢复。观察器每拍检查来源归属，按原逐项选择方式计算完整
十六位参考写数据，并在下一拍比较实际存储值。

| 配置 | 任务数 | 输出数 | 各任务周期总和 | 普通 DMA 拍数 | 窗口响应拍数 | 池化有效拍数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BUS32、TILE16、PE8 | 592 | 169,487 | 3,017,541 | 35,094 | 70,315 | 5,562 |
| BUS64、TILE16、PE8 | 592 | 168,601 | 2,979,488 | 17,684 | 68,838 | 3,044 |

BUS64 的全部任务周期、DMA 统计和重叠统计逐项等于已有完整向量结果。
测试结束时调用模拟器的 `final()`，使观察器输出累计检查数量。

## 完整向量资源和路径

下表使用 `TILE=16、BUS_WIDTH=64、DMA_SIZE=64、PE_COUNT=8`，保留全部公开输出。
组合测量同时采用 `a7447f43` 的归约 DSP 实现。

| 指标 | 参考 `3587da43` | 输入银行共享 | 输入银行共享及归约 DSP |
| --- | ---: | ---: | ---: |
| 逻辑 LUT | 11,331 | 11,022 | 11,129 |
| 分布式 RAM LUT | 248 | 248 | 248 |
| 触发器 | 5,994 | 5,994 | 5,994 |
| DSP48E1 | 15 | 15 | 16 |
| 最长实际寄存器间组合单元数 | 15 | 16 | 14 |

银行共享单独减少 309 个逻辑 LUT；与归约 DSP 组合后，相对于已有归约版本
的 11,399 个逻辑 LUT，减少 270 个。单独银行版本的最长路径位于舍入器的
剩余移位量至 `q_rounded`，组合版本最长为十四级。表中 LUT 数量来自逻辑
映射；完整 SoC 的物理 LUT 数量及 150 MHz 时序使用布局布线结果检查。

## 复跑命令

```sh
python3 test/vector_input_banks/run_control.py --out build/input_owner32 --bus-width 32
python3 test/vector_input_banks/run_control.py --out build/input_owner64 --bus-width 64
python3 test/vector_input_banks/run_formal.py --out build/input_write_formal --reference 3587da43
python3 test/vector_engine/run.py --out build/input_numeric32 --bus-width 32 --pes 8 --jobs 1 --xilinx
python3 test/vector_engine/run.py --out build/input_numeric64 --bus-width 64 --pes 8 --jobs 1 --xilinx
python3 test/vector_input_banks/prepare_measurement.py --out build/input_measurement \
  --reference 3587da43 --reduction-revision a7447f43
python3 scripts/fpga/open_fpga_synth.py --case-config build/input_measurement/cases.json \
  --cases vector_reference vector_current vector_combined --out build/input_synthesis
```

`measurement.json` 保存源码摘要、形式证明、完整数值结果和三组实际网表的
资源及路径摘要。输入银行共享与归约修改分别位于独立组合块，组合测量
输入由已保存版本的实际源码生成。
