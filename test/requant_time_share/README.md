# 统一并行与分时量化验证

`vec_requant` 负责配置保存、参数 DMA、WS/IS 参数存储、输入组缓存和输出行组装。所有计算实例均使用 `requant_compute_lane`。整张量模式广播一组准备参数，逐通道模式根据 WS 通道或 IS 输入行选择参数，INT8 与 INT16 使用相同的乘法和移位硬件。

## 接收与吞吐

当 `p_compute_lanes >= VLEN` 时，每个元素配备一个算术通道，连续输入可每周期接收一个向量。数据和同步读取的参数在乘法阶段会合，输出有效位、tile 完成标志及 DW 标签均经过七个流水边沿。

并行逐通道模式在消费参数组末行的边沿禁止启动下一参数组，当前末行继续使用当前参数。后续启动同时检查 `quant_params_valid` 与 `o_group_ready`。IS 模式跨列复用同一参数组时可以连续启动，整张量模式也保持连续接收。

当 `p_compute_lanes < VLEN` 时，`requant_group_buffer` 接收已经预留容量的完整输入组。每个周期最多向 `p_compute_lanes` 个算术通道发射一批数据。批次编号和行结束标志随七级算术传播，输出寄存器按批次保存元素，并在最后一批完成时产生整行输出有效信号。

组预留覆盖已接收、等待计算和等待输出的全部行。`o_group_ready` 在本组输出完成后恢复。参数尚未就绪时缓存保留输入，参数装载完成并经过同步读取边沿后开始计算。初始化和复位同时清空组状态及算术有效位。

生产参数 `VLEN=16`、`p_compute_lanes=2`、`MAX_IA_REUSE=32` 对应 512 行缓存，每行保存 `16×32+1=513` 位，共 262,656 位。WS/IS 参数的逻辑容量保持不变。

## 运行检查

```bash
python test/requant_time_share/run.py \
  --out build/requant_time_share --vlen 16 --lanes 2 --reuse 32 --bus 64
python test/requant_time_share/run.py \
  --out build/requant_parallel_groups --vlen 16 --lanes 16 --reuse 16 --bus 64
python test/requant_time_share/run_formal.py --out build/requant_group_capacity
python test/vector_shared_quant/run.py --out build/vector_shared_quant
```

数值测试分别检查并行和分时实例的结果及 DMA 请求序列。独立整数模型覆盖逐张量、逐通道、WS、IS、INT8、INT16、尾行、尾列、完整容量组、输入间隔、DMA 等待、初始化与复位。C++ 测试启用未定义行为检查。

`--lanes 16 --reuse 16` 还检查 320 个连续组配置，覆盖 1、15、17、31、33、256、257、528 行与 1、15、17、32、33 列。发送端在当前组最后一行到达时请求下一组，逐周期核对启动许可、参数切换和完整数值输出。

| 配置 | 周期 | INT8/INT16 元素 | 分组 | DMA 命令 |
|---|---:|---:|---:|---:|
| 16 元素，2 个算术通道，512 行，BUS64 | 75,534 | 542,528 | 170 | 608 |
| 4 元素，2 个算术通道，16 行，BUS64 | 7,279 | 15,912 | 182 | 377 |

生产配置还覆盖 7 次清空、6 次复位及 12 个完整容量组。DW 与矩阵共享端口测试检查 240 个任务、7,680 个向量和 122,880 个输出元素，逐个核对归属、标签、数值和七级延迟。

`prepare_measurement.py` 保存当前完整依赖并生成 1、2、4、16 个算术通道的独立综合配置。资源与组合级数由对应配置的实际映射结果报告。
