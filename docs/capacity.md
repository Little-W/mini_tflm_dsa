# PCR 面板与 PS RAM 容量求解

`scripts/capacity/solve.py` 在给定容量上限和矩阵任务集合下，联合选择 A 面板、B 面板和部分和页池的物理容量，并为每个任务选择 WS/IS、R/W 分块及尾块。求解器只依赖 Python 3 标准库。硬件配置保存在 [`config/npu.mk`](../config/npu.mk)，Make 将这些值传入 RTL 编译和驱动编译。

当前模型对应 16×16 INT8、K64 双缓冲面板、精确 INT32 部分和的 GEMPACT PCR 引擎。它优化正常遍历的外部操作数读取量；实际周期还受 AXI 延迟、写回、PS 编解码和 early completion 影响。

## 快速使用

以下命令在仓库根目录执行。KiB 为 1024 字节。

```bash
# 显示当前配置；初始配置保留旧引擎默认行为
make capacity-show

# A 面板 + B 面板 + PS 数据 RAM 合计不超过 128 KiB
# 求解成功后自动更新 config/npu.mk，并启用 PCR_ENGINE=1、SIZE=16
make capacity-solve MAX_RAM_KIB=128

# 检查已更新配置，再以该配置构建/运行
make capacity-check
make vcs-top GEN_ARGS='--K 80 --N 64 --M 112 --tight_strides'

# 无商业仿真器时，可用 Verilator + C++20 工具链编译后端
make pcr-backend PCR_BACKEND_MEM_WORDS=131072
```

求解与构建应分成两次 Make 调用。`make capacity-solve vcs-top` 会直接报错，因为 Make 在执行求解之前已经读取变量，无法保证同一次调用中的构建使用更新后的文件。

`make capacity-solve` 不指定上限时，使用配置中保存的预算；初始值为 256 KiB 的 `logical-state`。默认任务集合是 [`config/capacity_workloads.json`](../config/capacity_workloads.json) 中的八个 GEMM 任务，各任务等权。完整结果保存在 `build/capacity/solution.json`，包括容量、各任务分块、读取量、搜索范围和模型假设。

### 两种预算

| 命令 | 约束范围 |
|---|---|
| `make capacity-solve MAX_RAM_KIB=128` | A/B 面板和 PS/C 页池的数据数组总量，即 `buffer-ram` |
| `make capacity-solve MAX_STATE_KIB=128` | 数据数组，加目录、队列、流水寄存器、控制及 AXI 状态，即 `logical-state` |

这两个参数不能同时指定。`MAX_RAM_KIB` 不包括 SoC 主存、固件、CPU 缓存等资源；`MAX_STATE_KIB` 也是当前 PCR NPU 的逻辑状态模型，不是整个芯片的面积或存储预算。两种模式都未计入 FPGA BRAM 或 ASIC SRAM 宏的容量取整。

对默认八任务、`nominal3` 表示策略，128 KiB 上限产生以下不同结果：

| 预算范围 | `PANEL_MAX_R` | `PANEL_MAX_W` | A 面板 | B 面板 | PS 页池 | 数据 RAM 合计 | 完整状态模型 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `buffer-ram` | 8 | 16 | 16 KiB | 32 KiB | 80 KiB，320 页 | 128 KiB | 143901.5 B |
| `logical-state` | 12 | 8 | 24 KiB | 16 KiB | 76.25 KiB，305 页 | 116.25 KiB | 130892.625 B |

## 独立配置文件

`config/npu.mk` 使用字面值 `?=` 赋值。求解器更新以下字段，保留其他字段和注释：

```make
# 示例：默认任务，128 KiB 数据 RAM，nominal3
PCR_ENGINE ?= 1
SIZE ?= 16
PANEL_MAX_R ?= 8
PANEL_MAX_W ?= 16
PS_POOL_BYTES ?= 81920
PS_FORCE_RAW ?= 0
CAPACITY_BUDGET_BYTES ?= 131072
CAPACITY_BUDGET_SCOPE ?= buffer-ram
CAPACITY_REPRESENTATION ?= nominal3
```

