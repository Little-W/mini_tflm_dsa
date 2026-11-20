# 向量写回的数据循环选择

## 实现

`vector_writeback` 根据本次传输的字节偏移循环选择各总线通道的数据。每级循环选择的相邻两个数据位共用一个控制位，FPGA 实现使用一个 `LUT6_2` 完成这两个独立的二选一运算。通用实现保留同一循环选择表达式。

请求字段、数据来源、写入掩码、响应处理以及全部寄存周期保持一致。结果存储仍由调用者持有，直至写回响应完成。该模块保存事务元数据，数据选择本身没有增加寄存器。

## 综合结果

固定参考提交为 `7419df81`。两份实现均采用 `TILE=16`、`BUS_WIDTH=64` 和相同的 Xilinx 7 系列原生综合流程。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 674 | 527 |
| 触发器 | 55 | 55 |
| CARRY4 | 21 | 21 |
| DSP / RAM LUT / SRL | 0 / 0 / 0 | 0 / 0 / 0 |
| 寄存器间最长组合单元数 | 9 | 8 |

逻辑 LUT 减少 147 个，约 21.8%。最长路径按逐位连接图计算，两个实现的图均完整。完整 SoC 的物理 LUT 数量与 150 MHz 时序由整机实现报告统计。

## 验证

完整模块的形式等价比较覆盖所有公开输出及寄存状态，外部输入没有附加取值限制。FPGA 分支使用官方 `LUT6_2` 功能模型。

| `TILE` | `BUS_WIDTH` | 实现 | 等价结果位 |
|---:|---:|---|---:|
| 8 | 32 | FPGA | 466 |
| 16 | 32 | FPGA | 733 |
| 16 | 64 | FPGA | 910 |
| 16 | 128 | FPGA | 1319 |
| 32 | 64 | FPGA | 1437 |
| 16 | 64 | 通用 | 910 |

六组共 5775 位全部通过。实际 FPGA 数值测试使用独立的字节参考模型，遍历两种输出模式、所有总线内字节偏移以及 1 至 64 字节的请求长度，并随机延迟授权、数据接收和写响应。

| 总线宽度 | 请求数 | 检查的数据字节数 | 接收的数据传输次数 | 背压周期 | 错误响应次数 | 总周期 |
|---:|---:|---:|---:|---:|---:|---:|
| 32 | 512 | 16640 | 4544 | 1652 | 31 | 9524 |
| 64 | 1024 | 33280 | 5056 | 1734 | 61 | 13447 |
| 128 | 2048 | 66560 | 6080 | 2015 | 121 | 21407 |
| 合计 | 3584 | 116480 | 15680 | 5401 | 213 | 44378 |

每次传输检查写地址、长度、字节掩码、数据、末尾填充、错误结果和完成后的请求接收状态。所有背压周期检查数据和掩码保持稳定。全部 C++ 编译单元启用未定义行为检查，三种总线配置分别包含 12、15、27 个编译单元。

`docs/data/vector_writeback_rotation_validation.json` 保存参考与当前源码摘要、原语模型摘要、证明结果、数值测试和综合记录。当前源码 SHA-256 为 `3ec84705707f6bdece3163a96bedaeec38c1dee2743c496b43b840acb6a5d4f5`，参考源码为 `e6aac27c0b141b9d3dd06544df95fb54de15eeea12bfe7cba2f000786dcea3f3`。

## 复现

```bash
python3 test/vector_writeback_rotation/run.py \
  --reference 7419df81 --out build/vector_writeback_rotation \
  --verilator verilator-modern
python3 test/vector_writeback_rotation/prepare_measurement.py \
  --reference 7419df81 --out build/vector_writeback_rotation/sources
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/vector_writeback_rotation/sources/cases.json \
  --cases reference current --out build/vector_writeback_rotation/synthesis
```
