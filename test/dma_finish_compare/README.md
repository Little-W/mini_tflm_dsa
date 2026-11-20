# DMA 读取完成的并行比较

`axi_linear_block_dma` 使用已有的 `add_equal` 结构并行检查各位进位条件。跨字读取通过 `burst_len_m1 + 1 == rd_rsp_beat_cnt` 判断末拍，通过 `rd_rsp_row_cnt + 1 == rows` 判断末行。比较分别保留九位和行计数器的完整位宽，包含溢出回绕。线性读取的零拍、一拍条件与原有完成优先级保持一致。

这项修改不增加流水阶段，所有状态更新和公开输出周期保持一致。新增实例使用显式边界信号和中文说明，继续由综合工具选择存储器资源。

## 实测资源与路径

参考提交为 `2b1991822fdd395cd55397e1b7a2953dc2bf58f4`。独立综合使用 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`CACHE_BLOCKS=4`、`RD_CONTEXT_DEPTH=4`，两份实现采用相同的七系列综合流程。

| 项目 | 参考实现 | 并行比较实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,642 | 1,649 |
| 分布式 RAM LUT | 60 | 60 |
| 触发器 | 721 | 722 |
| CARRY4 | 183 | 178 |
| DSP48E1 | 1 | 1 |
| RAMB18 / RAMB36 | 0 / 0 | 0 / 0 |
| 寄存状态至 `rd_finish_beat` 最长组合单元数 | 9 | 7 |
| 完整模块最长寄存器间组合单元数 | 16 | 16 |

完成输出的路径减少两个组合单元。独立模块的最长路径仍位于突发分段与地址生成，最终要求为不超过 15 个组合单元；完整 SoC 的路径由固定整机版本重新测量。

## 验证结果

11 组完整模块状态与输出比较全部通过，共证明 58,486 位等价。全部外部输入保持自由，参数覆盖 32、64、128、1,024 位总线，8、16、32 位数据，1、2、3、4 个描述符，16、17、32 位地址，以及单拍、32 拍和 256 拍物理突发上限。生产参数包含 `SIZE=64` 和 `CACHE_BLOCKS=64`。

BUS32/64 的固定等待和随机等待共完成 752 个命令、282,596 次数据比较和 75,836 个周期。所有命令、数据节拍、错误、同时接收与完成、总线等待及周期统计均与参考实现一致。详细配置、实际路径、源码与仿真程序 SHA-256 见 [measurement.json](measurement.json)。

## 复现

```sh
python3 test/dma_byte_layout/run_formal.py \
  --reference-ref 2b1991822fdd395cd55397e1b7a2953dc2bf58f4 \
  --out build/dma_finish_compare_formal \
  --address-parameters --context-parameters --production-parameters
python3 test/dma_byte_layout/synthesis.py \
  --reference-ref 2b1991822fdd395cd55397e1b7a2953dc2bf58f4 \
  --out build/dma_finish_compare_synth/reference
python3 test/dma_byte_layout/synthesis.py --out build/dma_finish_compare_synth/current
python3 test/dma_finish_compare/measure_paths.py \
  --reference build/dma_finish_compare_synth/reference \
  --current build/dma_finish_compare_synth/current \
  --out build/dma_finish_compare_synth/paths.json
python3 test/linear_dma_context/run.py \
  --out build/dma_finish_compare_context32 --bus-width 32 --verilator verilator-modern
python3 test/linear_dma_context/run.py \
  --out build/dma_finish_compare_context64 --bus-width 64 --verilator verilator-modern
```
