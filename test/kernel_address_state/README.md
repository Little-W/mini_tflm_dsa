# 权重加载器地址与遍历状态

`kernel_loader_ctrl` 同步保存当前行起点、当前分块的完整 DMA 地址、列位置以及行列尾资格。配置、行列前进和分组切换使用既有接收事件更新这些状态，描述符坐标与预取比较直接读取已保存的值。地址和列位置满足以下模宽关系：

```text
row_base_address_q = group_base_addr + row_addr_offset
dma_address_q = group_base_addr + row_addr_offset + col_addr_offset
column_position_q = group_base_col + load_col_in_group
```

地址按 `REG_WIDTH` 位处理，列位置按 `COUNT_WIDTH` 位处理。行列尾资格与索引在同一边沿更新；相邻分组的边界比较并行处理正常递增与模宽回绕。配置取整将完整分块数和余数分别处理，零计数及回绕后的零值统一映射为一个分块。有效尾部行列数在选择前完成零值归一化。

描述符坐标与分组地址采用高低半段并行求和，综合器根据 RTL 算术推断器件资源。输入含未知值或高阻值时，公开地址和比较结果保留原有四态运算语义。模块端口、存储容量和请求接收周期保持一致。

## 验证

| 检查 | 范围 | 结果 |
| --- | --- | --- |
| 控制器完整状态与输出 | `SIZE=4, COUNT_WIDTH=8`；`SIZE=16, COUNT_WIDTH=29` | 两组均通过深度为 2 的时序归纳 |
| 地址比较组合证明 | 8、32、64 位，全部输入组合 | 通过 |
| 完整加载器逐周期比较 | 29,439 个工作周期、全部 23 个公开输出端口 | 通过 |
| 权重数值与预取事务 | 285 个分块、72,960 个数值、312 条 DMA 事务 | 通过 |
| 完整加载器四态比较 | `COUNT_WIDTH=16/29`，每组 20,004 个周期 | 通过 |

控制器证明使用实际模块，并增加纯组合观察量表示保存状态与参考算术的关系。证明同时检查共同公开信号、地址、列位置、行列尾资格和归约行数为正的状态关系。第一拍施加复位，之后所有外部输入自由变化。地址比较证明使用生产表达式和已经证明的保存地址关系。

四态测试覆盖配置字段、描述符坐标、未知值、高阻值与列计数回绕。注入任意列位置时，测试同时设置相应的列位置和列尾观察量，保持已经证明的状态关系。完整事务测试覆盖预取命中、请求重叠、尾部分块、配置切换和清空后的事务完成。

## FPGA 逻辑映射

测量参数为 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=29`。两份 RTL 使用相同的普通综合与物理成本 LUT 映射流程，目标周期为 6667 ps，连线估计为 300 ps，最多允许八输入 LUT 分解。

| 指标 | 检查点实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 3859 | 3620 |
| 触发器 | 2343 | 2374 |
| DSP48E1 | 2 | 6 |
| RAMB18E1 | 16 | 16 |
| 模块寄存器之间最长组合路径 | 12 级 | 10 级 |

资源减少 239 个逻辑 LUT。映射结果的连接图完整，LUT 映射功能检查通过。150 MHz 的器件时序结果需在目标器件完成布局布线后检查。源码摘要、验证结果和测量配置分别保存在 `validation.json` 与 `measurement.json`。

## 执行命令

```bash
python test/kernel_address_state/run_formal.py --out build/kernel_address_state/formal
python test/kernel_address_state/run_compare.py --out build/kernel_address_state/comparison
python test/kernel_prefetch/run_reference_comparison.py --reference 8b3728c0 --bus-width 64 --count-width 29 --out build/kernel_address_state/cycles --verilator verilator
python test/kernel_prefetch/run_loader_four_state.py --reference 8b3728c0 --count-width 29 --cycles 20000 --out build/kernel_address_state/four_state_29
python test/kernel_prefetch/run_loader_four_state.py --reference 8b3728c0 --count-width 16 --cycles 20000 --out build/kernel_address_state/four_state_16
```
