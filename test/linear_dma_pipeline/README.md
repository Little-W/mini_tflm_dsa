# 线性 DMA 的突发准备与数据选择

## 当前结构

`axi_linear_block_dma` 使用同一组寄存器和算术处理首个读取突发、同一行的后续突发以及下一行。

接收命令或选择下一段时，保存物理地址和剩余拍数。长度选择阶段同时检查 4 KiB 页边界和配置的突发上限，将本段拍数写入寄存器。命令输出阶段形成 `ARADDR`、`ARLEN`、后续地址和剩余拍数。地址及长度在背压期间保持稳定；读描述符、响应标签、错误状态和总线在途计数分别保存。

普通读取和跨字读取的末拍序号分别比较。描述符同时保存跨字末拍序号，响应阶段使用三位分组的相等比较。命令是否可以交给发起器、描述符空间是否可用分别计算，使完成当前描述符的条件能够直接用于接收下一描述符。

写数据使用一个总线宽度的字节旋转结构，按照字节位置分别形成当前总线字和后续保留字。写配置保存跨字末拍序号；待发送突发计数的加一和减一结果并行计算。中止时，已经等待接收的 `WDATA`、`WSTRB`、`WLAST` 保持稳定，已经接收地址的后续突发使用零字节使能完成排空。

所有存储和算术均采用行为级 RTL。宽地址加法使用 `use_dsp` 综合属性；源文件中没有显式的 LUT、BRAM 或 DSP 原语实例。

## 接口时序

读取计划保存后，依次经过长度选择和命令输出两个寄存器阶段。`ARVALID` 还受可用在途容量控制。读取原始数据、解包元素、标签和完成事件仍由实际 AXI 响应驱动。

读写请求相互独立。连续命令可以在先前命令尚有响应未返回时被接收，生产参数保留四个读描述符和四个总线在途事务。写接口保持与参考实现相同的逐周期行为。

## 独立综合结果

生产参数为 `SIZE=64`、`BUS_WIDTH=64`、`DATA_WIDTH=16`、`REG_WIDTH=32`、`CACHE_BLOCKS=64`、`RD_CONTEXT_DEPTH=4`、`RD_TAG_WIDTH=3`、`READ_OUTSTANDING=4`、`WRITE_OUTSTANDING=4`、`DMA_MAX_BYTES=2048`。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 1,863 | 1,476 |
| 包含分布式 RAM 的名义 LUT 数量 | 1,919 | 1,556 |
| 触发器 | 718 | 824 |
| DSP | 1 | 9 |
| RAMB18 | 1 | 1 |
| 寄存器间最长组合级数 | 13 | 10 |
| 连接图完整性 | 完整 | 完整 |

当前实现减少 387 个逻辑 LUT 和 363 个名义 LUT。统计包括寄存器的数据、使能和控制输入，以及实际连接中的进位单元、算术单元和异步存储读取。此表记录模块独立综合；完整 SoC 的面积和 150 MHz 时序由整机综合与器件时序分析给出。

## 验证范围

| 验证项目 | 配置与检查内容 | 结果 |
| --- | --- | --- |
| 完整写模块等价 | 六组总线宽度、块大小、槽数量、在途数量和突发上限；包含任意中止、握手、数据和复位输入；共 6,659 个等价比特 | 通过 |
| 读取组合算术 | 八组参数，地址宽度 16、17、32、40，总线宽度 32、64、128、1024；检查页限制、长度、后续地址和剩余拍数 | 通过 |
| 严格四态比较 | 总线宽度 32、64、128、256；计数宽度 1、3、5、9；字节数据、掩码、偏移、计数和末拍判断；共 199,024 次检查 | 通过 |
| 生产读取 | 64 位总线、64 个缓存槽、64 行块、四个上下文及四个在途事务；固定延迟与随机阻塞各 332 条命令 | 通过 |
| 单上下文读取 | 32 位总线，一个上下文和一个在途事务；固定延迟与随机阻塞各 172 条命令；每次运行包含 171 次完成与接收同时发生 | 通过 |
| 生产写入 | 64 位总线，一或四个在途事务，固定延迟与随机阻塞；每种组合 276 条命令、103,590 个总线数据拍 | 通过 |
| 写周期比较 | 四种运行组合，各 131 条命令；与参考实现逐条比较周期统计，同时分别检查实际写入数据 | 通过 |
| 仲裁器中止与恢复 | 实际仲裁器和线性 DMA，64 位总线、64 个缓存槽、四个在途事务；24 项并发读写、R/B 错误、等待数据保持、准备阶段中止、准备阶段复位及恢复检查 | 通过 |

生产读取的每次运行检查 113,925 个原始总线字和 623,516 个解包元素，并实际达到四个在途事务和四个待完成命令。两次运行合计检查 227,850 个原始总线字及 1,247,032 个解包元素。

事务测试使用独立数据模型，保留地址顺序、页边界、总线负载稳定、字节使能、标签、错误归属、容量和排空检查。C++ 测试使用 C++20 和 UndefinedBehaviorSanitizer。完整参数、源文件散列值、命令和结果保存在 `validation.json` 及相应测试输出目录中。

## 运行方法

从仓库根目录执行，输出目录应选择新的路径。

```bash
python3 scripts/fpga/open_fpga_synth.py \
  --case-config test/linear_dma_pipeline/synthesis_cases.json \
  --cases linear_dma --out build/linear_dma_measure \
  --wide-alu-dsp-budget 740 --rtl-dsp-attributes \
  --max-register-path-cells 10 --require-register-path-limit

python3 test/linear_dma_pipeline/run_formal.py \
  --out build/linear_dma_formal

python3 test/linear_dma_pipeline/run_four_state.py \
  --out build/linear_dma_four_state

python3 test/linear_dma_context/run.py \
  --out build/linear_dma_read64 --size 64 --cache-blocks 64 \
  --bus-width 64 --outstanding 4 --contexts 4 --fpga

python3 test/linear_dma_context/run.py \
  --out build/linear_dma_read32 --bus-width 32 \
  --outstanding 1 --contexts 1 --fpga

python3 test/linear_dma_write_4k/run.py \
  --out build/linear_dma_write64 --size 64 --cache-blocks 64 \
  --bus-width 64 --outstanding 1 4 --fpga --jobs 1

python3 test/dma_abort_boundary/run.py \
  --out build/linear_dma_abort64 --bus-width 64 --size 16 --dma-size 64 \
  --cache-blocks 64 --data-width 16 --outstanding 4 \
  --fpga --prepare-abort --jobs 1
```

`run_formal.py` 可以通过 `--reference-rtl` 指定完整参考源文件；默认参考提交为 `dba30863fce7a6c42d6e863ceafebf2023110d97`。`linear_dma_write_4k/run.py` 的 `--reference-rtl` 选项会另外构建参考实现并执行写周期比较。各数值测试的 `--source-root` 选项支持固定的独立源码目录。
