# 开源 FPGA 综合与资源分析

本项目使用 Yosys、Slang 和 ABC 将 RTL 转换为 Xilinx 7 系列器件单元。脚本支持独立模块、完整 NPU 和包含 PicoRV32、片上存储器、AXI 互连及 UART 的完整 SoC。综合结果用于比较硬件结构与资源数量；150 MHz 工作频率由目标器件的布局布线时序报告检查。

完整 SoC 同时检查三个目标：合法布局中的物理 LUT 位置不超过 50,000，最长寄存器间组合路径不超过 15 个组合单元，以及目标器件在 6.667 ns 周期下满足时序要求。综合逻辑 LUT 或合法布局物理 LUT 首次不超过 60,000 时，保存对应阶段的独立交接检查点；检查点分别记录三个目标的实际完成状态。

## 环境与运行

Python 环境需要 `pyosys==0.71.post40`，功能验证使用 Verilator。完整 SoC 还需要仓库指定的 PicoRV32 子模块。

```sh
python3 -m pip install pyosys==0.71.post40
git submodule update --init picorv32
python3 scripts/fpga/open_fpga_synth.py --cases soc_top --out build/open_soc
```

独立模块可使用以下命令：

```sh
python3 scripts/fpga/open_fpga_synth.py --cases array vector_engine --out build/open_modules
python3 scripts/fpga/open_fpga_synth.py --cases npu_top --out build/open_npu
```

多个工作目录共享一台机器时，使用同一个文件锁，使综合按顺序执行：

```sh
python3 scripts/fpga/open_fpga_synth.py --cases soc_top \
  --out build/open_soc --lock-file /tmp/mini_tflm_dsa_synthesis.lock
```

`--source-root` 指定需要测量的仓库工作目录，`--out` 指定结果目录。每轮测量应使用独立结果目录，综合期间保持被测 RTL 不变。脚本在开始和结束时核对源码 SHA-256。

## 完整 SoC 配置

`soc_top` 测量使用下表中的固定配置，对应 FPGA 工程的生产配置。部分和采用直接 INT32 存储。

| 项目 | 配置 |
| --- | --- |
| 目标器件 | `xc7a200tfbg484-3` |
| 目标时钟周期 | 6.667 ns |
| 脉动阵列 | 16×16，INT8 与 INT16 |
| NPU 总线 | 64 位 |
| IA 缓存块数 | 4 |
| im2col 缓存容量 | 4096 字节 |
| IA/PS 共享存储器 | 7 个存储块，每块 8192 字节，总计 57,344 字节 |
| PS 最大存储池 | 49,152 字节，直接 INT32 |
| 部分和帧数 | 16 |
| AXI 读写在途事务数 | 各 4 |
| 向量处理单元 | 启用，8 个 PE |
| CPU 存储器 | 65,536 个 32 位字，总计 256 KiB，64 位物理端口 |
| CPU 乘除法 | 启用 |
| CPU 指令缓存 | 关闭 |
| WS/IS 与逐通道量化 | 启用 |
| NPU AXI、CPU 写入、RAM 写入寄存处理 | 启用 |
| RAM 双缓冲 | 启用 |

所有参数的实际值写入 `manifest.json` 和 `summary.json`。`npu_top` 使用相同的生产 NPU 配置；`soc_top` 同时包含 CPU、片上存储器和外设。

生产配置固定使用 `SYNTHESIS=1`、`XILINX_FPGA=1`、`XILINX_CLK_WIZ_IP=1`、`GEMPACT_PS_COMPRESS=1`、`GEMMORA_PS_POOL_BYTES=49152` 和 `GEMMORA_PS_FORCE_RAW=1`。`GEMPACT_PS_COMPRESS` 是工程保留的开关名称，用于启用共享存储与帧调度；当前部分和存储采用 INT32。NPU 时钟由 `BUFGCE` 控制。

脚本核对 `config/npu_fpga.mk` 中的生产参数，保存该文件的 SHA-256、配置值及编译宏。展开阶段检查 IA/PS 共享 RAM、`ps_frame_store`、`BUFGCE` 和 CPU 存储器实际存在，并将对象名称保存为 `elaboration_structure.txt`。

## 原语与公共存储模块

各测量项自动包含 `rtl/common/` 下的 `.v` 和 `.sv` 文件，供 regfile 等公共模块使用。

显式实例化的 `LUT1`、`LUT6_2`、`DSP48E1` 等原语，从所安装 Yosys 的 `cells_sim.v` 和 `cells_xtra.v` 读取完整参数与功能定义。展开阶段保留原语实例及参数，后续由 Xilinx 综合流程处理。生成的 `xilinx_primitives.sv`、所选原语名称和工具库的 SHA-256 随测量结果保存。功能仿真可直接使用相同版本的原始 Xilinx 功能模型。

存储器使用 RTL 描述的容量、读写端口和读取周期进行自动推断。综合脚本不增加强制 BRAM 属性。小型存储器使用公共 regfile 封装时，最终采用寄存器、分布式 RAM 或块 RAM 由综合工具决定。

## 阶段文件与继续执行

每个测量项分为三个独立进程阶段。

| 阶段 | 保存内容 | 用途 |
| --- | --- | --- |
| `01_elaborate` | `elaborated.il` | 完成 SystemVerilog 展开并保留确定的参数与连接 |
| `02_pre_lut` | `pre_lut.il` | 完成算术、DSP、存储器和触发器转换 |
| `03_map_lut` | `mapped.json`、`mapped.v` | 完成 LUT 转换、结构检查及 Xilinx 原语网表导出 |

每个阶段保存独立的 `.ys` 脚本和 `.log` 日志。`stages.json` 记录耗时、以 0.2 秒间隔采样的进程树内存峰值，以及脚本和阶段文件的 SHA-256。

物理实现阶段另以两秒间隔原子更新 `<stage>.progress.json`，记录运行状态、进程树当前与峰值 RSS、系统可用内存和最低已观测值。子进程结束后保留退出码及最终资源记录，命令单独保存为 `<stage>.command.json`。

`--through elaborate` 仅完成展开与生产结构检查，`--through pre_lut` 保存 LUT 转换前的设计。通过 `--resume` 可以继续完成剩余阶段。

```sh
python3 scripts/fpga/open_fpga_synth.py --cases soc_top \
  --out build/open_soc --resume
```

`--resume` 核对保存的源码、参数、原语模型、阶段脚本和阶段文件。通过核对的阶段直接复用；从第一个需要重新执行的阶段继续运行。源码或配置不同的设计应使用新的输出目录。

`--reuse-elaboration-from /path/to/case` 可以在新的输出目录复用相同源码、参数、生产配置和原语模型的 `elaborated.il`。脚本检查来源清单与文件 SHA-256，保存来源路径、原阶段统计和复制结果摘要。例如，在同一固定源码上增加 DSP 映射时，可复用普通综合已经完成的展开结果。

### 中间文件压缩与恢复

`manage_intermediate_archives.py` 对已完成测量的中间文件执行无损 gzip 压缩。每份压缩文件保存前，程序解压并核对原始 SHA-256，再保存清单并移除原始副本。清单保存原始文件与压缩文件的大小、SHA-256、权限和修改时间。恢复时检查两种 SHA-256，已有文件内容不一致时停止操作。

当前 [intermediate_archives.json](data/intermediate_archives.json) 记录 46 份文件，原始大小为 8,150,330,641 字节，压缩后为 615,944,285 字节。恢复单个文件时，`--root` 指向包含 `worktrees` 的测量目录：

