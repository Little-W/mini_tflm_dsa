# DMA 返回就绪、错误与客户端授予

## 当前实现

`conv_axi_read_mux` 的 FPGA 实现使用一个查找表，根据当前模式、事务所有者、活动状态和两路客户端就绪信号生成返回就绪输出。每个就绪输入到输出只有一级组合逻辑。

`axi_block_dma_arbiter` 使用三个双输出查找表产生五个普通读取客户端的授予信号。请求方译码、命令寄存器占用和中止条件在同一级完成。量化客户端参数继续控制对应授予输出。

总线错误输出将写响应错误与读写完成错误提前合并，随后使用读取有效、读取就绪、返回错误码和其他错误条件完成最后一级判断。读取就绪到总线错误输出只有一级组合逻辑。

接口、状态寄存器、复位方式、请求优先级、窗口仲裁和所有接收边沿保持逐周期一致。通用实现保留相同布尔关系。

## 测量范围与结果

参考提交为 `47e51eff9831b42a36326cec6e074245ba0805d2`。联合综合使用生产读取保护器、读取复用器、SoC 两项 R/B 返回缓冲，以及从生产源码提取的模式寄存器、仲裁器授予和错误表达式、顶层故障表达式与 `kernel_request_idle`。返回载荷顺序直接取自 `soc_axi_pingpong_buffer`，为 `{rdata,rresp,rlast}`。

上下文计数、已登记请求方、命令寄存器状态和完成条件作为组合分析边界。路径分析只在网表副本添加端点，资源统计使用原始映射网表。该模型保留参考提交中的顶层故障表达式；整机集成后的顶层实现由对应整机结果说明。

| 测量项 | 参考版本 | 当前实现 |
| --- | ---: | ---: |
| 原生映射逻辑 LUT 原语 | 988 | 970 |
| `physical-cost` 逻辑 LUT 原语 | 922 | 923 |
| 触发器 | 545 | 545 |
| 上下文计数至返回就绪 | 3 级 | 3 级 |
| 上下文计数至总线错误 | 6 级 | 4 级 |
| 上下文计数至五个客户端授予 | 10 级 | 8 级 |
| 上下文计数至 `kernel_idle` | 11 级 | 9 级 |
| 返回就绪至总线错误 | 3 级 | 1 级 |
| 中止输入至五个客户端授予 | 3 级 | 1 级 |
| 联合模块内部寄存器间最长路径 | 11 级 | 12 级 |

路径表采用 `physical-cost` 配置：目标延迟 6667 ps、连线延迟 300 ps、最大八输入 LUT，ABC9 组合等价检查通过。最长内部路径为读取保护器地址寄存器至状态寄存器。BREADY、DMA 完成和错误、命令状态及 `abort_pending` 至各客户端授予和 `kernel_idle` 的已检查路径均未增加组合级数。

上述 LUT 数量是联合模块的逻辑原语计数。物理 LUT 位置数与 150 MHz 时序由整机布局布线结果确定。

## 功能验证

完整仲裁器状态和全部 DMA 实例端口通过七组比较，共 15147 位，覆盖 FPGA BUS32、BUS64、BUS128 与量化客户端开关的六种组合，以及 ASIC BUS64。DMA 输出与外部请求均为无约束输入。

真实读取保护器和复用器通过四组完整状态及公开输出比较，共 3229 位，覆盖通用和 FPGA 实现的 BUS32、BUS64。地址、数据、响应、模式、配置和复位输入均未添加取值限制。

完整 FPGA DMA 的 BUS32、BUS64 各通过 21 个场景和 905 次检查，包括每组 15 次描述符取消、5 次同时释放、5 次授予撤销和 8 次四个上下文占满检查。连续命令最小接收间隔保持两个周期，数值程序同时启用未定义行为检查。

当前实现与参考版本的窗口 DMA 均完成 422 次接收、418 次完成、4 次复位取消、4457 个返回元素与 19 次错误处理。1545 行连续返回周期记录逐项相同。

`measurement.json` 保存受测源码、生产表达式提取结果、映射输入、综合网表、路径和验证记录的 SHA-256。`collect_report.py` 核对这些记录和当前源码后生成报告。

## 复现命令

```sh
python3 test/dma_return_admission/run_arbiter_formal.py \
  --reference-rev 47e51eff --out build/dma_return_admission/arbiter_formal
python3 test/dma_read_permission/run_formal.py \
  --reference 47e51eff --out build/dma_return_admission/read_pair_formal
python3 test/dma_read_permission/run_numeric.py --verilator verilator-modern \
  --out build/dma_return_admission/numeric
python3 test/window_dma/run.py --fpga --jobs 1 --reference-ref 47e51eff \
  --verilator verilator-modern --out build/dma_return_admission/window_numeric

python3 test/dma_return_admission/prepare_measurement.py \
  --reference 47e51eff --out build/dma_return_admission/joint_inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/dma_return_admission/joint_inputs/cases.json \
  --cases reference current --out build/dma_return_admission/joint_synthesis
for version in reference current; do
  python3 scripts/fpga/remap_fpga_luts.py \
    --source build/dma_return_admission/joint_synthesis/${version} \
    --out build/dma_return_admission/joint_cost/${version} \
    --mode physical-cost --delay-target-ps 6667 --wire-delay-ps 300 --max-lut-inputs 8
  for mapping in joint_synthesis joint_cost; do
    python3 test/dma_return_admission/measure_paths.py \
      --mapped build/dma_return_admission/${mapping}/${version}/mapped.json \
      --pre-lut build/dma_return_admission/joint_synthesis/${version}/pre_lut.il \
      --out build/dma_return_admission/${mapping}/${version}/return_paths.json
  done
done
python3 test/dma_return_admission/collect_report.py
```
