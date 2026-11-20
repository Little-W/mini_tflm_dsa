# 权重描述符的并行比较与配置计算

权重加载器在原有周期内完成地址比较、尾部分块判断和配置计算。生产配置为 `SIZE=16`、`DATA_WIDTH=16`、`BUS_WIDTH=64`、`REG_WIDTH=32`、`COUNT_WIDTH=29`，参考提交为 `7598ae9`。

## 硬件结构

`add3_equal` 把三个操作数压缩成两个操作数，再调用 `add_equal` 并行检查各位进位与目标和值。最高进位显式连接到 `unused_final_carry`，比较结果保留参数指定的模加法位宽。模块使用组合逻辑。

控制器导出已有的列组起点、组内列偏移，以及地址的分组基址、行偏移和列偏移。描述符比较直接使用这些寄存操作数。`PF_EMPTY` 状态比较新预取候选，其余状态比较已经保存的预取描述符；相应的消费条件选择同一个比较结果。

列号截断后的左移宽度覆盖地址宽度时，列组起点、组内偏移和配置基址可直接作为三个操作数。其他参数配置保留列号截断后的表达式。行坐标采用二项加法等式。尾部分块判断分别比较 `load_tile_row + 1` 与总行数，以及 `group_base_col + load_col_in_group + 1` 与总列数，运算均保留 `CNT_W` 位。

配置采用已有状态：`S_IDLE` 保存列步长和复用次数，`S_INIT` 计算并保存分组步长，`S_RUN` 使用该值更新分组地址。DMA 启动、预取命中、缓冲区输出、复位和清空保持原有公开周期。

## 生产配置综合

两个版本使用相同的 Yosys、Xilinx 原语模型与映射设置，比较完整 `kernel_loader`。

| 指标 | 参考提交 | 并行比较与分阶段配置 |
| --- | ---: | ---: |
| 逻辑 LUT | 7,528 | 7,607 |
| 触发器 | 2,786 | 2,786 |
| 分布式 RAM 的名义 LUT 位置 | 384 | 384 |
| CARRY4 | 324 | 304 |
| DSP / RAMB36 / RAMB18 | 0 / 0 / 0 | 0 / 0 / 0 |
| 最长寄存器间组合单元数 | 22 | 15 |
| 寄存器至 `ext_dma_start` | 16 | 5 |
| 寄存器至 `load_weight_req` | 5 | 5 |
| 寄存器至 `ext_dma_p0` | 17 | 12 |
| 寄存器至 `ext_dma_q0` | 17 | 10 |
| 寄存器至 `ext_dma_base_addr` | 17 | 12 |
| `group_base_col` 至寄存器 | 20 | 14 |
| `col_addr_offset` 至寄存器 | 22 | 12 |

逻辑 LUT 增加 79 个，触发器和存储资源保持一致。上述路径按综合网表中实际连接的组合单元统计；目标器件频率由布局布线的延迟报告确定。

## 形式与数值检查

三项模加法等式覆盖宽度 1、4、16、32、64 的全部输入取值。完整加载器比较覆盖 SIZE4/COUNT8/BUS32、SIZE16/COUNT16/BUS32 和 SIZE16/COUNT29/BUS64，共 38,506 个运行状态和输出等价位。独立控制器另覆盖 SIZE4/COUNT8、SIZE8/COUNT16、SIZE16/COUNT29 和 SIZE16/COUNT32。

形式比较在两个设计中均增加运行阶段的步长观察点。分组步长只在 `S_RUN` 的更新分支消费，因此在该分支使用带相同状态条件的步长，与原表达式对全部输入等价。该观察点用于比较初始化阶段之后实际消费的值，保留原有配置状态转换与输入自由度。

| 数值检查配置 | 检查周期 | 输出分块 | 数值比较 | DMA 启动 |
| --- | ---: | ---: | ---: | ---: |
| BUS32，COUNT16 | 42,035 | 270 | 69,120 | 304 |
| BUS64，COUNT29 | 27,456 | 270 | 69,120 | 297 |

数值检查覆盖 INT8/INT16、im2col、尾部分块、已缓存命中、在途命中、预取不匹配、延迟预测、清空与事务重叠。两种配置均启用 C++ 未定义行为检查。详细源码、仿真程序、形式结果和网表摘要保存在 [measurement.json](measurement.json)。

## 运行

```sh
python3 test/kernel_descriptor_timing/run_formal.py --out build/kernel_formal
python3 test/kernel_prefetch/run_control_formal.py \
  --reference 7598ae9 --profiles 4:8 8:16 16:29 16:32 --out build/kernel_control_formal
python3 test/kernel_prefetch/run.py \
  --out build/kernel_prefetch64 --bus-width 64 --count-width 29 --verilator verilator-modern
python3 test/kernel_prefetch/run.py \
  --out build/kernel_prefetch32 --bus-width 32 --count-width 16 --verilator verilator-modern
python3 test/kernel_descriptor_timing/prepare_measurement.py --out build/kernel_inputs
python3 scripts/fpga/open_fpga_synth.py --source-root . \
  --case-config build/kernel_inputs/cases.json --cases loader_reference loader_current \
  --out build/kernel_synthesis --lock-file build/synth-small.lock
python3 test/kernel_descriptor_timing/measure_paths.py \
  --synthesis build/kernel_synthesis --out build/kernel_paths.json
```
