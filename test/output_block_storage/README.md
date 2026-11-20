# INT16 输出队列的块存储实现

`vec_s16_to_fifo` 通过公共存储封装的同步读端口保存输出数据，并指定块 RAM 类型。生产参数为 16 个 INT16 数据通道、4 个存储分组和 64 位输出总线，数组容量为 16,384 位。写入掩码、读取周期、同地址读写行为和背压处理均由现有接口测试检查。

| 综合项目 | 自动选择存储类型 | 指定块 RAM |
| --- | ---: | ---: |
| 逻辑 LUT | 247 | 242 |
| 分布式存储 LUT | 344 | 0 |
| 合计 LUT | 591 | 242 |
| 触发器 | 312 | 56 |
| RAMB36E1 | 0 | 4 |
| 最长组合路径级数 | 7 | 7 |

32 位和 64 位总线各通过 81 个场景、12,392 个输出字节检查，并逐周期比较全部公开输出。资源数据对应模块独立综合；完整 SoC 的资源和时序由整机报告给出。

```sh
python test/output_block_storage/synthesis.py --out build/output_block_storage
python test/writeback_bus/run.py --out build/output_block_bus32 --bus-width 32 --reference 8215cb95 --verilator verilator-modern
python test/writeback_bus/run.py --out build/output_block_bus64 --bus-width 64 --reference 8215cb95 --verilator verilator-modern
```