```sh
python3 scripts/fpga/manage_intermediate_archives.py restore \
  --root /path/to/measurement_workspace \
  --manifest docs/data/intermediate_archives.json \
  --path worktrees/round8_measurement/build/soc_round8_dsp740_pre/soc_top/pre_lut.il
```

使用 `--all` 代替 `--path` 可以恢复清单中的全部文件。恢复完成后，压缩文件仍保留。继续旧综合阶段前，先恢复相应阶段文件，使综合程序能够按原有清单检查文件摘要。新增压缩任务使用 `archive` 子命令和 `--paths-file`，文件内容为相对于 `--root` 的路径数组；仅选择已停止使用的中间文件。

## 宽算术单元的 DSP 映射

`--wide-alu-dsp-budget` 启用宽算术单元到 `DSP48E1` 的组合映射。默认筛选输出宽度为 24 至 48 位的 Yosys `$alu`，统计已有 DSP 后，在给定总预算内选择候选。

```sh
python3 scripts/fpga/open_fpga_synth.py --cases soc_top \
  --out build/open_soc_dsp --wide-alu-dsp-budget 740 \
  --lock-file /path/to/synth.lock
```

映射保留原有时钟周期与加减法行为，包括两个操作数的符号扩展、输入进位、`X`、`Y` 和全部逐位 `CO` 输出。DSP 的内部寄存器关闭。默认候选选择检查组合依赖，所选 DSP 之间保留寄存器分隔，并排除与已有未寄存 DSP 串接的候选。完整网表的最终 DSP 数量再次核对预算。

`--wide-alu-dsp-reserve` 可以保留额外 DSP 容量，`--wide-alu-minimum-width` 调整筛选的最小宽度。选择首先处理 24 至 48 位算术，再将较窄且独立的单元加入剩余预算；降低最小宽度时，已经选择的宽算术保持优先。例如，`--wide-alu-minimum-width 16 --wide-alu-dsp-budget 739` 允许补充 16 至 23 位算术，同时给器件保留一个 DSP。启用后增加 `02a_pre_alu` 和 `02b_map_alu` 阶段，分别保存 `pre_alu.json`、`mapped_alu.json` 和 `wide_alu_mapping.json`。报告列出预算、已有 DSP、候选与实际选择。源码、映射模型、选择程序及阶段文件均保存 SHA-256。

`--wide-alu-maximum-chain 2` 允许同一组合路径包含至多两个本轮选中的算术 DSP。选择时同时检查候选的全部上游与下游依赖，维持与已有未寄存 DSP 的分隔；默认值为 `1`。完整设计的 DSP 内部组合段、LUT、MUX 和 CARRY 仍由 `netlist_metrics.py` 统一统计，并使用相同的十五级要求。两次三十二位模加之间包含异或的验证电路，通过四万余个周期的实际综合网表比较及真实参数形式证明；两 DSP 实现的寄存器间路径为三个组合单元。对应结果见 [DSP 选择与复用验证](data/bounded_dsp_mapping_validation.json)。

固定同一份 RTL 比较不同 DSP 选择时，可以用 `--reuse-pre-alu-from` 指定已完成粗综合的单个 case 目录。工具核对全部源码、生产参数、原语模型、综合命令及网表 SHA-256，再复用 `elaborated.il` 和 `pre_alu.json`；后续算术选择和 LUT 映射重新执行。该选项与 `--wide-alu-dsp-budget` 一起使用。

分析布局中的组合 DSP 长连接后，可以单独保留指定算术单元的进位逻辑。直接运行 `map_wide_alu.py` 时，使用 `--selection-reference` 指定同一输入的 `wide_alu_mapping.json`，并用 `--keep-as-carry` 指定其中的完整单元名称；多个单元可以重复给出该选项。输入 SHA-256、预算、位宽范围和原有选择必须与参考报告一致。指定单元保留 `$alu` 类型，其余 DSP 选择、连线、参数和自动编号保持。报告保存保留的单元及减少后的 DSP 数量。该候选需要从修改后的算术映射阶段重新生成 `pre_lut.il`，并完成相同的 LUT 映射、功能检查和物理测量。

形式验证直接使用安装版本的 Yosys `$alu` 与 `DSP48E1` 功能模型，覆盖 1、17、24、32、48 位、符号组合、截断与扩展，以及动态 `BI`、`CI` 的全部确定输入取值。

```sh
python3 scripts/fpga/test_wide_alu_dsp.py --out build/wide_alu_formal
python3 scripts/fpga/test_map_wide_alu.py -v
```

对具体生产综合结果，验证脚本从选择清单读取每个算术单元的真实参数，合并相同参数组合后执行全输入证明，并保存网表、选择清单与模型摘要。

```sh
python3 scripts/fpga/test_wide_alu_dsp.py \
  --selected-netlist build/open_soc_dsp/soc_top/pre_alu.json \
  --selection build/open_soc_dsp/soc_top/wide_alu_mapping.json \
  --out build/open_soc_dsp/soc_top/selected_alu_proof
```

DSP 选择的 JSON 检查点同时保存 `mapped_alu.autoidx.il`，记录既有私有标识符使用的最大自动编号。后续技术映射先恢复该计数，再读取 JSON，生成新的唯一临时名称。继续执行时同时核对 JSON 和计数文件的 SHA-256。

## LUT 面积成本映射

### 按输出函数分析组合依赖

`lut_dependencies.py` 根据原语的 `INIT`、常量输入和重复输入连接，分别计算 `LUT1` 至 `LUT6` 以及 `LUT6_2` 每个输出实际使用的输入。`O5` 使用低32位真值表，`O6` 使用完整64位真值表；连接同一净信号的多个引脚作为同一个变量。真值表包含未定义位时，分析保留可能存在的依赖。

宽算术DSP选择、组合级数统计和详细路径导出使用相同的输出依赖结果。一个双输出LUT的两个函数分别建立图节点，输出仅连接到自身使用的输入。寄存器与DSP内部寄存边界继续按实际参数划分。工具清单保存依赖分析程序的SHA-256。

`scripts/fpga/patches/nextpnr_lut_output_inputs.patch` 将相同原则应用到物理打包。拆分 `LUT6_2` 时，若第六输入为常量且 `INIT` 完整定义，每个输出仅保留影响自身真值表的输入连接，原始 `INIT` 保持。具有动态第六输入的余因子共享仍保留共同输入及专用A6连接。组合环检查保持启用。

以下测试执行真实打包、布局、布线、物理输入排列及FASM真值表检查：

```sh
python3 scripts/fpga/tests/run_lut_output_implementation.py \
  --nextpnr /path/to/nextpnr-xilinx \
  --source /path/to/nextpnr-xilinx/xilinx \
  --chipdb /path/to/chipdb-xc7a200tfbg484-3.bin \
  --package-pins /path/to/prjxray-db/artix7/xc7a200tfbg484-3/package_pins.csv \
  --tilegrid /path/to/prjxray-db/artix7/xc7a200t/tilegrid.json \
  --out build/lut_output_implementation
```

四个可实现电路分别覆盖两个输出之间的单向依赖、固定第六输入和动态余因子共享，全部完成布线并通过函数检查；第五个电路检查真实组合环的拒绝行为。结果见 [nextpnr_lut_output_validation.json](data/nextpnr_lut_output_validation.json)。Python分析测试还覆盖全部二输入及三输入真值表、常量、重复连接、未定义位、DSP组合路径限制及完整SoC选择结果，见 [measurement.json](../test/lut_dependencies/measurement.json)。

