# 预取坐标验证

本目录验证 `conv_im2col_prefetch` 的行边界条件、三十五位坐标求和和既有准备阶段中的进位保存。模块的请求接收、投影坐标输出和后续预取阶段保持原有周期。

## 当前计算方式

输入行宽为十六位。对于三十二位模加结果，先并行计算其高十六位在低位进位为零、为一时是否等于零。低十六位的行边界使用减法无借位与两个加法进位的异或关系。高位非零或低位达到行宽时，投影坐标执行跨行选择。

横向有符号坐标始终保持三十五位。准备阶段保存低十六位求和的进位，投影阶段分别计算低十六位和高十九位。高位加法直接使用保存的进位，完整和值继续参与负值裁剪和窗口选择。含 X/Z 的仿真输入使用完整表达式保持比较和算术的四态语义。

## 形式验证与四态仿真

```sh
python3 test/prefetch_coordinate/run.py --out build/prefetch_coordinate
```

`run.py` 从当前生产模块提取实际算术和选择表达式，并与 `prefetch_coordinate_reference.sv` 的完整坐标函数比较。五项形式检查覆盖八位及三十二位模加关系、任意两个三十五位输入的分段求和、全部坐标选择条件，以及配置接收和复位取消时的阶段保持关系。阶段检查使用十二拍展开与时序归纳。

四态仿真默认运行 40000 个向量，其中 20000 个含 X/Z。每个向量分别比较行边界、横坐标、纵坐标和完整三十五位和值，共 160000 次结果比较。输出目录保存提取模型、形式工具脚本、仿真程序、日志、源文件散列和 `summary.json`。

## 三个前端数值配置

下面三个命令使用独立卷积方程检查期望输出，同时检查配置、描述符、缓存请求和背压期间的接口行为。编译入口使用单个构建进程。

```sh
python3 test/frontend_pipeline/run_numeric.py --target asic --size 16 --lanes 8 --bus-width 64 --cache-sets 16 --cache-ways 2 --line-bytes 128 --narrow-mode 2 --windowed --prefetch --out build/prefetch_coordinate_numeric/lanes8
python3 test/frontend_pipeline/run_numeric.py --target asic --size 16 --lanes 16 --bus-width 64 --cache-sets 16 --cache-ways 2 --line-bytes 128 --narrow-mode 2 --windowed --prefetch --out build/prefetch_coordinate_numeric/lanes16
python3 test/frontend_pipeline/run_numeric.py --target fpga --register-descriptor 0 --size 4 --lanes 2 --bus-width 32 --cache-sets 4 --cache-ways 2 --line-bytes 16 --narrow-mode 2 --prefetch --out build/prefetch_coordinate_numeric/direct4
```

采用版本的三种配置各通过 42 项任务，合计 126 项、1545916 个周期、107694 个输出拍。八路和十六路配置的最小描述符接收间隔均为一个周期，各有 2118 次同周期提交和接收。各配置的精确参数、输出数量和源码散列见 `validation.json`。

## 完整预取模块的局部映射

```sh
python3 test/prefetch_coordinate/measure.py --out build/prefetch_coordinate_measure
```

映射参数为 `p_size=16`、`p_line_bytes=128`、`p_register_cache_request=1`。工具保留整个预取模块的实际寄存器和选择条件，分别导出 D 端和 CE 端的路径。`--mapped-directory` 可读取已经完成的映射；该模式先检查映射输入文件与当前生产源码的 SHA256。

| 测量范围 | 最长 D 端路径 | 最长 CE 端路径 |
|---|---:|---:|
| `accepted_coordinate_q[0]` 到 `projected_coordinate_q[0]` | 10 | 无连接路径 |
| 所有寄存器到两个 `projected_coordinate_q` | 11 | 4 |
| 所有寄存器到 `prefetch_horizontal_low_carry_q` | 12 | 4 |
| 所有寄存器到 `prefetch_base_no_borrow_q` | 7 | 4 |

整个预取模块的最长寄存器路径为 12 级；资源为 1238 个逻辑 LUT、1187 个触发器、131 个 CARRY4 和 3 个由普通 RTL 推断的 DSP。低位进位寄存器的最长输入来自 `output_coordinate_q[0][21]`。这些数字属于完整预取模块的独立映射，完整 SoC 的面积及路径由对应 SoC 综合报告给出。
