# 向量控制与分段算术

完整向量引擎保留原有状态、存储容量、数值范围和公开输出周期。量化输出偏移与归约相加使用四个八位段，各段的产生进位和传播进位并行生成输入进位。输出偏移仍保留完整六十四位回绕、符号判断和激活限幅。

向量分组结束比较把低位相加与高位关系并行计算。低位宽度为 `$clog2(TILE+1)`，高位条件同时覆盖普通递增和三十二位回绕。配置检查把图像尺寸、填充和末坐标反码压缩成两项，使用求和进位判断严格小于关系，并检查末坐标的高位。最近偶数舍入采用八个八位递增段，各段进位由所有更低位是否为一直接产生。

## 运行验证

在仓库根目录执行：

```sh
python3 test/vector_coordinate_bounds/run_formal.py --out build/vector_timing/coordinates
python3 test/vector_parallel_add/run_formal.py --out build/vector_timing/arithmetic
python3 test/vector_control_bounds/run_formal.py --out build/vector_timing/control
python3 test/vector_round_carry/run_formal.py --reference-ref 2f06471c --out build/vector_timing/rounding
python3 test/vector_acc_read/run.py --reference-rev 2f06471c --bus-width 64 --out build/vector_timing/full_state
python3 test/vector_engine/run.py --bus-width 64 --pes 8 --jobs 1 --xilinx --out build/vector_timing/bus64
python3 test/vector_engine/run.py --bus-width 32 --pes 8 --jobs 1 --xilinx --out build/vector_timing/bus32
python3 scripts/fpga/open_fpga_synth.py --cases vector_engine --out build/vector_timing/synthesis
```

局部算术证明覆盖全部输入编码。分组比较检查 `TILE=1、3、16、32、64`，完整配置检查覆盖 824 个等价位，舍入的组合版本和中间寄存版本分别覆盖 455 位和 523 位。完整状态比较核对 13,446 位寄存状态和 35 个公开输出，并检查共享标量乘法器的输入。

BUS32 和 BUS64 各通过 592 项完整向量任务，分别检查 168,491 和 169,361 个数值输出。全部任务的周期、访存和缓存统计与附件对应参照完全相同。仿真使用官方 Xilinx 原语功能模型。

## 独立综合结果

生产向量配置为 `TILE=16、PE_COUNT=8、BUS_WIDTH=64`。同一工具和原语模型得到以下结果：

| 项目 | 附件版本 `2f06471c` | 分段算术与控制 | 并入 DMA 地址共享 |
| --- | ---: | ---: | ---: |
| 逻辑 LUT | 11,743 | 12,054 | 11,805 |
| 分布式 RAM LUT | 248 | 248 | 248 |
| 触发器 | 5,976 | 5,976 | 5,976 |
| DSP48E1 | 16 | 16 | 16 |
| 最长寄存器间组合单元数 | 18 | 15 | 15 |

当前最长路径从 `position[0]` 到 `state[0]`，包含输出位置递增和结束条件。完整路径图没有组合环或未识别的单元类型。该结果记录结构深度；目标器件的 150 MHz 时钟由布局布线延迟报告检查。

`measurement.json` 保存分段算术与控制的源码摘要、路径、形式结果和 BUS32/64 功能统计。`combined_measurement.json` 保存并入 DMA 地址共享后的固定源码与完整综合结果；该组合重新完成附件至当前 13,446 位状态和 35 个公开输出的等价检查，以及五组读取译码与全部范围输出的组合证明。