### 面积成本配置

`scripts/fpga/remap_fpga_luts.py` 从已经保存的 `pre_lut.il` 开始，保持完整 SoC 配置、DSP 选择和存储结构一致。输入目录的 `manifest.json` 与 `stages.json` 用于核对网表及原语库 SHA-256。每个方案使用独立输出目录，保存映射命令、原语网表、功能证明、资源、连通寄存器路径和阶段摘要。

```sh
python3 scripts/fpga/open_fpga_synth.py --cases soc_top \
  --out build/soc_pre --through pre_lut \
  --wide-alu-dsp-budget 740 --wide-alu-minimum-width 16 \
  --lock-file /tmp/mini_tflm_dsa_synthesis.lock
python3 scripts/fpga/remap_fpga_luts.py \
  --source build/soc_pre/soc_top --out build/soc_cost/soc_top \
  --mode physical-cost --lock-file /tmp/mini_tflm_dsa_synthesis.lock
```

面积成本模式从当前 Xilinx 原语模型生成 LUT 库，保留每个输入引脚的延迟，将 1 至 6 输入 LUT 的面积成本设为 1，7 输入和 8 输入选择网络的成本分别设为 2 和 4。ABC9 使用 XAIGER 版本 1、300 ps 连线成本及 6667 ps 延迟目标，并执行 `&verify`。这些成本指导逻辑映射；最终 LUT 占用仍由合法布局中的物理位置统计。

可通过 `--small-lut-area-cost 0.75` 比较较小 LUT 的成本选择。该参数只调整一至五输入 LUT 的面积成本，六输入 LUT 保持为 1，七/八输入保持为 2/4，全部引脚延迟、连线成本和目标周期保持。各候选使用独立输出目录，并完成组合等价、实际配对和合法布局后比较物理占用。默认值为 1。

固定 `dab4a8d` 的完整 SoC 使用相同器件、种子 1 和十轮布局细化完成比较：标准成本为 61,514 个物理 LUT 位置，成本 0.75 为 61,271 个，减少 243 个。两者的综合逻辑 LUT 分别为 61,644 和 63,598，占用 Slice 数分别为 19,893 和 20,958。资源、工具、网表、配置和实际阶段摘要保存于 [fpga_lut_cost_variants.json](data/fpga_lut_cost_variants.json)。两份结果均完成合法布局，布线与完整目标器件时序检查另行执行。

`native-xaiger1` 保留原语库的默认面积成本与引脚延迟。`legacy` 使用普通 ABC LUT 映射，并对提取前后的全部组合边界执行按名称匹配的分区 CEC。三种模式都要求功能等价检查成功。`--resume` 仅复用输入摘要、脚本、库文件、输出网表及日志全部一致的阶段。

固定提交 `b8b34d5` 的同一 DSP 映射检查点得到下列结果；各方案均使用 700 个 DSP。

| 映射方案 | 逻辑 LUT | RAM LUT | SRL LUT | FF | 最长寄存器组合路径 |
| --- | ---: | ---: | ---: | ---: | ---: |
| ABC9 默认 XAIGER 版本 2 | 71,161 | 4,012 | 192 | 54,499 | 32 |
| ABC9 原语成本、XAIGER 版本 1 | 70,207 | 4,012 | 192 | 54,499 | 33 |
| ABC9 面积成本 | 65,917 | 4,012 | 192 | 54,499 | 32 |
| 普通 ABC | 77,345 | 4,012 | 0 | 55,434 | 36 |

表内最后一列为实际连通路径中的组合单元数。对应资源、配置、网表与证明摘要保存于 [fpga_lut_mapping_comparison.json](data/fpga_lut_mapping_comparison.json)。面积成本方案的物理位置与目标速度等级时序需继续执行布局布线后确定。

可运行包含寄存乘法、加法和动态移位的小设计，检查三种映射的完整功能证明以及检查点复用：

```sh
python3 scripts/fpga/tests/test_lut_remapping.py --out build/lut_remapping_validation
```

## 资源数量的含义

`metrics.json` 同时保存逻辑 LUT、分布式 RAM 和移位寄存器占用。

| 字段 | 含义 |
| --- | --- |
| `logic_lut_cells` | 网表中的逻辑 LUT 原语数量；`LUT6_2` 按一个单元计算 |
| `distributed_ram_lut_sites_nominal` | 根据存储原语结构换算的 LUT 存储位置数量 |
| `shift_register_lut_sites_nominal` | 移位寄存器使用的 LUT 存储位置数量 |
| `lut_sites_nominal_before_packing` | 上述三项之和 |
| `physical_lut_sites_after_placement` | 合法布局后的物理 LUT 位置数量；单独综合阶段为空 |

`RAM32M` 和 `RAM64M` 各需要四个 LUT 存储位置，`RAM64X1D` 需要两个，`SRL16E` 和 `SRLC32E` 各需要一个。打包过程可以把满足条件的逻辑函数放入同一个 LUT，也可能为连接增加 LUT 单元。因此，完整 SoC 的 50,000 LUT 目标使用合法布局后的物理占用检查。

## 布局与布线

`open_fpga_implementation.py` 将综合后的网表交给 `nextpnr-xilinx`，依次保存时钟缓冲器处理、器件打包、合法布局和完整布线结果。

```sh
python3 scripts/fpga/open_fpga_implementation.py \
  --mapped build/open_soc/soc_top/mapped.json \
  --nextpnr /path/to/nextpnr-xilinx \
  --chipdb /path/to/chipdb-xc7a200tfbg484-3.bin \
  --soc-package-pins /path/to/prjxray-db/artix7/xc7a200tfbg484-3/package_pins.csv \
  --out build/open_soc_implementation --freq 150 \
  --lock-file /path/to/synth.lock --allow-timing-failure
```

`--soc-package-pins` 为独立 `soc_top` 测量分配合法封装引脚。输入 `clk` 直接使用 150 MHz SoC 时钟，时钟、复位和 UART 使用工程已有引脚，其余状态端口分配到 Bank 34。开发板完整顶层使用 `fpga_top` 及其时钟生成与引脚约束。已有完整 XDC 时，可改用 `--xdc`。

`--through pack` 和 `--through place` 分别在打包、布局后停止。默认继续完成布线。`--resume` 核对网表、工具二进制、器件数据库、约束、环境选项和各阶段结果，再继续运行。

| 文件 | 内容 |
| --- | --- |
| `manifest.json` | 器件数据库中的实际器件名称、工具与输入摘要、引脚分配和 150 MHz 约束 |
| `implementation.json` | 已插入全局时钟缓冲器的网表 |
| `packed.json` | 打包后的器件单元与位置关系 |
| `placed.json` | 通过布局检查的具体 BEL 位置 |
| `routed.json` | 完成布线的网表和连接 |
| `placed_resources.json` / `routed_resources.json` | 物理 LUT 数量和用途分类 |
| `placement_timing.json` / `routing_timing.json` | 工具当前时序模型给出的延迟与频率结果 |

`placed_resources.py` 按同一 Slice 中的 A、B、C、D 位置合并 `5LUT` 与 `6LUT`。逻辑、分布式 RAM、SRL 三类采用互不重复的物理位置计数，共用一个位置的两个输出只计算一次。全部单元必须已经分配 BEL，且没有重复 BEL 占用，才输出完整的物理 LUT 总数。

