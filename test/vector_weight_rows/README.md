# 向量权重的整行同步存储

本地存储配置的 `vector_weight_store` 按卷积核位置保存全部通道权重。默认配置为 49 行、
每行 16 个八位通道，共 6,272 位。存储通过公共 `regfile` 提供字节写掩码、
同步读取与块 RAM 资源选择，每个 DMA 字节仍按原有通道条件写入。

`SHARED_STORAGE_ENABLE=1` 时，向量单元通过 `vector_shared_store` 访问已有的
IA/PS 共享 RAM。共享存储测试及两类配置的运行方法见
[`test/vector_engine`](../vector_engine/README.md)。

状态机在 `OUTPUT_INIT` 读取位置零，在最后一组计算的 `EXECUTE_COMMIT`
准备下一个卷积核位置；其余周期使用当前 `tap`。计算发射周期始终取得
当前卷积核位置的权重。写入和读取的越界地址检查保留完整 32 位范围，
同地址读写返回写入前的数据。八路 PE、全部权重位和公开接口周期保持相同。

## 存储与控制检查

`run_storage.py` 直接读取实际 `vector_weight_bank` 和 `vector_weight_store`。
两份存储的初始内容相同且内容任意，写使能、字节掩码、写数据和完整读写
地址均无输入限制。比较每一位存储状态，以及原异步读取经过一个时钟后的
结果与当前同步结果。1×1、3×7 和 16×49 三组配置均通过，分别比较 8、168
和 6,272 个存储位，覆盖地址越界、部分写入和同地址读写。

`run_control.py` 从实际向量状态机验证读取的周期关系，保留状态、操作码、
加载类型、计算组、卷积核位置及同步地址寄存器，其余数据寄存器和独立
数据比较允许任意取值。归纳检查确认，每次深度卷积发射时，前一周期
读取的位置等于当前 `tap`，且前一周期没有权重写入。

## 完整向量数值检查

测试使用生产 DMA、八路 PE、实际 Xilinx 原语功能模型和独立整数参考，
覆盖深度卷积、池化、S8/S16 向量、归约、Add、Softmax、总线等待和错误恢复。
`vector_weight_issue_observer` 独立保存每个通道的权重，并在计算发射时逐字节
检查实际权重和同步读取地址。

| 配置 | 任务数 | 输出数 | 各任务周期总和 | 权重发射检查 | 权重字节检查 |
| --- | ---: | ---: | ---: | ---: | ---: |
| BUS32、TILE16、PE8 | 592 | 169,487 | 3,017,541 | 29,673 | 474,768 |
| BUS64、TILE16、PE8 | 592 | 168,601 | 2,979,488 | 28,838 | 461,408 |

BUS64 的全部任务周期、DMA 统计和重叠统计逐项等于已有完整向量结果。

## 资源与容量

本地存储配置下，完整独立向量模块的测量结果为 11,183 个逻辑 LUT、56 个分布式 RAM
LUT、6,030 个触发器、17 个 DSP48E1 和 2 个 RAMB36E1。权重存储占用这两个
块 RAM，原有 192 个权重 RAM LUT 转入块 RAM。实际存储层次为
`u_vector.g_private_weights.u_weights.u_storage.mem`，容量统计应计算 49×128 位。
`measurement.json` 保存所测源码摘要、全部验证摘要和综合资源信息。

## 运行方法

```sh
python3 test/vector_weight_rows/run_storage.py --out build/weight_storage
python3 test/vector_weight_rows/run_control.py --out build/weight_control32 --bus-width 32
python3 test/vector_weight_rows/run_control.py --out build/weight_control64 --bus-width 64
python3 test/vector_engine/run.py --out build/weight_numeric32 --bus-width 32 --pes 8 --jobs 1 --xilinx
python3 test/vector_engine/run.py --out build/weight_numeric64 --bus-width 64 --pes 8 --jobs 1 --xilinx
```
