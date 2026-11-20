# DMA 末拍与命令完成输出

`axi_linear_block_dma` 的 FPGA 实现使用一个 `LUT6_2` 同时生成行完成和命令完成信号。查找表输入为响应握手、跨字标志、两类末拍比较结果及末行比较结果。行地址低位只影响最终选择，所有响应计数、命令队列、错误状态和公开接口周期保持一致。

## 资源与路径

综合采用完整 SoC 中的 `SIZE=64`、`CACHE_BLOCKS=64`、`DATA_WIDTH=16`、`BUS_WIDTH=64` 和 `RD_CONTEXT_DEPTH=4`。参考提交为 `2f06471c`。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,664 | 1,670 |
| 触发器 | 735 | 735 |
| DSP48E1 | 1 | 1 |
| CARRY4 | 181 | 181 |
| 最长寄存器间组合路径 | 16 | 16 |
| 行地址低三位到 `rd_finish_beat` | 5 | 3 |

输出端口路径直接统计生产网表中的连接，分析用端点不增加硬件单元。整机各模块连接后的路径由完整 `soc_top` 综合记录。

## 验证

七组参数的完整状态、全部描述符存储字和公开输出形式比较通过，共 17,767 个比较位。配置覆盖 32、64、128 位总线，8、16、32 位数据，1、2、3、4 个命令上下文，以及整机的 64 行和 64 个缓存槽位。全部外部输入保持任意取值。

32 位与 64 位总线仿真均使用官方 FPGA 查找表功能模型，固定等待和随机等待合计完成 752 个命令、282,596 次结果比较和 75,836 个周期。测试覆盖跨页、跨字、等待、错误返回以及完成与新命令同时接收。

源码摘要、资源、实际连接路径和运行结果保存在 [measurement.json](measurement.json)。

```bash
python3 test/dma_completion_share/prepare_measurement.py --out build/dma_completion_inputs
python3 scripts/fpga/open_fpga_synth.py --case-config build/dma_completion_inputs/cases.json --cases reference current --out build/dma_completion_synth
python3 test/dma_return_finish/measure_paths.py --synthesis build/dma_completion_synth --out build/dma_completion_paths.json
python3 test/dma_byte_layout/run_formal.py --out build/dma_completion_formal --reference-ref 2f06471c --context-parameters --production-parameters --observe-context-storage --fpga
python3 test/linear_dma_context/run.py --out build/dma_completion_sim32 --bus-width 32 --outstanding 4 --contexts 4 --verilator verilator-modern --fpga
python3 test/linear_dma_context/run.py --out build/dma_completion_sim64 --bus-width 64 --outstanding 4 --contexts 4 --verilator verilator-modern --fpga
```
