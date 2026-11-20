# 权重候选字段比较与突发长度选择

`kernel_loader` 使用平衡组合比较检查预取候选字段是否保持稳定，并在选择传输描述符之前编码突发长度。所有寄存器、请求接受边沿、权重装载条件、缓存命中、丢弃和输出周期均保持相同。

## 组合结构

`kernel_candidate_equal` 每三个对应位组成一个相等比较叶节点，再通过六路组合树归并。生产 160 位候选字段包含 54 个叶节点，归并节点数依次为 9、2、1，共四级 LUT。FPGA 分支使用显式 `LUT6`，通用 RTL 分支使用相同分组关系。

`kernel_burst_encode` 分别为控制器描述符、预取描述符和活动描述符生成八位突发长度。传输状态随后只选择编码结果。列数、精度和打包标志的运算与描述符选择并行执行。

在每拍元素数为二的幂且寄存器宽度足够时，非零列数使用以下关系编码低八位：

`burst_len_m1 = ((columns - 1) >> log2(elements_per_beat)) mod 256`

零列数和打包传输分别按各自定义编码。较窄寄存器和其他总线宽度使用完整定宽取整表达式，保持溢出和截断行为。

## 资源与组合路径

完整加载器参数为 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`REG_WIDTH=32`、`COUNT_WIDTH=29`。参考源码为 `7254ced6`。

| 完整模块指标 | 参考实现 | 分组比较与提前编码 |
| --- | ---: | ---: |
| 逻辑 LUT | 4,662 | 4,492 |
| RAM LUT | 384 | 384 |
| FF | 2,779 | 2,779 |
| DSP48E1 | 0 | 0 |
| 最长寄存器组合路径 | 15 | 14 |

此表使用原生模块综合。全 SoC 的宽运算 DSP 映射和物理 LUT 合并另由生产整机测量确定。

从 `candidate_fields_q` 到公开输出的实际组合路径如下。分析在公开输出处增加仅用于统计的寄存器终点，不修改生产网表。

| 输出 | 参考级数 | 当前级数 |
| --- | ---: | ---: |
| `ext_dma_burst_len_m1` | 14 | 10 |
| `ext_dma_base_addr` | 9 | 8 |
| `ext_dma_start` | 7 | 7 |
| `prefetch_idle` | 8 | 8 |

全部映射单元均已分类。器件时序分析继续使用完整器件和布线延迟模型。

## 验证结果

完整加载器在任意输入下完成全部匹配状态和信号的等价证明，参数组合如下。

| SIZE | COUNT_WIDTH | BUS_WIDTH | 已证明位数 |
| ---: | ---: | ---: | ---: |
| 4 | 8 | 32 | 4,394 |
| 16 | 16 | 32 | 17,867 |
| 16 | 29 | 64 | 18,416 |
| 16 | 29 | 128 | 18,591 |

相等比较另外完成 18 组证明，覆盖 1、2、3、4、5、31、32、160、320 位输入，每种宽度均检查通用 RTL 和 Yosys Xilinx `LUT6` 功能模型。突发长度完成 14 组任意输入证明，覆盖窄寄存器、32/64 位寄存器、32/64/128 位总线及其他每拍元素数量。

BUS64 的完整加载器事务测试使用 Xilinx 原语功能模型并开启 UBSan，通过 29,443 个周期、312 次 DMA、285 个 tile 和 72,960 个权重数值检查。其中包括 S8/S16、im2col、尾部 tile、两项 DMA 上下文重叠、命中、丢弃、候选字段变化及清空恢复。

`measurement.json` 保存源码摘要、数值检查、形式结果、综合资源和具体路径。

## 运行命令

```sh
python3 test/kernel_candidate_fields/run_formal.py \
  --reference-rev 7254ced6 --out build/kernel_candidate_fields/formal

python3 test/kernel_prefetch/run.py \
  --out build/kernel_candidate_fields/prefetch64 \
  --verilator verilator-modern --bus-width 64 --fpga

python3 test/kernel_candidate_fields/prepare_measurement.py \
  --reference-rev 7254ced6 --out build/kernel_candidate_fields/inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/kernel_candidate_fields/inputs/cases.json \
  --cases loader_reference loader_current \
  --out build/kernel_candidate_fields/synthesis \
  --lock-file /tmp/mini_tflm_dsa_synthesis.lock
python3 test/kernel_candidate_fields/measure_paths.py \
  --synthesis build/kernel_candidate_fields/synthesis \
  --out build/kernel_candidate_fields/paths.json
```
