# 线性 DMA 返回列范围

所有输出通道共同使用有效列数高段的零值结果。`zero_reduce` 将高段分为六位片段并行归并，再形成完整高段的零值标志。各通道保留自己的低段减法和列范围条件。数据、列号、描述符、输出有效位和返回周期保持相同。

## 功能检查

完整线性 DMA 在矩阵尺寸 16/64、总线宽度 32/64、读写各 1/4 项未完成事务以及 1/4 项描述符的组合下完成 32 项证明，共 47,904 个等价点。所有外部输入自由变化，公开输出、共享状态和展开的描述符存储共同参与检查。

高段归并在通用与 FPGA 方式下完成 695,296 次四态比较，覆盖 1、6、7、26、28、32、64 位数据、已知值、逐位未知值及控制归并结果的已知非零位。

实际读事务分别运行固定等待和随机等待，检查命令顺序、目的标签、返回数据、连续描述符、错误归属及 4 KiB 边界。两组测试共处理 1,150 个命令，检查 557,592 个输出元素。

## 完整模块映射

参数为 `SIZE=64`、`BUS_WIDTH=64`、`CACHE_BLOCKS=32`，读写各保留 4 项未完成事务，读描述符深度为 4。该缓存槽数量由生产配置的共享输入存储容量派生。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 名义 LUT 数量 | 1,486 | 1,490 |
| 最长寄存器间组合路径 | 10 | 10 |

映射采用相同的 `physical-cost` 配置，最大 LUT 输入数为 8，目标周期为 6,667 ps，布线延迟参数为 300 ps。完整 SoC 的描述符存储到返回资格路径由整机报告检查。

## 运行

```sh
mkdir -p build/linear_column_groups
git show 07a199ac:rtl/npu/dma/axi_linear_block_dma.sv > build/linear_column_groups/reference.sv
python test/frontend_depth_timing/linear_check.py \
  --reference build/linear_column_groups/reference.sv \
  --candidate rtl/npu/dma/axi_linear_block_dma.sv --sizes 16 64 \
  --out build/linear_column_groups/formal
python test/linear_column_groups/check_four_state.py --out build/linear_column_groups/four_state
python test/linear_dma_context/run.py --fpga --size 64 --cache-blocks 4 \
  --bus-width 64 --outstanding 4 --contexts 4 --out build/linear_column_groups/context
python test/linear_dma_4k/run.py --bus-width 64 --outstanding 4 \
  --out build/linear_column_groups/page
python test/linear_column_groups/measure.py --out build/linear_column_groups/mapping
```

`validation.json` 和 `measurement.json` 保存具体参数、源码摘要、功能检查和资源结果。
