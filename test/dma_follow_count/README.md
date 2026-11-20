# 读取合并与后续拍数的并行计算

线性DMA分别计算页边界和物理突发长度限制。剩余拍数超过页内空间且页内空间小于突发上限时，后续拍数使用页差值；其他情况下，按突发上限差值或零选择。两种差值与限制判断同时计算，选择输出无需再经过减法。

连续行仅在起始地址按总线字对齐、行跨度等于每行字节数、行数大于一且合并后不超过256拍时合并。合并拍数使用 `rows × burst_len_m1 + rows`，线性读取模式把乘法的突发长度分量设为零。行跨度通过 `add_equal` 的逐位进位关系直接比较，保持完整地址宽度和原有截断行为。

全部请求、响应、上下文存储和事务完成周期保持一致。

## 生产参数资源

参考提交为 `e6fd2b1f`。完整DMA采用 `SIZE=64`、`CACHE_BLOCKS=64`、BUS64、四项读取上下文和256拍突发上限。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑LUT | 1,655 | 1,675 |
| RAM LUT | 64 | 64 |
| FF | 735 | 737 |
| CARRY4 | 168 | 168 |
| DSP48E1 | 1 | 1 |
| 寄存器间最长组合路径 | 15 | 14 |
| 基地址至后续拍数 | 16 | 10 |
| 突发长度至后续拍数 | 16 | 10 |
| 行数至后续拍数 | 16 | 10 |
| 行跨度至后续拍数 | 17 | 10 |
| 基地址或突发长度至ARLEN | 15 | 13 |

端口路径分析只添加接口边界标识，实际电路中没有新增这些分析寄存器。完整SoC的路径由对应固定源码的整机报告记录。

## 验证

使用官方FPGA原语模型的11组完整模块形式比较和通用RTL的7组形式比较均通过，比较全部原有状态与公开输出，不限制外部输入。参数覆盖32、64、128、1024位总线，16、17、32位地址，1、2、3、4项上下文，8、256字节等不同突发上限，以及生产64行、64缓存槽位配置。

BUS32和BUS64的实际FPGA模型数值测试完成752个命令、282,596次数据比较、75,836个周期。测试覆盖跨总线字、跨4 KiB页、并发上下文、固定与随机等待、错误返回、完成边沿接收新命令。每次测试的全部统计和周期均与参考记录一致。

`measurement.json` 保存源码摘要、所有证明配置、数值结果、原生综合网表资源和具体组合路径。

## 运行命令

```sh
python3 test/dma_byte_layout/run_formal.py --reference-ref e6fd2b1f \
  --production-parameters --context-parameters --address-parameters \
  --fpga --out build/follow_count/formal_fpga
python3 test/dma_byte_layout/run_formal.py --reference-ref e6fd2b1f \
  --production-parameters --context-parameters --asic \
  --out build/follow_count/formal_generic

python3 test/linear_dma_context/run.py --fpga --bus-width 32 \
  --verilator verilator-modern --out build/follow_count/numeric32
python3 test/linear_dma_context/run.py --fpga --bus-width 64 \
  --verilator verilator-modern --out build/follow_count/numeric64

python3 test/dma_read_length/prepare_measurement.py --reference e6fd2b1f \
  --out build/follow_count/inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/follow_count/inputs/cases.json \
  --cases reference current --out build/follow_count/synthesis
python3 test/dma_follow_count/measure_paths.py \
  --source build/follow_count/synthesis --out build/follow_count/paths.json
```
