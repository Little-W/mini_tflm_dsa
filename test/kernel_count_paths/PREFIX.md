# 权重计数的分组进位

权重任务计数使用三倍 `COUNT_WIDTH` 的完整位宽。计数器每六位组成一个加法分组，最高一组保留剩余位数。最低组的输入进位恒为一，其余组各保存一个派生进位寄存位，表示当前计数中所有更低位是否全为一。

每次计数递增时，各组使用已保存的输入进位并行相加。下一周期的组间进位直接检查当前低位是否为 `11…110`。复位和新任务将计数及派生进位同时清零，暂停期间同时保持。该关系在任意次数的递增及完整模宽回绕后均成立，公开输出和任务周期保持一致。

生产配置的完整计数宽度为 87 位，增加 14 个进位寄存位。完整 `kernel_loader_ctrl` 使用相同参数、公共 RTL 和 xc7 综合选项的结果如下。

| 项目 | 参考提交 `44c0e5e3` | 当前实现 |
|---|---:|---:|
| 普通 LUT | 1,316 | 1,279 |
| 寄存器 | 649 | 663 |
| CARRY4 | 129 | 158 |
| 寄存器之间的最长组合路径 | 14 | 14 |

`SIZE:COUNT_WIDTH` 为 `4:8`、`8:16`、`16:29` 和 `16:32` 的完整控制器检查通过 8,760 个等价位。参考设计中同时观察每个派生进位对应的低位全一条件，全部公开输出、对应状态及派生进位均参加比较，输入不添加约束。实际 FPGA 分支的权重预取检查完成 285 个块、72,960 个数值及 29,443 个周期，覆盖预取、尾组、INT8、INT16 和同时加载与发送。

```sh
python3 test/kernel_prefetch/run_control_formal.py \
  --reference 44c0e5e3 --fpga --seq 2 \
  --profiles 4:8 8:16 16:29 16:32 --out /tmp/kernel_carry_formal
python3 test/kernel_count_paths/prepare_measurement.py \
  --reference 44c0e5e3 --out /tmp/kernel_carry_inputs
python3 scripts/fpga/open_fpga_synth.py \
  --case-config /tmp/kernel_carry_inputs/cases.json \
  --cases controller_reference controller_current --out /tmp/kernel_carry_synthesis
python3 test/kernel_prefetch/run.py \
  --fpga --verilator verilator-modern --out /tmp/kernel_carry_numeric
```

具体资源、配置、源码摘要和验证结果保存在 `registered_carry_measurement.json`。完整 SoC 的资源及跨模块路径由统一综合测量。
