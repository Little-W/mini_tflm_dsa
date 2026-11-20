# 权重加载请求与预取空闲选择

`kernel_loader` 使用 `load_weight_req && load_weight_granted` 产生实际 DMA 启动。请求信号已包含普通模式和受管预取模式的完整接收条件，以及清空、缓冲容量和在途状态的限制。后台空闲条件提前独立计算，并与同周期启动一起生成 `prefetch_idle`。

FPGA 实现使用一个 `LUT6_2` 同时生成启动与空闲输出，使晚到的授予信号至两个输出均只经过一个 LUT。通用实现使用相同的布尔表达式。寄存状态、存储容量、预取比较、命中处理、清空和公开周期保持一致。

## 完整加载器测量

比较提交为 `8bd4b00b`，参数为 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`REG_WIDTH=32`、`COUNT_WIDTH=29`。两个版本均综合完整加载器、控制器、缓冲器及其实际存储。

| 项目 | 参考版本 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT 原语 | 4,492 | 4,482 |
| 分布式存储 LUT | 384 | 384 |
| 触发器 | 2,779 | 2,779 |
| DSP48E1 | 0 | 0 |
| 最长寄存器间组合路径 | 14 级 | 14 级 |
| 授予输入至 `prefetch_idle` | 4 级 | 1 级 |
| 授予输入至 `ext_dma_start` | 3 级 | 1 级 |
| 内部寄存器至 `prefetch_idle` | 8 级 | 8 级 |
| 内部寄存器至 `ext_dma_start` | 7 级 | 8 级 |

端口路径在原始综合网表中增加分析起止点，资源统计取自未添加分析节点的网表。完整 SoC 的物理资源和跨模块路径由对应整机测量给出。

## 验证

接收与空闲选择的三位任意输入在通用实现和官方 `LUT6_2` 模型下均通过形式证明。完整实际加载器完成四组状态及输出等价检查，共 60,741 位：

| SIZE | COUNT_WIDTH | BUS_WIDTH | 实现 | 比较位数 |
| ---: | ---: | ---: | --- | ---: |
| 4 | 8 | 32 | 通用 | 4,542 |
| 16 | 32 | 64 | 通用 | 18,665 |
| 16 | 29 | 32 | FPGA | 18,725 |
| 16 | 29 | 64 | FPGA | 18,809 |

检查保留实际控制器、两逻辑槽位缓冲器和存储状态，外部输入未增加取值限制。FPGA 模型内部真值表选择的组合中间线使用私有名称，实际寄存状态、存储内容与公开输出均参与等价比较。

实际 FPGA 数值测试使用完整权重 RAM、独立 DMA 模型和 C++ 未定义行为检查：

| 总线 | 周期 | 输出分块 | 数值比较 | DMA 启动 | 预取命中 |
| --- | ---: | ---: | ---: | ---: | ---: |
| BUS32 | 45,050 | 285 | 72,960 | 319 | 66 |
| BUS64 | 29,443 | 285 | 72,960 | 312 | 73 |

测试覆盖 INT8/INT16、im2col、尾部分块、普通模式、受管预取、已完成与在途命中、预测不匹配、比较输入改变、清空和两个 DMA 上下文重叠。源码摘要、形式结果、数值结果和实际映射摘要保存在 `measurement.json`。

## 运行

```sh
python3 test/kernel_request_idle/run_formal.py \
  --reference 8bd4b00b --out build/kernel_request_idle/formal
python3 test/kernel_prefetch/run.py --fpga --bus-width 32 --count-width 29 \
  --verilator verilator-modern --out build/kernel_request_idle/bus32
python3 test/kernel_prefetch/run.py --fpga --bus-width 64 --count-width 29 \
  --verilator verilator-modern --out build/kernel_request_idle/bus64

python3 test/kernel_candidate_fields/prepare_measurement.py \
  --reference-rev 8bd4b00b --out build/kernel_request_idle/inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/kernel_request_idle/inputs/cases.json \
  --cases loader_reference loader_current --out build/kernel_request_idle/synthesis
python3 test/kernel_request_idle/measure_paths.py \
  --synthesis build/kernel_request_idle/synthesis --out build/kernel_request_idle/paths.json
```

形式脚本可使用 `--resume` 读取同一份源码、原语模型和证明命令的已完成结果，继续执行尚未完成的配置。
