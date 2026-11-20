# DMA 字节排列与零点运算

读取响应把当前总线字和前一个总线字连接起来，再根据字节偏移选择完整数据。写入数据在扩展位宽后执行一次左移，低半部分进入当前传输，高半部分保存到跨字传输寄存器；字节掩码使用相同结构。

INT8 和 INT16 输入先选择统一的十六位数值，再按输出通道共用零点加法器。数据范围、输出有效位、列填充以及原有位宽转换保持一致。公开接口、状态更新和传输周期保持一致，新增组合逻辑使用显式信号与命名生成结构。

## 资源

独立模块采用生产参数 `SIZE=16`、`BUS_WIDTH=64`、`DATA_WIDTH=16` 和四项读取上下文。

| 资源 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 1,914 | 1,744 |
| 触发器 | 1,025 | 1,013 |
| CARRY4 | 201 | 183 |
| DSP48E1 | 1 | 1 |
| 最长寄存器间组合单元数 | 20 | 20 |

两个实现均未使用分布式 RAM 或块 RAM。完整 SoC 的实际 LUT 与时序由对应固定版本的实现报告记录。

## 验证

五组全输入状态比较覆盖 32 / 64 / 128 位总线、8 / 16 / 32 位数据、一个 / 两个 / 四个读取上下文，共证明 9,667 位状态与输出等价。形式比较使用完整 `axi_linear_block_dma`，不约束外部输入。

读取专项完成 1,160 条命令、481,052 次数据比较和 122,321 个周期。检查包含非整字地址、跨 4 KiB 页边界、INT8 / INT16、有效列填充、并行描述符、输入阻塞以及错误返回后的继续执行。

写入专项覆盖 32 / 64 位总线以及一个 / 四个在途事务，完成 1,680 条命令、3,123,136 次字节比较和 1,206,873 个周期。固定和随机阻塞分别检查地址、写入数据、掩码、跨页传输与完成响应。

源码、仿真程序、形式结果与综合网表统计保存在 `docs/data/dma_byte_layout_validation.json`。

## 运行方法

```sh
python3 test/dma_byte_layout/run_formal.py --out build/dma_byte_formal
python3 test/dma_byte_layout/synthesis.py --reference-ref e19e4f4 --out build/dma_byte_synth/reference
python3 test/dma_byte_layout/synthesis.py --out build/dma_byte_synth/current
python3 test/linear_dma_context/run.py --verilator verilator-modern --bus-width 32 --outstanding 4 --contexts 4 --out build/dma_byte_context32
python3 test/linear_dma_context/run.py --verilator verilator-modern --bus-width 64 --outstanding 4 --contexts 4 --out build/dma_byte_context64
python3 test/linear_dma_context/run.py --verilator verilator-modern --bus-width 64 --outstanding 1 --contexts 1 --out build/dma_byte_context1
python3 test/linear_dma_write_4k/run.py --verilator verilator-modern --bus-width 32 --outstanding 1 4 --out build/dma_byte_write32
python3 test/linear_dma_write_4k/run.py --verilator verilator-modern --bus-width 64 --outstanding 1 4 --out build/dma_byte_write64
```
