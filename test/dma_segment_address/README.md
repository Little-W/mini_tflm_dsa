# DMA 突发分段与后续地址

`axi_linear_block_dma` 对首个突发和后续突发分别计算长度限制、页内剩余拍数及下一地址。分段计算使用显式组合逻辑。下一地址的低位与突发字节跨度相加，上部地址并行预先计算加一结果，低位进位只选择上部地址。

地址宽度超过突发跨度位数时使用分段地址加法；较窄地址使用完整位宽的模加法。两种结构均显式保留未使用的最终进位。读命令、在途响应、标签、跨字数据和错误返回的周期保持一致，写入通道同时保留原有行为。

## 综合结果

完整模块比较使用 `SIZE=16`、`BUS_WIDTH=64`、`DATA_WIDTH=16`、`REG_WIDTH=32`、`RD_CONTEXT_DEPTH=4` 和 `DMA_MAX_BYTES=2048`，参考提交为 `cd0455b`。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,708 | 1,731 |
| 触发器 | 1,013 | 1,013 |
| CARRY4 | 183 | 183 |
| DSP48E1 | 1 | 1 |
| 最长寄存器间组合路径 | 20 | 16 |

至 `rd_follow_addr` 寄存器的实际连接路径如下。组合输入只在分析副本中表示为零深度边界，不增加硬件寄存器。

| 起点 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| `rd_burst_len_m1` 输入 | 21 | 16 |
| `rd_base_addr` 输入 | 21 | 16 |
| `rd_rows_to_read` 输入 | 21 | 16 |
| `rd_row_stride` 输入 | 21 | 17 |
| `rd_follow_addr` 寄存器 | 18 | 14 |
| `rd_cmd_row_addr` 寄存器 | 20 | 16 |

新增 23 个 LUT 用于地址高位的并行计算和选择。完整 SoC 的资源与器件时序由固定整机测量记录。

## 验证

九组完整状态和输出比较共证明 51,355 位，外部输入不增加约束。配置包括 32、64、128、1024 位总线，16、17、32 位地址，8、16、32 位数据和 1、2、4 个命令上下文。1024 位总线配置分别检查完整位宽加法与仅有一个地址高位的分段加法；生产总线配置另外检查单拍和 32 拍物理突发限制。

BUS32、BUS64 的固定等待和随机等待测试共完成 752 个命令、282,596 次结果比较和 75,836 个周期，覆盖四笔在途事务、四个独立上下文、跨页、跨字、标签顺序、完成与新命令同时发生，以及错误返回。

源码、综合网表、仿真程序摘要和详细路径保存在 [measurement.json](measurement.json)。

```bash
python3 test/dma_byte_layout/run_formal.py \
  --out build/dma_segment/formal --reference-ref cd0455b --address-parameters
python3 test/dma_byte_layout/synthesis.py \
  --out build/dma_segment/reference --reference-ref cd0455b
python3 test/dma_byte_layout/synthesis.py --out build/dma_segment/current
python3 test/dma_segment_address/measure_paths.py \
  --reference build/dma_segment/reference --current build/dma_segment/current \
  --out build/dma_segment/paths.json
python3 test/linear_dma_context/run.py \
  --out build/dma_segment/context32 --bus-width 32 --outstanding 4 --contexts 4 \
  --verilator verilator-modern
python3 test/linear_dma_context/run.py \
  --out build/dma_segment/context64 --bus-width 64 --outstanding 4 --contexts 4 \
  --verilator verilator-modern
```
