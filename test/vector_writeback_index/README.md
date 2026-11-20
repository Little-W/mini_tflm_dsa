# 向量写回银行地址寄存

`vector_writeback` 在接收事务时保存字节旋转起点和每个总线银行的组地址。每接受一个数据周期，各银行组地址增加一。数据选择直接使用这些寄存器，事务长度、掩码、写入响应和结果存储的使用期限保持原有行为。

事务地址的低位记为 `offset`，总线字节数记为 `B`。起始旋转银行为 `(-offset) mod B`，第 `bank` 个银行的初始组地址为 `offset < B-bank`。有效数据周期满足：

```text
selected_byte = B + written_bytes - lane_offset
first_bank = selected_byte mod B
group_index[bank] = floor(selected_byte / B) + (bank < first_bank)
```

每次继续传输时增加的有效字节数恰好使各银行组地址增加一。最后一个周期完成后，控制器等待写入响应；下一事务重新计算全部地址。增加这些地址寄存器没有增加事务周期。

## 资源和组合路径

使用相同的原生 Xilinx 映射流程，生产参数为 `TILE=16`、`BUS_WIDTH=64`。

| 项目 | 参考源码 `7254ced6` | 当前源码 |
| --- | ---: | ---: |
| 逻辑 LUT | 527 | 521 |
| FF | 55 | 90 |
| CARRY4 | 21 | 21 |
| 内部寄存器之间的最长组合路径 | 8 | 8 |
| 寄存器至 `src_wdata` 的最长组合路径 | 11 | 7 |
| 包含数据及请求地址接口边界的最长组合路径 | 11 | 8 |

数据输出路径的分析在真实映射输出导线上添加分析端点，原始综合网表及组合连接保持不变。图中所有原语均完成分类。完整 SoC 连接 DMA 写入缓存后的路径由对应整机测量记录。

## 验证

形式比较包含七组原有状态寄存器、每个周期的公开控制和元数据，以及 `src_wvalid` 为真时的全部数据位。同时归纳证明每个有效周期的银行地址与上式一致。首个边沿施加复位，其余输入均不加限制，包括后续复位、请求长度、任意背压、写入授权和完成响应。

FPGA 原语模型覆盖 `(TILE, BUS_WIDTH)` 为 `(8,32)`、`(16,32)`、`(16,64)`、`(16,128)`、`(32,64)` 五种配置；通用 RTL 另验证 `(16,64)`。实际 LUT 功能来自当前 Yosys 的官方 `LUT6_2` 模型。

独立数值测试使用同一 FPGA 模型，覆盖 BUS32、BUS64、BUS128 的全部地址偏移、1 至 64 字节长度和两种输出模式，共 3,584 个事务、116,480 个有效字节。测试检查每次有效传输的数据与掩码、背压期间的数据保持、描述符、响应等待和错误完成。测试程序启用 UBSan。统计和源码摘要保存在 `measurement.json`。

## 运行命令

```sh
python3 test/vector_writeback_index/run.py \
  --out build/writeback_bank/verification --verilator verilator-modern

python3 test/vector_writeback_rotation/prepare_measurement.py \
  --reference 7254ced6 --out build/writeback_bank/inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/writeback_bank/inputs/cases.json \
  --cases reference current --out build/writeback_bank/synthesis
python3 test/vector_writeback_index/measure_paths.py \
  --source build/writeback_bank/synthesis --out build/writeback_bank/paths.json
```
