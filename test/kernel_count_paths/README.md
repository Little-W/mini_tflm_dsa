# 权重任务计数与完成比较

`kernel_loader_ctrl` 保留三个遍历维度的完整计数范围。生产配置的 `COUNT_WIDTH=29` 对应 87 位已发出、已加载和已发送计数器，控制状态、描述符输出和预取周期保持一致。

计数递增按六位划分。各段并行计算全一条件，每六段再合并为一组，较高段使用完整低组和组内剩余段的全一结果生成进位。每段只执行本段宽度的加法。

FPGA 比较器按四十七位划分无符号操作数，每段先补零扩展至四十八位，再由 `DSP48E1` 计算差值。差值符号提供大小关系，`PATTERNDETECT` 提供相等关系；平衡树按高位优先顺序合并各段。三个 87 位比较器共使用六个组合 DSP。通用 RTL 分支保留分段比较表达式。

## 独立控制器资源

配置为 `SIZE=16`、`REG_WIDTH=32`、`COUNT_WIDTH=29`，参考提交为 `2f06471c`。使用相同的 Yosys、ABC9 和 Artix-7 原语模型；本表未启用额外宽算术 DSP 分配。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 1,766 | 1,514 |
| 触发器 | 819 | 819 |
| DSP48E1 | 0 | 6 |
| CARRY4 | 228 | 216 |
| 最长寄存器间组合单元数 | 15 | 14 |

以上 LUT 数表示综合逻辑单元；完整 SoC 的面积使用合法布局后的物理 LUT 位置统计。完整 SoC 的 DSP 分配总数仍受器件预算约束。

## 完整加载器资源

完整 `kernel_loader` 使用同一计数参数、16 位权重与 64 位总线。该模块保留权重存储和全部预取控制。

| 项目 | 参考实现 | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 7,607 | 7,860 |
| 分布式 RAM LUT | 384 | 384 |
| 触发器 | 2,786 | 2,786 |
| DSP48E1 | 0 | 6 |
| 最长寄存器间组合单元数 | 15 | 14 |

完整模块的逻辑映射选择与独立控制器不同。本实现缩短计数控制路径，完整 SoC 的面积变化由固定整合提交单独测量。

## 功能检查

使用官方 DSP 和 LUT 功能模型，对 `SIZE/COUNT_WIDTH` 为 `4/8`、`8/16`、`16/29`、`16/32` 的四种配置完成状态与输出等价证明，共覆盖 12,765 位，输入不附加取值限制。

完整加载器使用实际 FPGA 分支完成两种总线宽度的数值测试。每种配置检查 270 块权重及 69,120 个数值，包括预取命中、在途命中、请求等待、错误匹配、延迟预测、清空、尾部块和随机任务。32 位总线运行 42,035 个周期，64 位总线运行 27,456 个周期，均启用 C++ 未定义行为检查。

源码、原语库、仿真程序和报告的 SHA-256 摘要保存在 `measurement.json`。

## 运行方法

```sh
python3 test/kernel_prefetch/run_control_formal.py \
  --reference 2f06471c --fpga --profiles 4:8 8:16 16:29 16:32 \
  --out build/kernel_count_paths/formal
python3 test/kernel_prefetch/run.py --verilator verilator-modern --fpga \
  --bus-width 32 --count-width 29 --out build/kernel_count_paths/sim32
python3 test/kernel_prefetch/run.py --verilator verilator-modern --fpga \
  --bus-width 64 --count-width 29 --out build/kernel_count_paths/sim64
python3 test/kernel_count_paths/prepare_measurement.py \
  --reference 2f06471c --out build/kernel_count_paths/sources
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/kernel_count_paths/sources/cases.json \
  --cases controller_reference controller_current loader_reference loader_current \
  --out build/kernel_count_paths/synthesis
```