### 限定布局细化次数

应用 `scripts/fpga/patches/nextpnr_heap_iteration_limit.patch` 后，可用 `NEXTPNR_HEAP_MAX_ITERS` 设置 HeAP 分析布局的最大迭代次数，取值必须为正整数。每次迭代先完成严格合法化并保存较好的位置，达到指定次数后恢复已保存的位置，再进行退火细化与全部位置检查。未设置该变量时保持原有停止条件。

`NEXTPNR_HEAP_MAX_ITERS=2 NEXTPNR_REFINE_MAX_ITERS=1` 已用于同步复位和异步复位两类电路的独立与配对布局比较。四个实现均完成合法布局及布线，LUT真值、寄存器初值、复位、使能和输出选择检查通过。配对实现分别占用一个物理LUT位置，独立实现分别占用两个。完整结果及工具SHA256见 [nextpnr_heap_iteration_validation.json](data/nextpnr_heap_iteration_validation.json)。限定搜索次数可以控制测量时间，实际频率仍使用布线后的时序报告检查。

应用 `scripts/fpga/patches/nextpnr_refinement_limit.patch` 后，`--refinement-iterations 10` 将 HeAP 后的退火细化限制为十次迭代。该选项通过 `NEXTPNR_REFINE_MAX_ITERS` 传给实现程序，取值必须为正整数。未指定时保持工具的自然收敛停止条件。每次布局仍检查全部 BEL 的合法性、全部相对位置约束并执行时序分析，然后保存 `placed.json`。随机种子、迭代次数和工具摘要保存于 `manifest.json`。

固定种子和相同迭代次数可用于比较不同配对方案的实际占用与线长。邻近位置选择使用已完成布局的坐标；增加配对后重新执行合法布局和布线。

以下命令验证一次细化后的参考电路、共用输入配对及邻近位置配对：

```sh
NEXTPNR_REFINE_MAX_ITERS=1 python3 scripts/fpga/tests/run_carry_lut_pair_implementation.py \
  --nextpnr /path/to/nextpnr-xilinx --source /path/to/nextpnr-xilinx/xilinx \
  --chipdb /path/to/chipdb-xc7a200tfbg484-3.bin \
  --package-pins /path/to/prjxray-db/artix7/xc7a200tfbg484-3/package_pins.csv \
  --tilegrid /path/to/prjxray-db/artix7/xc7a200t/tilegrid.json \
  --out build/refinement_validation
```

三个电路均完成布线，每个电路检查 256 组输入与 14 个寄存器输入，并核对导出的 LUT INIT、进位和触发器输入选择以及共享输出选择。未启用迭代限制时，同一输入网表的 81 个单元及全部端口与已验证实现完全一致。验证摘要见 [nextpnr_refinement_validation.json](data/nextpnr_refinement_validation.json)。

### 读取已保存布局的时序路径

应用 `scripts/fpga/patches/nextpnr_saved_path_report.patch` 后，可以独立读取已经完成布局的文件，输出每个时钟及跨时钟关系的最长路径：

```sh
python3 scripts/fpga/report_saved_timing.py \
  --design build/open_soc_implementation/placed.json \
  --nextpnr /path/to/nextpnr-xilinx \
  --chipdb /path/to/chipdb-xc7a200tfbg484-3.bin \
  --out build/open_soc_placement_paths --freq 150
```

程序保持输入文件的 SHA-256 不变，保存 `paths.json`、原始日志及每时钟频率报告。路径包含寄存器起止端口、原始单元类型、RTL 来源、BEL 位置，以及逐段逻辑和连线延迟。逐段数值沿用工具日志的 0.1 ns 显示精度。已放置设计使用距离预测的连线延迟。

执行完整实现时，设置 `NEXTPNR_REPORT_PATHS=1` 会把相同格式的路径分段写入各阶段日志；布线阶段使用当前实际连接的延迟。原语和目标速度等级的模型覆盖情况随报告记录。验证覆盖真实寄存器间路径的已保存布局分析和实际布线阶段分析，见 [nextpnr_saved_timing_validation.json](data/nextpnr_saved_timing_validation.json)。

增加 `--register-origins build/open_soc_dsp/soc_top/pre_lut.il` 可以把触发器单元关联到技术映射前的寄存器名称。增加 `--dsp-connections` 并应用 `scripts/fpga/patches/nextpnr_dsp_connection_report.patch`，可以同时输出组合 DSP 的最长二十条连接，以及十个不同 DSP 各自的最长连接。该报告保留 DSP 参数、RTL 来源、实际源端口、目的端口和 BEL 位置；相同延迟的连接按名称排序。报告中的数据路径组合 DSP 要求 `AREG`、`BREG`、`CREG`、`DREG`、`ADREG`、`MREG`、`PREG`、`ACASCREG`、`BCASCREG` 均关闭，控制寄存参数单独保存在每个 DSP 的记录中。

DSP 连接延迟直接读取当前实现阶段使用的延迟函数，数值以 ns 保存到小数点后六位。已保存布局使用器件 tile 距离模型，完整实现中的布线阶段使用当前实际连接。独立检查程序从网表重新建立驱动与使用关系，并使用器件坐标重新计算最长跨 tile 连接，验证前二十条连接和十个不同 DSP 的排序：

```sh
python3 scripts/fpga/tests/check_dsp_connection_report.py \
  --design build/open_soc_implementation/placed.json \
  --report build/open_soc_placement_paths/paths.json \
  --tilegrid /path/to/prjxray-db/artix7/xc7a200t/tilegrid.json \
  --out build/open_soc_placement_paths/connection_check.json
```

验证摘要见 [nextpnr_dsp_connection_validation.json](data/nextpnr_dsp_connection_validation.json)。

### 使用 Vivado 实现原语网表

综合末尾同时导出 `mapped.v`，包含所选 DSP、LUT、存储器及触发器原语，并加入 `IBUF`、`OBUF` 与全局时钟缓冲器。网表文件的 SHA-256 随阶段结果保存。启用宽算术 DSP 映射时，选择结果直接保留在该网表中。

`scripts/fpga/vivado_implement_mapped_soc.tcl` 使用 `read_verilog`、`read_xdc` 和 `link_design` 建立目标器件设计，随后执行优化、布局、物理优化和布线。这一入口使用已经完成技术映射的结构网表，符合 AMD 的 [link_design 命令说明](https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/link_design)。

```sh
vivado -mode batch -source scripts/fpga/vivado_implement_mapped_soc.tcl \
  -tclargs build/open_soc_dsp/soc_top/mapped.v \
  build/open_soc_implementation/soc_measurement.xdc \
  build/vivado_mapped_soc
```

目标器件固定为 `xc7a200tfbg484-3`，顶层为 `soc_top`。输入 XDC 使用独立 SoC 的实际封装引脚；可复用开源实现脚本生成的 `soc_measurement.xdc`。若 XDC 已指定更严格的时钟周期，脚本保持该值；其余情况使用 6.667 ns，并拒绝超过目标周期的约束。

输出目录保存连接、布局、布线三个设计检查点、资源报告、设计规则检查、布线状态、未约束路径、最长 setup 与 hold 路径。公共程序 `fpga/vivado/tflm_ai_dsa_soc/scripts/timing_checks.tcl` 在布线后检查以下条件：

