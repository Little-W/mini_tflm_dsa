# DMA 写数据字节选择

宽总线先根据字节偏移的低两位选择四种位置，再由高位选择对应的部分结果。数据和字节使能采用相同的两段移位，分别形成当前写入字和后续保留字。寄存器、源数据消耗、AXI 突发划分和响应处理保持一致。

## 验证结果

- 六组参数完成写通道等价证明，共 6,659 个状态及输出位，覆盖 32、64、128 位总线和 1、4 个未完成写事务。
- 四组参数完成 199,024 次严格四态比较，覆盖 32、64、128、256 位总线。
- 64 位总线分别在 1、4 个未完成写事务配置下执行固定及随机等待测试。每组处理 276 个命令、1,919 个突发和 103,590 个数据拍，检查 618,940 个写入字节。
- 每种等待配置另执行 131 个单段命令，与参考实现逐项比较周期和传输数量。

64 位移位逻辑的独立映射包含 187 个 LUT，参考版本为 192 个。两侧均为 210 个寄存器，最长寄存器路径为 3 级。完整 DMA 和 SoC 的路径由整机测量检查。参数、源码散列和测试摘要保存在 [validation.json](validation.json)。

## 重复执行

```sh
python3 test/linear_dma_pipeline/run_formal.py \
  --out build/linear_dma_write_selection/formal
python3 test/linear_dma_pipeline/run_four_state.py \
  --out build/linear_dma_write_selection/four_state
python3 test/linear_dma_write_4k/run.py --source-root . \
  --bus-width 64 --size 64 --cache-blocks 64 --outstanding 1 4 --fpga \
  --jobs 1 --out build/linear_dma_write_selection/protocol
python3 test/linear_dma_write_selection/prepare_measurement.py \
  --out build/linear_dma_write_selection/measurement
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/linear_dma_write_selection/measurement/cases.json \
  --cases reference current --out build/linear_dma_write_selection/measurement/results
```
