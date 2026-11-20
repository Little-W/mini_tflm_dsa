# 帧地址并行进位

`frame_address_prepare` 使用普通 RTL 描述八位分组加法。每组独立产生和传播进位，组间进位并行归并。共享基址加法与配置取整均保留完整三十二位结果、回绕和输出进位。

单元仍按原有十个周期计算三个地址。输入接收、运行中请求、中止、复位和结果等待行为相同。

## 测量

完整单元采用相同 `synth_xilinx` 与 ABC9 设置。LUT1 至 LUT6 的面积权重均为 1，最大 LUT 输入数为 6；源码通过算术运算推断逻辑。

| 项目 | 提交 `2297cb12` | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 420 | 483 |
| 触发器 | 505 | 505 |
| DSP48E1 | 1 | 1 |
| CARRY4 | 16 | 16 |
| 最大寄存器间组合级数 | 11 | 8 |

完整连通图满足该单元最大九级要求。整机资源和目标器件时序通过完整 SoC 的对应报告检查。

## 验证

`run_formal.py` 比较参考与当前单元的全部对应状态和公开输出，包含九组分块尺寸及中止屏蔽参数。启动、配置、复位、中止和结果接收输入均不受约束。

`test/frame_address/run_formal.py` 另以官方 DSP 模型证明通用与 FPGA 实现的 967 位状态和输出，并检查完整模地址运算。测试生成的实例显式连接全部二十六个端口。

数值测试分别运行中止屏蔽参数 0、1，以及实际综合网表。每次运行检查 36,746 个完整地址事务、4,286 次中止、1,512 次运行中复位及 185,328 个结果等待周期，共 672,662 周期。十个计算阶段及结果等待阶段均包含复位与中止。

源码摘要、形式证明、综合和三个数值运行结果保存在 [measurement.json](measurement.json)。

```sh
python3 test/frame_address_depth/run_formal.py --out build/frame_depth/formal
python3 test/frame_address/run_formal.py --out build/frame_depth/primitive
python3 test/frame_address_depth/prepare_measurement.py --out build/frame_depth/inputs
python3 scripts/fpga/open_fpga_synth.py --case-config build/frame_depth/inputs/cases.json \
  --cases reference candidate --through pre_lut --out build/frame_depth/pre
python3 scripts/fpga/remap_fpga_luts.py --source build/frame_depth/pre/reference \
  --out build/frame_depth/mapped/reference --mode physical-cost --max-lut-inputs 6 \
  --small-lut-area-cost 1 --wire-delay-ps 500 --delay-target-ps 6667
python3 scripts/fpga/remap_fpga_luts.py --source build/frame_depth/pre/candidate \
  --out build/frame_depth/mapped/candidate --mode physical-cost --max-lut-inputs 6 \
  --small-lut-area-cost 1 --wire-delay-ps 500 --delay-target-ps 6667
python3 test/frame_address/run.py --out build/frame_depth/numeric --verilator verilator-modern --jobs 1
python3 test/frame_address/run.py --out build/frame_depth/numeric_unmasked \
  --verilator verilator-modern --jobs 1 --ready-mask-abort 0
python3 test/frame_address/run.py --out build/frame_depth/numeric_mapped \
  --verilator verilator-modern --jobs 1 --mapped build/frame_depth/mapped/candidate/mapped.v
python3 test/frame_address/check_structure.py --mapped build/frame_depth/mapped/candidate/mapped.json \
  --out build/frame_depth/structure.json
```