- `report_route_status` 的 `ROUTED_FULLY` 为真，`ERRORS_IN_ROUTES` 为假。
- 默认 DRC 规则中严重性为 `Fatal`、`Error` 或 `Critical Warning` 的检查全部通过。
- `no_clock`、`unconstrained_internal_endpoints`、`generated_clocks`、`loops` 和 `latch_loops` 的问题数量均为零。
- 存在完整的 setup 与 hold 路径，所有实际时钟的最差裕量均非负；全设计最差路径另行检查，以覆盖具有外部延迟约束的端口路径。

这些条件未满足时，脚本返回错误。内部时序检查报告必须包含每一项的可识别数值；未知格式不会作为通过结果。外部输入、输出延迟的检查结果同时保存在 `clock_checks.rpt`，接口的具体时序要求由输入 XDC 提供。

| 输出文件 | 内容 |
| --- | --- |
| `synchronous_timing.tsv` | 每个实际捕获时钟的周期、setup WNS/TNS、hold WNS/TNS、端点数量和 Fmax 适用状态 |
| `internal_timing_checks.tsv` | 五项内部时序完整性检查的问题数量 |
| `implementation_checks.tsv` | 布线、严重 DRC、时钟与路径数量，以及最终检查结果 |
| `required_post_route_drc.rpt` | 必须通过的严重 DRC 规则结果 |
| `required_clock_checks.rpt` | 必须通过的内部时序检查原始报告 |
| `effective_timing.xdc` | 当前设计中的有效时序约束 |
| `timing_exceptions.rpt` | 当前设计的时序例外摘要 |

统计使用 `get_timing_paths` 的实际 clock 对象选择捕获端点，逐步扩大查询数量，直至完整结果小于查询上限。每个端点保留最差裕量；WNS 为其中的最小值，TNS 为所有负裕量之和。hold 字段对应 Vivado 原生报告的 WHS/THS。跨时钟路径同样计入其捕获时钟的结果。

`single_cycle_setup_fmax_estimate_mhz` 按当前布线结果计算 `1000 / (周期 − setup WNS)`，只用于同一时钟、同一边沿、普通单周期路径。存在跨时钟、外部输入或输出路径、跨边沿路径、非单周期要求、路径例外，或者有效约束包含 `set_multicycle_path`、`set_max_delay` 时，该字段留空，原因写入 `fmax_status`。跨时钟、外部端口和跨边沿关系均单独查询，覆盖同一端点的次差路径。Fmax 估算独立于 setup/hold 的通过条件；所有实际路径仍按已有约束检查。

板级 `run_batch_impl.tcl` 和 `export_project.tcl` 的实现入口使用相同检查，并在检查通过后生成比特流。生产 RTL 文件列表覆盖帧地址准备、量化运算通道及量化输入队列。RTL 直接综合入口 `vivado_synth_soc.tcl` 生成综合报告；目标器件布线后的时序由上述实现入口检查。

