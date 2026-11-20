# 读取首段地址的并行计算

`axi_linear_block_dma` 分别计算普通首行与合并首行的后续地址。两种地址各自完成页边界限制、突发长度限制和地址加法，再由 `rd_merge_rows` 选择结果。后续突发使用原有地址计算结构。

在256拍突发上限配置中，合并条件已经检查总拍数不超过256。合并地址分支直接使用该拍数；其他突发上限继续保留完整限制计算。合并条件为假时，选择普通首行地址。该结构保留完整地址宽度、模加法、所有状态更新及公开接口周期。

## 生产参数测量

参考提交为 `38f32d93`，其中包含读取突发长度的并行计算。完整模块采用 `SIZE=64`、`CACHE_BLOCKS=64`、64位总线、四项读取上下文和256拍突发上限。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 原生映射逻辑LUT | 1,697 | 1,729 |
| 原生映射FF | 735 | 738 |
| 原生映射寄存器间最长组合路径 | 14 | 14 |
| 原生映射DSP输出端口至 `rd_follow_addr` | 8 | 7 |
| 原生映射DSP输出端口至ARLEN | 9 | 7 |
| 物理成本映射逻辑LUT | 1,578 | 1,601 |
| 物理成本映射FF | 735 | 735 |
| 物理成本映射寄存器间最长组合路径 | 15 | 14 |
| 物理成本映射DSP输出端口至 `rd_follow_addr` | 8 | 6 |
| 物理成本映射DSP输出端口至ARLEN | 8 | 8 |
| DSP48E1 | 1 | 1 |
| RAM LUT | 64 | 64 |

物理成本映射增加23个逻辑LUT，使DSP输出端口至后续地址的路径减少两级。端口路径分析只在分析图中标记DSP输出，实际电路保持原有寄存器边界。寄存器间路径分析包含LUT、CARRY4、MUXF和有效DSP组合段；结构级数用于评估逻辑深度，150 MHz仍需器件布局布线时序分析。

当前RTL文件的SHA256为 `945a747b9b9ec5f1feae4ceedab23dbb223fefdc505b0e1612f0410e98701d50`。表中LUT数量为映射后、放置前的原语计数；RAM LUT单独列出。

## 验证结果

完整模块的18组形式比较全部通过，合计检查84,423位原有状态与公开输出，外部输入不增加约束。官方FPGA原语模型检查11组参数，通用RTL检查7组参数，覆盖32、64、128、1024位总线，16、17、32位地址，1至4项读取上下文和不同突发上限。

BUS32、BUS64的FPGA数值测试共完成752个命令、282,596次输出数据比较和75,836个周期。全部统计与参考结果一致，覆盖跨字、跨4 KiB页、并发上下文、固定与随机等待、完成边沿接收新命令和错误返回。

`measurement.json` 保存源码哈希、形式比较结果、数值结果、映射资源和具体路径。参考实现与当前实现采用相同的公共RTL依赖、综合参数和数值测试程序。

## 运行命令

```sh
python3 test/dma_byte_layout/run_formal.py --reference-ref 38f32d93 \
  --production-parameters --context-parameters --address-parameters \
  --fpga --out build/first_address/formal_fpga
python3 test/dma_byte_layout/run_formal.py --reference-ref 38f32d93 \
  --production-parameters --context-parameters --asic \
  --out build/first_address/formal_generic
python3 test/linear_dma_context/run.py --fpga --bus-width 32 \
  --verilator verilator-modern --out build/first_address/numeric32
python3 test/linear_dma_context/run.py --fpga --bus-width 64 \
  --verilator verilator-modern --out build/first_address/numeric64
python3 test/dma_first_address/prepare_reference.py --reference 38f32d93 \
  --out build/first_address/reference_runtime
python3 build/first_address/reference_runtime/test/linear_dma_context/run.py \
  --fpga --bus-width 32 --verilator verilator-modern \
  --out build/first_address/reference_numeric32
python3 build/first_address/reference_runtime/test/linear_dma_context/run.py \
  --fpga --bus-width 64 --verilator verilator-modern \
  --out build/first_address/reference_numeric64

python3 test/dma_read_length/prepare_measurement.py --reference 38f32d93 \
  --out build/first_address/inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/first_address/inputs/cases.json \
  --cases reference current --out build/first_address/synthesis \
  --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
python3 test/dma_parallel_length/measure_paths.py \
  --reference build/first_address/synthesis/reference \
  --current build/first_address/synthesis/current \
  --out build/first_address/native_paths.json

for name in reference current; do
  python3 scripts/fpga/remap_fpga_luts.py \
    --source build/first_address/synthesis/$name \
    --out build/first_address/cost/$name --mode physical-cost \
    --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
  ln -sfn ../../synthesis/$name/pre_lut.il build/first_address/cost/$name/pre_lut.il
done
python3 test/dma_parallel_length/measure_paths.py \
  --reference build/first_address/cost/reference \
  --current build/first_address/cost/current \
  --out build/first_address/cost_paths.json
python3 test/dma_first_address/collect_report.py --results build/first_address
```
