# IA 输入列排列

IA 写入端将当前总线中的数值和有效位排列为完整行，再根据列起点同时左移。每列直接取得对应的数据段和有效位，越过行末的数据移出。未使能的输入通道先填零，使无效数据输出与原有实现一致。

该结构保持槽位地址、有效行列数、同步存储周期和全部公开输出周期。原有存储容量和格式转换保持一致。

## 独立综合

生产参数为 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`CACHE_BLOCKS=32`，使用外部共享存储，RAM 字地址为 12 位。

| 资源 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 2,370 | 1,979 |
| 分布式 RAM LUT | 8 | 8 |
| 触发器 | 354 | 354 |
| CARRY4 | 129 | 130 |
| 最长寄存器间组合单元数 | 11 | 11 |

两个实现均未新增 DSP 或块 RAM。上述结果采用相同的模块参数和综合设置。

## 验证

五组完整状态比较包含本地存储与外部存储，覆盖 4 / 8 / 16 列、32 / 64 / 128 位总线、8 / 16 位数据以及 2 / 4 / 32 个宽数据槽位，共证明 12,308 位状态与输出等价。外部输入不附加取值限制。

实际缓存测试覆盖 256 种 INT8 偏置和 65,536 种 INT16 位型，通过 592,832 次数值比较、2,663 次补零比较及 64 个同时读写周期。完整 IA 加载器测试完成 81 个场景、724,032 次数值比较、1,515 次 DMA 请求和 138 次槽位回绕。两个测试累计 309,050 个周期，并启用 C++ 未定义行为检查。

完整参数、源码与仿真程序摘要、形式结果和综合统计见 `docs/data/ia_write_layout_validation.json`。

```sh
python3 test/ia_write_layout/run_formal.py --out build/ia_write_formal
python3 test/ia_write_layout/synthesis.py --reference-ref 05be5b8 --out build/ia_write_synth/reference
python3 test/ia_write_layout/synthesis.py --out build/ia_write_synth/current
python3 test/ia_compact/run.py --verilator verilator-modern --only cache --out build/ia_write_cache
python3 test/ia_compact/run.py --verilator verilator-modern --only loader --loader-cache-blocks 32 --out build/ia_write_loader32
```

## 紧凑读数据

紧凑模式的有效偏移位宽、读数据重建结构及相应功能和路径比较见 [IA 紧凑读数据重建](../ia_compact/READ_EXPANSION.md)。
