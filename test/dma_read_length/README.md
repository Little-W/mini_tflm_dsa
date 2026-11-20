# 读取突发长度的并行借位计算

线性 DMA 将物理突发拍数减一后保存为八位 `ARLEN`。各结果位的借位由较低位是否全部为零决定。FPGA 实现使用独立查找表处理低六位，共享低六位全零条件处理最高两位；通用 RTL 使用同一布尔关系。零拍数和超过八位的输入保留原有模减法结果，所有请求、地址、响应及完成周期保持。

## 生产参数测量

参考代码为 `3587da43`，参数为 `SIZE=64`、`CACHE_BLOCKS=64`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、四个读取上下文和 256 拍突发上限。

| 指标 | 参考实现 | 并行借位实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,648 | 1,655 |
| RAM LUT | 64 | 64 |
| 触发器 | 736 | 735 |
| CARRY4 | 170 | 168 |
| DSP48E1 | 1 | 1 |
| 寄存器间最长组合单元数 | 15 | 15 |
| `rd_start` 至 `rd_arlen_r` | 4 | 2 |
| `m_axi_arready` 至 `rd_arlen_r` | 7 | 5 |
| `rd_base_addr` 至 `rd_arlen_r` | 13 | 15 |
| `rd_burst_len_m1` 至 `rd_arlen_r` | 13 | 15 |

端口分析只标注外部时序起点，实际网表不增加寄存器。完整 SoC 的跨模块路径和物理面积由整机测量记录。

## 验证

官方 `LUT6_2` 模型和通用 RTL 各完成七组完整状态与公开输出形式比较，每组实现共 19,889 个比较位；外部输入保持任意取值。参数覆盖 32、64、128 位总线，8、16、32 位数据，1、2、3、4 个读取上下文以及生产配置的 64 行和 64 个缓存槽位。

32/64 位总线均使用官方 FPGA 功能模型运行固定及随机等待场景，共完成 752 个命令、282,596 次数据比较和 75,836 个周期，包含跨字、跨页、并发事务、错误返回及完成边沿接收新命令。数值与全部周期统计均与参考实现相同。

详细配置、源码摘要、实际逐单元路径与运行结果见 [measurement.json](measurement.json)。

```sh
python3 test/dma_read_length/prepare_measurement.py --out build/read_length/inputs
python3 scripts/fpga/open_fpga_synth.py --case-config build/read_length/inputs/cases.json --cases reference current --out build/read_length/synthesis
python3 test/dma_read_length/measure_paths.py --reference build/read_length/synthesis/reference --current build/read_length/synthesis/current --out build/read_length/paths.json
python3 test/dma_byte_layout/run_formal.py --reference-ref 3587da43 --context-parameters --production-parameters --fpga --out build/read_length/fpga_formal
python3 test/dma_byte_layout/run_formal.py --reference-ref 3587da43 --context-parameters --production-parameters --asic --out build/read_length/generic_formal
python3 test/linear_dma_context/run.py --fpga --bus-width 32 --verilator verilator-modern --out build/read_length/numeric32
python3 test/linear_dma_context/run.py --fpga --bus-width 64 --verilator verilator-modern --out build/read_length/numeric64
```
