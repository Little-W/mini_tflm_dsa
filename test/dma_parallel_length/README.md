# AXI读取突发长度的并行计算

`axi_linear_block_dma` 同时计算剩余拍数、页边界和物理突发上限对应的 `ARLEN`。页内末尾拍序号使用地址取反计算，非整字地址额外扣除一拍；剩余拍数的减一结果与限制条件并行计算。最终选择直接输出已经完成的候选长度。

设计保留原有页边界判断、后续地址、上下文存储、响应顺序及事务完成周期。所有位宽的截断行为均由显式中间信号限定。

## 生产参数测量

参考提交为 `08a9aa92`。完整模块采用 `SIZE=64`、`CACHE_BLOCKS=64`、64位总线、四项读取上下文和256拍突发上限。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 原生映射逻辑LUT | 1,675 | 1,697 |
| 原生映射FF | 737 | 735 |
| 原生映射DSP48E1 | 1 | 1 |
| 原生映射RAM LUT | 64 | 64 |
| 原生映射寄存器间最长路径 | 14 | 14 |
| 原生映射DSP输出端口至ARLEN | 11 | 9 |
| 物理成本映射逻辑LUT | 1,548 | 1,578 |
| 物理成本映射寄存器间最长路径 | 15 | 15 |
| 物理成本映射DSP输出端口至ARLEN | 11 | 8 |

端口路径测量在分析图中标记DSP输出端口，实际电路没有新增寄存器。此项测量只描述该端口之后的逻辑；完整SoC的寄存器路径还包括DSP内部组合部分及相邻模块。

## 验证

11组官方FPGA原语模型比较与7组通用RTL比较均通过，检查完整模块的原有状态与公开输出，不限制外部输入。参数覆盖32、64、128、1024位总线，16、17、32位地址，1至4项读取上下文及不同突发上限。

BUS32和BUS64的FPGA数值测试完成752个命令、282,596次输出数据比较和75,836个周期。全部统计与参考结果一致，覆盖跨字、跨4 KiB页、并发上下文、固定与随机等待及错误返回。

`measurement.json` 保存源码、映射网表、证明脚本和日志的SHA256，以及完整资源、路径和数值结果。每项结果均检查使用相同的RTL源码。

## 运行命令

```sh
python3 test/dma_byte_layout/run_formal.py --reference-ref 08a9aa92 \
  --production-parameters --context-parameters --address-parameters \
  --fpga --out build/parallel_length/formal_fpga
python3 test/dma_byte_layout/run_formal.py --reference-ref 08a9aa92 \
  --production-parameters --context-parameters --asic \
  --out build/parallel_length/formal_generic
python3 test/linear_dma_context/run.py --fpga --bus-width 32 \
  --verilator verilator-modern --out build/parallel_length/numeric32
python3 test/linear_dma_context/run.py --fpga --bus-width 64 \
  --verilator verilator-modern --out build/parallel_length/numeric64

python3 test/dma_read_length/prepare_measurement.py --reference 08a9aa92 \
  --out build/parallel_length/inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/parallel_length/inputs/cases.json \
  --cases reference current --out build/parallel_length/synthesis
python3 test/dma_parallel_length/measure_paths.py \
  --reference build/parallel_length/synthesis/reference \
  --current build/parallel_length/synthesis/current \
  --out build/parallel_length/paths.json
```