文件中还集中设置 `IA_CACHE_BLOCKS`、`PS_FRAME_COUNT`、`AXI_READ_OUTSTANDING`。前两个是旧引擎/接口参数；当前 PCR 的面板 RAM 和 PS RAM 由 `PANEL_MAX_R/W` 与 `PS_POOL_BYTES` 决定，不能用旧参数推算其容量。

可以为不同预算保存不同配置：

```bash
mkdir -p build/configs
cp config/npu.mk build/configs/npu_64k.mk
make capacity-solve NPU_CONFIG=build/configs/npu_64k.mk MAX_RAM_KIB=64
make capacity-show NPU_CONFIG=build/configs/npu_64k.mk
make vcs-top NPU_CONFIG=build/configs/npu_64k.mk
```

`NPU_CONFIG` 会转换为绝对路径，递归 Make 使用同一份文件。命令行变量优先于文件中的 `?=`；例如手工覆盖 `PANEL_MAX_R` 后，构建前的 `capacity-check` 会检查实际有效值是否超预算。相同内容不会重复写入配置或改变其修改时间；输入非法、预算无解时不会修改配置。

已接入配置的入口包括根 Makefile、`veri/sim/Makefile`、`asic/Makefile` 和 `asic/synthesis/Makefile`。根目录的 `pcr-backend` 显式把配置传给 Verilator 后端构建器。独立调用其他 Python 构建脚本、旧 `veri/top_regression/Makefile` 或 Vivado Tcl 时，仍须按各入口的接口传递参数。

### 配置如何进入硬件和软件

| 配置字段 | RTL / 驱动中的作用 |
|---|---|
| `PCR_ENGINE=1` | 定义 `GEMPACT_PANEL_ENGINE`、`GEMPACT_PCR_PS`；驱动定义 `DSA_PCR_ENGINE=1` |
| `SIZE` | NPU 顶层 `SIZE` 参数；PCR 必须为 16 |
| `PANEL_MAX_R` | `GEMPACT_PANEL_MAX_R`、`DSA_PANEL_MAX_R`；物理 A/stream 面板上限 |
| `PANEL_MAX_W` | `GEMPACT_PANEL_MAX_W`、`DSA_PANEL_MAX_W`；物理 B/stationary 面板上限 |
| `PS_POOL_BYTES` | `GEMMORA_PS_POOL_BYTES` → `gempact_panel_engine.POOL_BYTES`，以及 `DSA_PS_POOL_BYTES` |
| `PS_FORCE_RAW` | 为 1 时定义 `GEMMORA_PS_FORCE_RAW`；驱动使用 `DSA_PS_FORCE_RAW` |

这里的 A/B 是物理面板名称。在 WS 下，stream 面板驻留 IA，stationary 面板驻留 W；在 IS 下二者承担的逻辑操作数角色交换。报告同时列出 A/B 面板容量，避免把物理 `Rmax` 的增长都解释成 IA 容量增长。

PCR 构建产物名称包含池容量、面板上限与 RAW 标志。`veri/sim` 还记录有效参数内容戳，即使手工固定 `SIMV` 文件名，参数变化也会触发重编；固件构建使用同样的物理参数。

## 终端配置菜单

`make menuconfig` 打开交互式终端界面，直接编辑同一份 `config/npu.mk`。可以手动调整参数，也可以在菜单中调用容量求解器。

```bash
# 编辑默认配置
make menuconfig

# 以 128 KiB 数据 RAM 预算打开；尚未保存前不会修改文件
make menuconfig MAX_RAM_KIB=128

# 编辑另一份配置；文件不存在时，保存会创建它
make menuconfig NPU_CONFIG=build/configs/npu_custom.mk

# 为界面中的 Optimize 指定任务集合
make menuconfig MAX_STATE_KIB=64 SHAPES='128,1024,128 512,1024,512'
```

菜单包含引擎选择、阵列大小、预算范围和容量、部分和表示策略、A/B 面板上限、PS 池大小，以及旧引擎缓存和 AXI 参数。界面实时显示 A/B 面板、PS 池、数据 RAM 合计、完整状态模型和剩余预算；旧引擎模式会注明 PCR 容量模型未启用。

