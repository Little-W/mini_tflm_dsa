# 权重描述符比较准备

`kernel_loader` 在时钟边沿保存描述符比较结果、五个候选字段和比较来源。`kernel_loader_ctrl.o_descriptor_update` 标记配置接收、初始化和请求接受时对描述符的更新。配置更新、预取保存、缓存命中和丢弃操作均使上一周期比较结果失效。

`comparison_ready` 同时检查结果有效标志、比较来源以及空闲状态下候选字段是否保持一致。缓存命中、失配丢弃和预取保存只使用有效的登记结果。候选正在等待比较时，`prefetch_idle` 保持为低；输入稳定并完成采样后，控制器继续处理该候选。普通线性加载、缓冲容量和所有描述符字段的位宽保持完整。

## 资源与组合路径

比较对象采用 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`REG_WIDTH=32`、`COUNT_WIDTH=29`。参考源码为 `3a773d18`，复用的已完成综合结果与该版本三个加载器源码文件的 SHA-256 一致。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 4,798 | 4,764 |
| 分布式 RAM 占用的 LUT 位置 | 384 | 384 |
| 触发器 | 2,786 | 2,949 |
| DSP48E1 | 6 | 6 |
| 完整加载器寄存器之间最长组合级数 | 15 | 15 |
| 寄存器至 `prefetch_idle` 输出边界 | 13 | 8 |
| 寄存器至 `load_weight_req` 输出边界 | 6 | 5 |
| 寄存器至 `ext_dma_start` 输出边界 | 10 | 7 |

输出边界分析使用已映射网表的实际单元连接，在分析图中把模块输出视作接收寄存器的输入。参考实现的 `prefetch_idle` 最长路径起于 `prefetch_state[1]`，当前实现起于已保存的候选字段。物理 LUT 数量及 150 MHz 时序由完整 SoC 的布局和布线结果确定。

## 验证

形式检查覆盖 `COUNT_WIDTH=8/BUS32`、`COUNT_WIDTH=29/BUS32` 和 `COUNT_WIDTH=29/BUS64`。全部外部输入自由变化，比较函数的结果作为任意控制输入；计数状态、完成条件和遍历末端条件保留实际 RTL。归纳证明确认：

- `comparison_ready` 为真时，678 位真实比较输入与采样边沿的输入完全一致。比较结果和这些输入在同一边沿登记，纯组合比较函数因此给出相同结果。
- 新候选尚未完成比较时，`prefetch_idle` 必须为低。

BUS32 和 BUS64 事务测试使用真实加载器、缓冲区及 Xilinx LUT/DSP 功能模型，每种配置均完成 285 个数据块和 72,960 个数值检查。测试涵盖普通双槽位并发、受管预取、已完成及在途缓存命中、描述符失配、行列尾部、S8/S16、im2col、清空后恢复和随机等待。新增测试逐拍改变候选的五个字段，并覆盖准备期间撤回候选、清空、配置更新和复位。

| 测试配置 | 数据块 | 数值检查 | 完成周期 | DMA 接受与完成 | 缓存命中 |
|---|---:|---:|---:|---:|---:|
| BUS32 | 285 | 72,960 | 45,050 | 319 / 319 | 66 |
| BUS64 | 285 | 72,960 | 29,443 | 312 / 312 | 73 |

描述符改变后，缓存和预取判断等待一次稳定输入采样。测试检查输出数据、DMA 描述符、一次接受对应一次完成，以及全部已请求权重的发送完成。所有 C++ 翻译单元启用未定义行为检查。

## 运行

```sh
python3 test/kernel_compare_stage/run_formal.py --out build/kernel_compare_stage/formal
python3 test/kernel_prefetch/run.py --out build/kernel_compare_stage/bus32 --bus-width 32 --fpga
python3 test/kernel_prefetch/run.py --out build/kernel_compare_stage/bus64 --bus-width 64 --fpga
python3 test/kernel_count_paths/prepare_measurement.py \
  --out build/kernel_compare_stage/sources --reference 3a773d18
python3 scripts/fpga/open_fpga_synth.py \
  --out build/kernel_compare_stage/synthesis \
  --case-config build/kernel_compare_stage/sources/cases.json \
  --cases loader_reference loader_current
python3 test/kernel_compare_stage/measure_paths.py \
  --reference build/kernel_compare_stage/synthesis/loader_reference \
  --current build/kernel_compare_stage/synthesis/loader_current \
  --out build/kernel_compare_stage/paths.json
```

`measurement.json` 保存源码摘要、形式检查、事务结果、资源统计和实际输出路径。