上述 API 与统计定义对应 AMD 的 [report_route_status](https://docs.amd.com/r/2023.2-English/ug835-vivado-tcl-commands/report_route_status)、[check_timing](https://docs.amd.com/r/2023.2-English/ug835-vivado-tcl-commands/check_timing)、[get_timing_paths](https://docs.amd.com/r/2023.2-English/ug835-vivado-tcl-commands/get_timing_paths) 和 [write_xdc](https://docs.amd.com/r/2023.2-English/ug835-vivado-tcl-commands/write_xdc) 命令说明。

可在具备 Tcl 的环境执行脚本检查：

```sh
python3 scripts/fpga/tests/test_vivado_timing.py \
  --out build/vivado_timing_checks --picorv32 /path/to/picorv32
python3 fpga/vivado/tflm_ai_dsa_soc/scripts/test_npu_config.py \
  --out build/vivado_configuration_checks --picorv32 /path/to/picorv32
```

这些测试检查 Tcl 语法、Vivado 命令调用、结果判断、端点统计和生产源文件完整性，使用模拟命令提供设计对象。测试报告分别记录这些检查与实际 Vivado 执行状态。本次环境没有可调用的 Vivado，实际 Vivado 布局布线尚未执行；执行生产实现需要包含 Artix-7 器件支持的 Vivado 环境、对应固定源码的原语网表，以及实际封装和接口约束。

[脚本验证结果](data/vivado_timing_validation.json) 保存通过的 40 项测试、173 次 Tcl 调用及源码 SHA-256。Vivado 列表中的 79 个文件覆盖 `dut_axil.f` 所需的 64 个生产文件；该比较排除仿真包装 `axil_top_with_ram.sv`。

### CARRY 专用输入

`scripts/fpga/patches/nextpnr_xilinx_carry_direct_di.patch` 为记录版本的 `nextpnr-xilinx` 增加 `XC7_CARRY_DIRECT_DI=1` 选项。满足连接条件的 CARRY `DI` 直接使用对应位置的 X 输入，保留真实信号及常量连接。动态 `CYINIT` 与 `DI[0]` 共用 AX 时必须为同一个信号。

补丁允许六输入或具有其他使用者的 S LUT 使用对应 CARRY 位置，同时将 X 输入占用交给原有布局检查。拆分 CARRY 时同步保留真实 DI 和补齐位置的 X 输入占用，仅调整属于该进位组的 LUT 位置关系。FF、存储器、SRL 与选择器的输入冲突继续执行合法性检查。

```sh
git -C /path/to/nextpnr-xilinx apply \
  /path/to/repository/scripts/fpga/patches/nextpnr_xilinx_carry_direct_di.patch \
  /path/to/repository/scripts/fpga/patches/nextpnr_xilinx_dsp_dram_timing.patch \
  /path/to/repository/scripts/fpga/patches/nextpnr_xilinx_lut_packing.patch
cmake --build /path/to/nextpnr-xilinx/build --target nextpnr-xilinx -j2
XC7_CARRY_DIRECT_DI=1 XC7_FRACTURE_LUTS=1 python3 scripts/fpga/open_fpga_implementation.py \
  --mapped build/open_soc/soc_top/mapped.json \
  --nextpnr /path/to/nextpnr-xilinx/build/nextpnr-xilinx \
  --chipdb /path/to/chipdb-xc7a200tfbg484-3.bin \
  --soc-package-pins /path/to/prjxray-db/artix7/xc7a200tfbg484-3/package_pins.csv \
  --out build/open_soc_implementation --freq 150 --allow-timing-failure
```

组合验证覆盖常量、独立动态和共用动态 `CYINIT`、六输入 S LUT、S 输出的多个使用者，以及完整打包、布局、布线。对于保持原 CARRY 实例的验证电路，`check_carry_connections.py` 还检查输入信号及缓冲 LUT 的恒等关系。

### CARRY 尾部输入

`scripts/fpga/patches/nextpnr_xilinx_carry_tail.patch` 增加 `XC7_CARRY_TRIM_TAIL=1`。打包器检查每个 `CARRY4` 的全部 `O` 和 `CO` 使用者，只解除最高有效输出位以上的 `S`、`DI` 连接。`CI`、`CYINIT`、有效位和共享净信号的其他使用者保持原连接。具有固定 BEL 的单元继续保持其输入连接。

该变换减少不可观察高位所需的常量与输入转接 LUT。验证使用 Yosys 和 Xilinx Unisim 两套原语模型，覆盖任意输出掩码、未定义尾部替代值及跨 CARRY 的 `CI`、`CYINIT` 连接。实际 C++ 连接操作另检查 65,536 种连接形状、4,096 种进位连接、513 个跳过条件以及六个共享信号情况。

```sh
python3 scripts/fpga/test_carry_tail.py --out build/carry_tail_formal
python3 scripts/fpga/tests/review_carry_tail.py \
  --nextpnr /path/to/nextpnr-xilinx \
  --vendor-model /path/to/XilinxUnisimLibrary/verilog/src/unisims/CARRY4.v \
  --worker scripts/fpga/open_fpga_synth.py --out build/carry_tail_review
python3 scripts/fpga/tests/run_carry_tail_implementation.py \
  --nextpnr /path/to/nextpnr-xilinx/build/nextpnr-xilinx \
  --source /path/to/nextpnr-xilinx/xilinx \
  --chipdb /path/to/chipdb-xc7a200tfbg484-3.bin \
  --package-pins /path/to/prjxray-db/artix7/xc7a200tfbg484-3/package_pins.csv \
  --tilegrid /path/to/prjxray-db/artix7/xc7a200t/tilegrid.json \
  --out build/carry_tail_implementation
```

实现测试包含动态进位级联和保留的共享尾部信号。参考与优化版本均完成合法布局和布线，物理 LUT 位置分别为 37 与 26。每个版本穷举 256 组输入并核对 14 个寄存器输入，另逐项核对实际导出的 LUT INIT、九个进位入口选择及 14 个触发器输入选择。完整结果、原语来源和工具摘要见 [nextpnr_carry_tail_validation.json](data/nextpnr_carry_tail_validation.json)。

### 普通 LUT 共用物理位置

`scripts/fpga/patches/nextpnr_xilinx_lut_packing.patch` 增加 `XC7_FRACTURE_LUTS=1` 选项。单输出、至多五个输入的普通逻辑可以使用 `5LUT` 位置，并与同位置 `6LUT` 共用五个物理输入。输入净信号先去重，再检查并集；重复连接不会增加可用输入数量。真实第六个逻辑输入、双输出单元、存储器和 SRL 继续使用各自的专用规则。

布局后的输入排列与 O5/O6 输出选择由实际 `fixupPlacement` 和 FASM INIT 函数处理。保存和重新读取阶段文件后仍检查输入并集、端口来源与输出资源。O5、进位输出和 5FF 的外部输出共同使用每个位置的输出选择器，使用者必须满足本地物理连接条件；FF 控制端、其他位置的 CARRY 输入和 LUT 反馈均计入外部连接。专用 COUT 只允许 CO3 连接一个相邻 CIN。

布局移动同时检查源位置与目标位置，保持两个位置的输出选择器和其他资源均合法。验证覆盖空目标、交换目标以及失败移动后的绑定和共享评分恢复。

以下程序从实际后端源码提取函数并编译执行，检查输入重排、INIT、位置限制和输出连接。

```sh
python3 scripts/fpga/tests/review_lut_packing.py \
  --source /path/to/nextpnr-xilinx/xilinx --out build/lut_packing_logic
python3 scripts/fpga/tests/review_outmux_edges.py \
  --source /path/to/nextpnr-xilinx/xilinx --out build/lut_packing_outputs
python3 scripts/fpga/tests/review_placer_moves.py \
  --nextpnr /path/to/nextpnr-xilinx --out build/lut_packing_moves
python3 scripts/fpga/tests/run_lut_packing_implementation.py \
  --nextpnr /path/to/nextpnr-xilinx/build/nextpnr-xilinx \
  --source /path/to/nextpnr-xilinx/xilinx \
  --chipdb /path/to/chipdb-xc7a200tfbg484-3.bin \
  --out build/lut_packing_implementation
```

实际实现测试包含五个共用输入、六个独立输入、带重复端口的六个输入，以及带重复端口的三个输入。合格用例完成布局布线，并逐引脚和真值表核对原逻辑；两类六输入共用位置被布局检查拒绝。`--through place` 可仅运行到布局。

验证结果保存于 [nextpnr_lut_packing_validation.json](data/nextpnr_lut_packing_validation.json)，其中包含源码摘要、42,395,008 次普通 LUT 输出检查、20,480 次 `LUT6_2` 输出检查、位置与输出资源边界检查，以及实际布线后的函数检查。

### 普通 LUT 相对位置配对

`scripts/fpga/pair_packed_luts.py` 从打包后的 JSON 中选择带普通逻辑标记、没有既有位置约束的单输出 LUT。候选使用至多五个输入引脚，排除 RAM、SRL，以及直接驱动触发器、进位单元和专用多路选择器的逻辑。每对至少共享一个非常量输入，输入净信号并集至多五个，两个输出没有直接驱动另一侧输入。选择时优先共享更多输入的组合。

程序仅添加根单元和子单元之间的相对位置关系，子单元 `Z` 偏移为 1，根单元可使用任意一组 `6LUT/5LUT`。连接、INIT、其他属性和原有约束保持，并对修改前后的单元内容核对 SHA-256。放置后的输出端口与物理输入排列由已经验证的后端处理。

```sh
python3 scripts/fpga/pair_packed_luts.py \
  --packed build/open_impl/packed.json \
  --out build/open_pair/paired.json --report build/open_pair/pairing.json
python3 scripts/fpga/tests/test_pair_packed_luts.py -v
python3 scripts/fpga/tests/run_lut_pair_implementation.py \
  --nextpnr /path/to/nextpnr-xilinx/build/nextpnr-xilinx \
  --source /path/to/nextpnr-xilinx/xilinx \
  --chipdb /path/to/chipdb-xc7a200tfbg484-3.bin \
  --tilegrid /path/to/prjxray-db/artix7/xc7a200t/tilegrid.json \
  --out build/lut_pair_implementation
```

配对后的 JSON 由 nextpnr 使用 `--no-pack` 继续放置。验证包含四种输入组合：两类五个以内的共享输入各使用一个物理 LUT，两类六输入组合各保持两个物理 LUT。两个配对用例完成实际布线、逐引脚真值表检查和导出的 FASM INIT 核对。结果保存于 [nextpnr_lut_pair_validation.json](data/nextpnr_lut_pair_validation.json)。

候选对数用于安排实现比较。最终节省的物理位置及线长变化取自相同网表、约束、器件和随机种子的完整合法布局结果。

### 六输入函数与零余因子共享

`fuse_lut_cofactors.py` 在映射后的普通逻辑中查找六输入函数及其零余因子。设六输入函数为 `F(x0, x1, x2, x3, x4, s)`，当另一函数与 `F(x0, x1, x2, x3, x4, 0)` 完全相同时，两者可用一个 `LUT6_2` 的 O6 和 O5 输出。工具逐个尝试选择变量，并对每个候选穷举 64 种输入，检查两个输出。下半函数允许使用共同五个输入的子集，输入次序按真值表重新排列。

候选必须是连接完整、INIT 已定义的普通 LUT，输入为不同的动态净信号。工具保留两个输出净信号，排除物理约束、保持属性、直接反馈以及进位、专用多路选择器和存储单元的直接使用者。源文件信息保存在合并单元中，报告保存原始真值表、选择变量、共同输入、输出及文件摘要。

`nextpnr_xilinx_lut_cofactor.patch` 增加 `XC7_LUT_COFACTOR=1` 选项，使原生 `LUT6_2` 的真实第六输入保持在 A6。两半共同使用 A1 至 A5，下半没有 A6 端口。布局和布线后均检查共同输入、端口来源及 INIT 的低 32 位；布线允许共同五个输入重新排列，保留 A6 的恒等连接。输出选择器、触发器、进位及其他资源的合法性检查继续执行。

```sh
python3 scripts/fpga/fuse_lut_cofactors.py \
  --mapped build/open_soc/soc_top/mapped.json --top soc_top \
  --out build/open_soc_cofactor/mapped.json \
  --report build/open_soc_cofactor/fusion.json
XC7_LUT_COFACTOR=1 XC7_FRACTURE_LUTS=1 \
python3 scripts/fpga/open_fpga_implementation.py \
  --mapped build/open_soc_cofactor/mapped.json \
  --nextpnr /path/to/nextpnr-xilinx/build/nextpnr-xilinx \
  --chipdb /path/to/chipdb-xc7a200tfbg484-3.bin \
  --soc-package-pins /path/to/prjxray-db/artix7/xc7a200tfbg484-3/package_pins.csv \
  --out build/open_soc_cofactor/implementation --through route
```

验证包括六种选择变量位置、一至五个下半输入、输入反序、共同输入重复和第六输入复用。三组参考与共享设计共完成六次实际布局布线，每组均由 14 个物理 LUT 位置减少到 7 个。每份已布线设计检查 256 组输入、14 个寄存器数据位及实际 FASM 的 INIT 和输入选择。C++ 检查直接编译后端函数，覆盖 154 种合法配置、50 种不兼容配置和 19,712 次输出比较。结果见 [nextpnr_lut_cofactor_validation.json](data/nextpnr_lut_cofactor_validation.json)。

```sh
python3 scripts/fpga/tests/test_fuse_lut_cofactors.py
python3 scripts/fpga/tests/review_lut_cofactor.py \
  --source /path/to/nextpnr-xilinx/xilinx --out build/lut_cofactor_cpp
python3 scripts/fpga/tests/run_lut_cofactor_implementation.py \
  --nextpnr /path/to/nextpnr-xilinx/build/nextpnr-xilinx \
  --source /path/to/nextpnr-xilinx/xilinx \
  --chipdb /path/to/chipdb-xc7a200tfbg484-3.bin \
  --package-pins /path/to/prjxray-db/artix7/xc7a200tfbg484-3/package_pins.csv \
  --tilegrid /path/to/prjxray-db/artix7/xc7a200t/tilegrid.json \
  --out build/lut_cofactor_fused --fuse-mapped
```

省略 `--fuse-mapped` 可检查原生 `LUT6_2`，增加 `--repeated-inputs` 可检查重复输入。整机节省量由完成的合法布局统计。

### 进位输入 LUT 的空闲 O5

`pair_carry_luts.py` 在已有进位组中寻找可共享的位置。S 输入必须由至多五个输入的普通 LUT 驱动，DI 使用对应的 X 输入。该位置的 5LUT 和 5FF 未被现有相对约束占用，进位输出只进入同位置的 6FF 数据端或专用 CO3/CIN 后继。新增逻辑的输入并集最多为五个，输出经空闲 OUTMUX 进入普通布线。

工具将独立逻辑作为 S 输入 LUT 的子单元，设置相对 `Z=1`。原有 CARRY、S 输入 LUT、寄存器及其子单元的位置约束保持。默认只选择具有公共非常量输入的候选；提供已完成的布局后，可选择邻近的兼容逻辑，并要求其原物理位置只有一个 LUT 单元。

```sh
python3 scripts/fpga/pair_carry_luts.py \
  --packed build/open_soc_physical/paired.json \
  --placement-guide build/open_soc_physical/placed.json \
  --maximum-site-distance 8 \
  --out build/open_soc_physical/carry_paired.json \
  --report build/open_soc_physical/carry_pairing.json
```

距离使用 `SLICE_X...Y...` 坐标的曼哈顿距离，用于限制候选移动范围。随后重新运行完整布局和布线，检查实际资源与延迟。

```sh
python3 scripts/fpga/tests/test_pair_carry_luts.py
python3 scripts/fpga/tests/run_carry_lut_pair_implementation.py \
  --nextpnr /path/to/nextpnr-xilinx \
  --source /path/to/nextpnr-xilinx/xilinx \
  --chipdb /path/to/chipdb-xc7a200tfbg484-3.bin \
  --package-pins /path/to/prjxray-db/artix7/xc7a200tfbg484-3/package_pins.csv \
  --tilegrid /path/to/prjxray-db/artix7/xc7a200t/tilegrid.json \
  --out build/carry_lut_pair_implementation
```

实际验证包含共享输入和按 SLICE 距离选择的两种配对，均增加四对相对位置约束。参考设计占用 16 个物理 LUT 位置，两种配对结果均为 11 个。三个已布线网表分别完成 256 组输入、14 个寄存器数据位的 3,584 次数值比较，并核对实际 FASM 的 LUT INIT、进位入口和触发器输入选择。新增共享位置的 DI 路由分别为 AX、BX、CX、DX，OUTMUX 选择 O5。紧凑结果保存在 [nextpnr_carry_lut_pair_validation.json](data/nextpnr_carry_lut_pair_validation.json)。

### 相对位置组与逻辑输入编号

`nextpnr_heap_cluster_connectivity.patch` 递归检查相对位置组的所有子单元。只要任意成员具有有效网络连接，整个组就共同参与分析布局和合法位置分配。这包括根 LUT 的输出没有使用者、子 LUT 仍承担逻辑，以及只有第二层子单元触发器具有有效连接的结构。

`nextpnr_lut_logical_pin_mapping.patch` 在共享 LUT 位置的输入重新排列时，保留 `X_ORIG_PORT_A1` 至 `X_ORIG_PORT_A6` 中的原逻辑引脚编号和重复输入关系。原 INIT 使用原有位序，物理输入可以重新排列。输入编号存在间隔时，其逻辑含义保持不变。

实际实现测试覆盖常量输出、稀疏逻辑输入、有效 O5/O6 输出和两层子单元。每个案例均执行打包、布局与布线，并核对全部单元的唯一 BEL、全部输出真值、实际 C++ 产生的物理 INIT 和 FASM 配置。

```sh
python3 scripts/fpga/tests/run_lut_cluster_connectivity.py \
  --nextpnr /path/to/nextpnr-xilinx \
  --source /path/to/nextpnr-xilinx/xilinx \
  --chipdb /path/to/chipdb-xc7a200tfbg484-3.bin \
  --package-pins /path/to/prjxray-db/artix7/xc7a200tfbg484-3/package_pins.csv \
  --tilegrid /path/to/prjxray-db/artix7/xc7a200t/tilegrid.json \
  --out build/lut_cluster_connectivity --with-output-regressions
```

完整 SoC 使用逐单元检查器比较布局前后的普通逻辑 LUT。检查内容包括单元集合、原类型、INIT、所有逻辑输入及输出对应的网络别名，以及共享物理位置的输入一致性。输入文件可以直接使用 gzip 压缩格式。

```sh
python3 scripts/fpga/tests/check_lut_logical_pin_mapping.py \
  --packed build/open_soc_physical/paired.json \
  --physical build/open_soc_physical/placed.json \
  --out build/open_soc_physical/logical_lut_mapping.json
```

验证结果见 [nextpnr_lut_cluster_validation.json](data/nextpnr_lut_cluster_validation.json)。工具清单保存实际二进制和相关 C++ 源码的 SHA-256。

### DSP 位置与存储器读口

`scripts/fpga/patches/nextpnr_xilinx_dsp_dram_timing.patch` 为级联 DSP 保留相邻位置关系，允许独立 DSP 使用同一 tile 的上下两个 DSP 位置。器件 DSP 容量与级联连接要求保持不变。

`RAM32M` 和 `RAM64M` 的 A、B、C 读口在输出完全没有使用者、读地址无驱动时使用零地址。D 口地址控制写入，保持原连接。官方存储模型的状态与其他读输出使用时序归纳证明检查。

```sh
python3 scripts/fpga/test_unused_dram_read_ports.py --out build/unused_dram_read_proof
```

实现脚本在打包、布局和布线阶段均启用 `--strict-timing-graph`，要求所有组合时序依赖完成拓扑遍历。时序图检查与目标器件延迟模型的覆盖情况分别记录。

`--allow-timing-failure` 允许保留未满足频率约束的布线结果和报告，约束仍为 150 MHz。当前 Project X-Ray 数据库具有一组时序数据，目标速度等级、DSP 与时钟相关的延迟覆盖需要进一步补充；脚本将频率确认字段保留为空。150 MHz 确认使用完整目标器件时序模型及布线后的时序分析。

所记录版本的开源后端具有以下时序模型覆盖情况。

| 对象 | 当前模型 |
| --- | --- |
| LUT、CARRY、级联选择器 | 从器件数据库读取组合延迟 |
| Slice 触发器 | setup、hold、clock-to-Q 各使用固定 0.1 ns |
| BUFGCTRL | 输入到输出使用固定 0.2 ns |
| 全组合 DSP48E1 | 使用按输入类型划分的保守固定延迟 |
| 启用内部寄存器的 DSP48E1 | 尚未纳入完整时序分析 |
| 块 RAM | 尚未纳入完整时序分析 |
| 目标速度等级 | 数据库包含一组时序数据，需要确认其与 `-3` 等级的对应关系 |

工具版本与数据库来源记录在 [open_fpga_tools.json](data/open_fpga_tools.json)。物理计数检查可运行：

```sh
python3 scripts/fpga/test_placed_resources.py -v
```

DSP、`RAMB36E1`、`RAMB18E1`、进位单元和触发器分别统计。比较不同方案时应保持计算阵列、缓存容量、总线宽度、CPU 存储器和功能配置一致。

## 模块资源分布

扁平化和全局 LUT 映射会合并跨模块逻辑。`module_resources.py` 使用保留的 RTL 来源、原始寄存器信号声明与实例名，以及存储与算术单元连接分配 LUT。寄存器单元只保留技术库来源时，从 `pre_lut.il` 的 Q 信号声明恢复 RTL 文件。公共存储封装的资源归入最近的可识别功能模块。一个 LUT 的所有可达使用模块一致时，将其计入该模块；多个模块共享的组合逻辑及无法分类的单元单独列出。各分类之和等于综合逻辑 LUT 总数。

```sh
python3 scripts/fpga/module_resources.py \
  --netlist build/open_soc/soc_top/mapped.json \
  --pre-lut build/open_soc/soc_top/pre_lut.il \
  --out build/open_soc/soc_top/module_resources.json
```

该报告用于选择下一轮优化模块。物理 LUT 总占用继续取自合法布局结果。

## 寄存器之间的组合路径

`netlist_metrics.py` 根据实际连接构建按位有向图，从时钟控制的存储输出查找至同步数据或控制输入的最长路径。报告列出起点、终点、经过的单元和连接名称。综合流程从 `pre_lut.il` 恢复触发器对应的 RTL 寄存器名，并按不同算术段保存路径分组，便于定位多个模块的较长路径。

分析考虑以下结构：

- `LUT6_2` 的 `O5` 仅依赖 `I0` 至 `I4`，`O6` 还依赖 `I5`。
- `CARRY4` 按从低位到高位的进位方向确定输入与输出关系。
- 分布式 RAM 和 SRL 的异步地址选择进入组合路径，写入数据以时钟为分隔。
- DSP 启用的寄存器形成时钟分隔；输入、内部寄存器和输出之间实际经过的每段算术计为一个 DSP 组合单元。直接连接寄存器的输出计为零个算术单元。
- 对控制为常量的 `ONE48`、`A:B` 与 `C` 纯 ALU 运算，`P` 和 `PCOUT` 的每一位只依赖同位及更低位操作数。该关系已使用官方 `DSP48E1` 模型对全部 48 种低位宽度和任意 `ALUMODE` 完成形式证明。其他 DSP 配置继续保留保守依赖。
- 外部输入直接形成的组合路径不记为寄存器之间的路径。

`remap_fpga_luts.py` 另外保存 `fanout.json`，按实际单元输入引脚统计高扇出信号，分别列出时钟负载、控制负载以及每类最长路径中的高扇出连接。`summary.json` 记录 ABC 各轮映射延迟成本和 6667 ps 目标的满足情况；该数值用于比较映射选择，布线后的完整器件时序另行检查。

`graph_complete` 表示分析器是否识别全部相关单元且不存在组合环路。`longest_register_path_cells` 是结构级数，包含进位单元及可能存在的未寄存 DSP 运算。它不包含单元延迟或连线延迟。完整 SoC 必须使用器件、封装、速度等级和全部所用单元的有效时序模型检查 6.667 ns 要求。

`register_path_requirement` 保存 15 个组合单元的限制、实际最长路径以及检查结果。路径图完整时，`met` 按实际单元数是否不超过 15 计算；路径图未完成时该字段为空。同步数据输入和使能等同步控制输入均纳入检查。报告同时保留完整起止点、逐单元连接及 LUT、CARRY、DSP 等类型，供各模块缩短实际组合路径。

可单独分析已保存的网表：

```sh
python3 scripts/fpga/netlist_metrics.py build/open_soc/soc_top/mapped.json \
  --top soc_top --out build/open_soc/soc_top/metrics.json \
  --register-origins build/open_soc/soc_top/pre_lut.il
python3 scripts/fpga/test_netlist_metrics.py -v
python3 scripts/fpga/test_dsp_alu_bit_dependencies.py --out build/dsp_alu_bit_dependencies/formal
```

[DSP 按位依赖验证结果](data/dsp_alu_bit_dependencies_validation.json) 同时保存 48 组算术关系证明与 9 组实际内部寄存器边界检查。组合级数和器件延迟分别记录，150 MHz 要求继续通过完整器件时序检查确认。

## 增加独立模块测量

`--case-config` 接受一个 JSON 文件，其内容按测量名称组织。以下示例测量 16 通道、64 位总线的写回模块：

```json
{
  "writeback_check": {
    "top": "vector_writeback",
    "options": ["-GTILE=16", "-GBUS_WIDTH=64"],
    "sources": ["rtl/npu/conv/vector_writeback.sv"],
    "configuration": "16 lanes, 64-bit bus"
  }
}
```

```sh
python3 scripts/fpga/open_fpga_synth.py --case-config cases.json \
  --cases writeback_check --source-root /path/to/worktree --out build/writeback_check
```

## 已保存的模块参考数据

[模块参考数据](data/open_fpga_reference.json) 保存提交 `c3712e54` 的独立模块结果及对应源码 SHA-256，可用于检查工具版本与参数。该文件中的完整 NPU 统计包含 69,871 个逻辑 LUT、45,171 个触发器和 390 个 DSP48E1。新的完整 SoC 测量应使用本页给出的固定配置，并保存自身的资源与时序结果。