| 操作 | 按键 |
|---|---|
| 选择项目 | `↑` / `↓` 或 `k` / `j` |
| 翻页 | `Page Up` / `Page Down` |
| 编辑参数 | `Enter` |
| 切换布尔值或枚举 | `Space`、`←` / `→` |
| 自动求解当前预算 | `O` |
| 校验并保存 | `S` |
| 从文件重新加载 | `L` |
| 退出 | `Q` 或 `Esc` |
| 查看当前参数帮助 | `?`、`H` 或 `F1` |
| 清空输入框 | `Ctrl-U` |

容量输入支持字节数和二进制单位，例如 `131072`、`128 KiB`、`1 MiB`；PS 池仍必须按 256 字节整页配置。启用 PCR 时会将 `SIZE` 设为 16，部分和表示策略与 `PS_FORCE_RAW` 保持同步。

修改先保存在菜单中的未保存状态。按 `O` 会用当前预算和指定任务集合求解并填入参数；按 `S` 才会校验并写回配置。超预算或其它非法配置可以继续编辑，但不能保存。退出时有未保存修改，可选择保存、放弃或取消退出；如果文件被其他程序修改，菜单会阻止覆盖并提示重新加载。

菜单从配置文件中的持久参数开始编辑；显式传入的公共参数，例如 `make menuconfig PANEL_MAX_R=8`，会作为待保存修改载入。子 Make 的旧引擎默认参数不会自动写回配置。`MAX_RAM_KIB`、`MAX_STATE_KIB`、`REPRESENTATION`、`SHAPE/SHAPES`、`WORKLOADS` 和 `CAPACITY_OUTPUT` 与命令行求解入口一致。界面内求解后保存，会同时导出对应的解；手动编辑后需要再次求解才能导出新的求解报告。

菜单要求交互式终端及可用的 Python `curses` 模块，支持 80×24 终端、滚动和窗口尺寸变化。若系统 Python 未包含 `curses`，需通过系统的软件包管理器安装带该模块的 Python；不需要 `dialog` 或 `Kconfiglib`。直接调用脚本也可查看帮助：

```bash
python3 scripts/capacity/menuconfig.py --help
```

保存并退出后，再单独运行 `make capacity-check` 或构建命令。与求解入口相同，`make menuconfig vcs-top` 会被拒绝，保证构建重新读取保存后的参数。

## 自定义任务和表示策略

求解器采用标准 GEMM 维度：`A[M,K] × B[K,N] = C[M,N]`。

```bash
# 单任务：结果针对该任务求解
make capacity-solve MAX_RAM_KIB=128 SHAPE=512,1024,512

# 一组任务共享同一份物理硬件
make capacity-solve MAX_RAM_KIB=128 SHAPES='128,1024,128 512,1024,512'

# 从 JSON 读取任务；SHAPE/SHAPES 未指定时使用 WORKLOADS
make capacity-solve MAX_RAM_KIB=128 WORKLOADS=config/capacity_workloads.json

# 使用 RAW32 部分和准入规则，并同步写入 PS_FORCE_RAW=1
make capacity-solve MAX_RAM_KIB=128 REPRESENTATION=raw32
```

自定义 JSON 格式：

```json
{
  "workloads": [
    {"M": 128, "K": 1024, "N": 128},
    {"M": 512, "K": 1024, "N": 512}
  ]
}
```

`nominal3` 使用正常压缩记录的名义准入约束：

\[
RW+3R\le P,\qquad 3RW+R\le P.
\]

`raw32` 使用 `4RW <= P`。两者都保持 INT32 部分和值精确；`nominal3` 不是把计算精度降为 24 位。对任意数据，压缩记录增长仍可能触发 RTL 的 early completion，额外读取不能仅靠矩阵形状预测。需要按最坏 RAW32 容量准入时，选用 `raw32`；该选项同时强制原始部分和存储。

Python 模型允许非 16 倍数形状，并在结果中标出 `requires_padding` 和填充后的尺寸。它不替调用方变换张量；实际 PCR 驱动和测试生成器要求维度已经按 16 对齐，且小于 20 位尺寸上限。

注意：历史测试生成器的参数命名为 `--K` 输出行、`--N` 归约维、`--M` 输出列。例如文首的 `--K 80 --N 64 --M 112` 对应求解器中的 `M=80,K=64,N=112`。

