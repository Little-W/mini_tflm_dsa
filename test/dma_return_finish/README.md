# DMA 读取完成判断

`axi_linear_block_dma` 并行比较无跨字和跨字两种情况的最后一拍。行地址低位决定数据是否跨字，并选择已经计算的比较结果。线性读取分别在第零拍或第一拍完成；多拍读取使用描述符末拍编号或该编号加一。握手、行推进、在途命令、错误记录和完成输出保持原有周期。

## 综合结果

比较采用 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`RD_CONTEXT_DEPTH=4`，参考提交为 `038a095`。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,744 | 1,708 |
| 触发器 | 1,013 | 1,013 |
| DSP48E1 | 1 | 1 |
| CARRY4 | 183 | 183 |
| 最长寄存器间组合路径 | 20 | 20 |
| 行地址低三位至 `rd_finish_beat` 输出 | 9 | 8 |

输出路径按生产综合网表的实际连接计算，输出端点不增加逻辑或硬件寄存器。整机时序由对应的完整 SoC 综合与目标器件实现报告记录。

## 验证

五组参数的完整状态与输出比较共证明 11,659 位，覆盖 32/64/128 位总线、8/16/32 位数据和 1/2/4 个命令上下文，外部输入不增加约束。

BUS32、BUS64 的上下文测试覆盖固定等待和随机等待，合计完成 752 个命令、282,596 次结果比较和 75,836 个周期。测试包含跨页、跨字、命令切换、完成与新请求同时发生、AXI 等待和错误返回。

源码、网表、测试程序和运行摘要见 [measurement.json](measurement.json)。

```bash
python3 test/dma_byte_layout/run_formal.py --out build/dma_return_formal --reference-ref 038a095
python3 test/dma_byte_layout/synthesis.py --out build/dma_return_synth/reference --reference-ref 038a095
python3 test/dma_byte_layout/synthesis.py --out build/dma_return_synth/current
python3 test/dma_return_finish/measure_paths.py --synthesis build/dma_return_synth --out build/dma_return_paths.json
python3 test/linear_dma_context/run.py --out build/dma_return_context32 --bus-width 32 --outstanding 4 --contexts 4 --verilator verilator-modern
python3 test/linear_dma_context/run.py --out build/dma_return_context64 --bus-width 64 --outstanding 4 --contexts 4 --verilator verilator-modern
```
