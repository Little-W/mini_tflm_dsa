# DMA 读取许可路径

## 当前实现

`conv_axi_read_guard.o_arb_arvalid` 表示保护模式下处于 `FAST_AR` 或 `WORD_AR` 的待发请求。该输出由模式和状态直接生成，等价于 `enable && m_arvalid`。它供 `axi_dual_block_dma` 中的读取请求复用器使用。

`axi_dual_block_dma` 在保护模式下采用复用器输出的地址有效信号，在直通模式下采用读取保护器的完整地址有效信号。格式、地址范围和跨页检查仍由读取保护器完成。模式寄存器、地址载荷、反压处理、请求接受边沿、复用器轮转优先级及所有事务状态保持逐周期一致。

## 联合综合结果

联合输入从生产 `axi_dual_block_dma` 提取实际模式寄存器、读取保护器实例、读取复用器实例和连接表达式。参数为 32 位地址、64 位数据及四个读取在途事务，保留全部 AXI 端口。参考提交为 `dcef8d89`。

映射使用与完整 SoC 相同的 `physical-cost` 配置：目标延迟 6667 ps、连线延迟 300 ps、最大八输入 LUT。ABC9 的组合等价检查通过。

| 测量项 | 参考版本 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT 原语 | 857 | 855 |
| 触发器 | 399 | 399 |
| DSP48E1 | 0 | 0 |
| RAMB36E1 / RAMB18E1 | 0 / 0 | 0 / 0 |
| 内部寄存器间最长组合路径 | 12 级 | 11 级 |
| `linear_araddr` 至 `linear_arready` | 8 级 | 4 级 |
| `linear_arlen` 至 `linear_arready` | 8 级 | 4 级 |
| `linear_araddr` 至 `m_axi_arvalid` | 7 级 | 4 级 |
| `linear_arlen` 至 `m_axi_arvalid` | 7 级 | 4 级 |
| `linear_araddr`、`linear_arlen` 至 `fe_arready` | 7 级 | 无组合连接 |
| 任务模式至 `linear_arready` | 6 级 | 4 级 |
| 任务模式至 `fe_arready` | 5 级 | 3 级 |
| 任意内部寄存器至 `linear_arready` | 6 级 | 5 级 |

同时检查了两路返回就绪、前端地址有效、外部地址就绪、外部返回有效和最后一个返回数据拍对读取许可与错误接收的影响，这些路径均未增加组合级数。端口路径使用网表分析副本中的端点，资源统计取原始网表。本表记录联合模块映射结果，完整 SoC 路径由整机综合报告给出。

## 功能检查

真实读取保护器与复用器在 BUS32、BUS64 下分别完成通用实现和 FPGA 实现的完整状态及公开输出等价比较，共 3221 位。复位、配置、模式、请求、地址、返回数据、错误码和反压输入均未增加取值限制。脚本还检查双路 DMA 在所测连接之外的代码与参考版本完全相同。

独立读取保护器通过七组参数的完整状态与输出比较，共 6828 位，覆盖两种跨页拆分设置，地址宽度 16、32、33、40 位及数据宽度 16、32、64、128、256 位。新增仲裁输出一并与参考表达式 `enable && m_arvalid` 比较。

FPGA 读取保护器的四组配置各完成 50000 个周期的数值比较。完整 DMA 的 BUS32、BUS64 回归各通过 21 个场景和 905 次检查，覆盖 15 次描述符取消、5 次同时释放、5 次授予撤销和四个上下文占满的情况，连续命令最小接收间隔保持两个周期。

完整窗口 DMA 在当前实现与参考版本分别通过 422 次接收、418 次完成、4 次复位取消、4457 个返回元素及 19 次错误处理。连续命中周期记录逐项相同。检查包括普通请求与窗口请求并发、授予撤销、配置接收、随机坐标、输出反压、错误排空、边界条件和运行中复位。

`measurement.json` 保存源码、输入快照、综合网表、形式检查、数值检查及周期记录的 SHA-256。

## 复现命令

```sh
python3 test/dma_read_permission/run_formal.py \
  --reference dcef8d89 --out build/dma_read_permission/formal
python3 test/dma_read_permission/run_guard_formal.py \
  --reference-ref dcef8d89 --fpga --out build/dma_read_permission/guard_formal
python3 test/conv_guard/compare.py --reference-ref dcef8d89 --fpga \
  --verilator verilator-modern --out build/dma_read_permission/guard_numeric
python3 test/dma_read_permission/run_numeric.py \
  --verilator verilator-modern --out build/dma_read_permission/dma_numeric
python3 test/window_dma/run.py --fpga --jobs 1 --reference-ref dcef8d89 \
  --verilator verilator-modern --out build/dma_read_permission/window_numeric

python3 test/dma_read_permission/prepare_measurement.py \
  --reference dcef8d89 --out build/dma_read_permission/inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/dma_read_permission/inputs/cases.json \
  --cases reference current --out build/dma_read_permission/synthesis
for version in reference current; do
  python3 scripts/fpga/remap_fpga_luts.py \
    --source build/dma_read_permission/synthesis/${version} \
    --out build/dma_read_permission/cost/${version} \
    --mode physical-cost --delay-target-ps 6667 --wire-delay-ps 300 --max-lut-inputs 8
  python3 test/dma_read_permission/measure_paths.py \
    --mapped build/dma_read_permission/cost/${version}/mapped.json \
    --pre-lut build/dma_read_permission/synthesis/${version}/pre_lut.il \
    --out build/dma_read_permission/cost/${version}/permission_paths.json
done
```