## 搜索范围和“最佳”的定义

物理容量计算为：

\[
B_A=2048R_{\max},\quad B_B=2048W_{\max},\quad B_{PS}=256P.
\]

求解器枚举 `Rmax,Wmax ∈ [1,32]`，对每个几何用整数二分搜索求预算内的最大 PS 页数 `P ∈ [4,4095]`；随后为每个任务枚举合法整数 `R,W`、WS/IS 方向、均匀分组和末组尾块。

多任务主目标是最小化正常遍历 A+B 外部读取量的等权几何平均数，实际比较使用精确整数乘积。读取量相同时，依次比较估计输出 burst、列帧数、分组数、逻辑状态大小和物理 R/W，使结果可重复。最大页数枚举足以覆盖这个读取量主目标；状态大小只是候选之间的择优项，不是对所有页数的全局最小面积证明。

WS 的读取量为：

\[
MK\left\lceil\frac{N/16}{W}\right\rceil + KN\left\lceil\frac{M/16}{R}\right\rceil.
\]

IS 则使用 `MK ceil((N/16)/R) + KN ceil((M/16)/W)`，尺寸均按填充后计算。JSON 的 `same_read_geometries` 给出主目标并列的物理几何数；“最佳”可能并非唯一。

完整状态公式保存在 [`scripts/capacity/model.py`](../scripts/capacity/model.py) 的 `state_bits()` 中，包含页指针位宽、目录及 PS 存储分区相关状态的取整。在核对过的 `e8a7337` RTL 基础上，保留论文计数比当前 AXI 包装器多计 3 bit，偏保守 0.375 B。RTL 结构发生变化后，应重新核对该状态模型。

### 运行时分块

[`drivers/gempact_tiling.h`](../drivers/gempact_tiling.h) 的 `gempact_plan_panel()` 与 Python 模型使用相同的物理限制、准入规则和分组排序。PCR 下支持 3、5、7、11 等整数分块，不再将其降为旧引擎支持的 2 的幂。`ia_reuse_num/w_reuse_num=0` 表示自动选择，非零值表示调用方给出的上限。

硬件求解报告可为每个任务自动选择 WS/IS；C 驱动保留调用方设置的数据流方向，在该方向内选择分块。若要复现报告中的读取量，应同时采用报告中的 `mode`。Python 测试生成器通过 `--dataflow_mode 0/1` 选择 WS/IS，并输出 `acc.mem`，用于完整 INT32 部分和检查。

## 独立脚本和验证

```bash
# 只求解/导出，不更新配置
python3 scripts/capacity/solve.py --max-ram-kib 128 \
  --shape 512,1024,512 --output build/capacity/single.json

# 显式更新配置
python3 scripts/capacity/solve.py --config config/npu.mk \
  --max-state-kib 128 --apply

# 导出供外部集成参考的 NPU_CONFIG_* C 宏
python3 scripts/capacity/solve.py --config config/npu.mk \
  --emit-c-header build/capacity/npu_config.h

# 求解器、Make、C 分块器及输入生成回归
make capacity-test
```

Make 内部以 `DSA_*` 编译宏连接现有驱动；导出的头文件使用 `NPU_CONFIG_*` 命名，供其他集成入口映射，不会自动注入外部工程。

`pcr-backend` 的输出根目录可通过 `PCR_BACKEND_OUTPUT` 指定，编译并行度为 `PCR_BACKEND_JOBS`。该入口沿用现有后端构建器的不可变快照规则：已存在相同标签的后端时不会覆盖；需要重新编译相同几何的新 RTL 时，应指定另一个输出目录。`PCR_BACKEND_MEM_WORDS` 是仿真器的外部存储容量，不计入片上 RAM 预算。

测试覆盖已知容量最优解、硬预算边界、RAW32/压缩模式、无解时配置不变、重复更新、Make 参数覆盖与重编，以及 C/Python 分块一致性。RTL 的完整 INT32 和 INT8 输出验证仍由现有 PCR 测试平台完成；商业 VCS/ASIC 综合需在具备相应工具与工艺库的环境运行。
