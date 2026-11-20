# FPGA 优化版本的恢复与运行

本轮开发分支为 `optimize/rtl-45000`，逐提交补丁的起始版本为 `b24976b7f51b8db7b9299bf0afcd5f63b5f0250c`。交接包标签为 `rtl45000`。包内 `manifest.json` 记录实际固定提交、源码树、补丁顺序、历史参考提交、子模块版本和测量来源。

以下命令在恢复后的仓库根目录执行；恢复脚本在解压后的交接包目录执行。`/path/to/...` 应替换为本机路径。每轮验证使用独立输出目录，并保持被测源码不变。

## 恢复完整提交历史与子模块

交接包包含以下内容：

| 文件或目录 | 用途 |
| --- | --- |
| `source.bundle` | 完整提交历史及验证脚本引用的历史提交 |
| `patches/`、`series` | 按顺序排列的完整二进制补丁 |
| `commits/` | 原始 Git 提交对象，包含作者、提交者、时间、说明和父提交 |
| `external/` | PicoRV32 等子模块的独立 bundle |
| `source.tar.gz`、`combined.patch` | 源码快照及相对起始提交的完整差异 |
| `manifest.json`、`checksums.json` | 版本清单与包内文件的 SHA-256 |
| `measurement.json`、`results/` | 导出时收入的测量记录及原始结果 |
| `CHANGES.md`、`NEXT_STEPS.md` | 提交内容与复测、器件时序检查说明 |

完整等价检查会读取历史参考版本，应使用以下任一恢复方式建立工作目录。

### 直接恢复 bundle

在交接包目录执行，目标目录须尚未存在：

```sh
./restore_bundle.sh --destination /path/to/restored_soc
```

脚本检查包内文件摘要，恢复完整 Git 历史、固定提交及 PicoRV32 子模块，并核对最终提交、源码树和工作目录状态。恢复结果记录在 `/path/to/restored_soc.recovery.json`。

恢复脚本使用分离的 `HEAD`。在新建的独立仓库中继续开发时，可创建本轮分支：

```sh
git -C /path/to/restored_soc switch -c optimize/rtl-45000
git -C /path/to/restored_soc rev-parse HEAD
git -C /path/to/restored_soc/picorv32 rev-parse HEAD
```

### 逐提交应用补丁

```sh
./apply_patches.sh --destination /path/to/restored_soc_patches
```

该方式按 `series` 顺序应用全部补丁，逐项检查源码树，并恢复对应的原始 Git 提交对象，因此每一步保留原提交标识。脚本随后导入完整历史参考提交并恢复子模块。

已有仓库包含本轮起始提交时，可在独立工作树中执行同样的恢复：

```sh
./apply_patches.sh \
  --repository /path/to/mini_tflm_dsa \
  --destination /path/to/restored_soc_worktree
```

`restore_bundle.sh` 同样支持 `--repository`。使用已有仓库时，恢复目录保持分离的 `HEAD`；需要继续开发可另建未被占用的分支。

包内恢复脚本直接使用 `external/` 中的子模块 bundle。通过普通 Git 克隆获得源码时，使用仓库记录的 PicoRV32 版本：

```sh
git submodule update --init picorv32
```

## 工具环境

综合环境使用 `pyosys==0.71.post40`。完整 NPU 仿真使用 Verilator Python 分发包 `5.48.0`、GCC 14.2.0 和 GNU Make；该 Verilator 的 `--version` 输出为 `rev vUNKNOWN-built20260516-4e853d8`。安装命令还需要 Git 和 `patch`。四态存储检查使用 Icarus Verilog 12.0。

以下示例在独立 Python 环境与工具目录安装依赖，并应用 GCC 的 C++20、协程及预编译头文件配置：

```sh
python3 -m venv /path/to/tools/python
. /path/to/tools/python/bin/activate
python3 -m pip install pyosys==0.71.post40
python3 -m pip install --target /path/to/tools/verilator verilator==5.48.0
patch -d /path/to/tools/verilator/verilator -p1 \
  < scripts/fpga/patches/verilator_5_48_gcc.patch

export VERILATOR_ROOT=/path/to/tools/verilator/verilator
export VERILATOR_BIN="$VERILATOR_ROOT/bin/verilator_bin"
"$VERILATOR_ROOT/bin/verilator" --version
```

物理实现还需要 `nextpnr-xilinx`、目标器件数据库和封装引脚文件。对应工具补丁、编译方法、功能检查和器件模型说明见 [开源 FPGA 综合与资源分析](open_fpga_synthesis.md)。工具版本和文件摘要随实际测量保存。

## 完整 NPU 回归

完整回归统一使用 `test/requant_time_share/run_npu.py`：

```sh
python3 test/requant_time_share/run_npu.py \
  --out build/rtl45000_npu \
  --verilator "$VERILATOR_ROOT/bin/verilator" \
  --jobs 1 --build-timeout 7200
```

入口构建实际 FPGA 分支的生产 NPU，加载官方器件原语功能模型，依次执行功能、容量、输出和分块数据排列任务。各类任务复用同一仿真程序，同时检查权重提交、帧地址准备、量化组预留及配置保持。

输出目录中的 `summary.json` 保存源码摘要、仿真程序清单、各任务测量值，以及组预留和配置覆盖。比较两个版本时，应逐项核对任务集合、全部 `measurements` 字段、周期统计及两类覆盖记录。详细测试说明见 [分时量化与完整 NPU 验证](../test/requant_time_share/README.md)。

## 结构、容量与 ASIC 存储检查

```sh
python3 test/ps_channels/run_npu_structure.py \
  --out build/rtl45000_structure \
  --verilator "$VERILATOR_ROOT/bin/verilator"

python3 test/capacity/check_elaboration.py \
  --config config/npu_fpga.mk \
  --verilator "$VERILATOR_ROOT/bin/verilator" \
  --output-root build/rtl45000_capacity

python3 -m unittest discover -s test/capacity -p 'test_*.py'

python3 test/requant_group_buffer_asic/check_structure.py \
  --out build/rtl45000_asic_structure

python3 test/requant_group_buffer_memory/run.py \
  --out build/rtl45000_asic_memory \
  --verilator "$VERILATOR_ROOT/bin/verilator" --jobs 1

python3 test/requant_group_buffer_memory/run_control.py \
  --out build/rtl45000_asic_control

python3 test/requant_group_buffer_npu/run.py \
  --source-root "$PWD" --out build/rtl45000_asic_npu

python3 -m unittest discover -s test/asic_requant_storage -p 'test_*.py'
```

生产 NPU 结构检查核对实际 FPGA 分支的存储容量、部分和通道、256 个阵列计算单元和 8 路向量 PE。容量检查根据 `config/npu_fpga.mk` 核对实际展开的数组及配置模型。

ASIC 检查展开量化整行缓冲的 SRAM 宏，检查全部数据位、完成标志、填充位写掩码、读写地址和使能连接。完整 NPU 检查使用真实 DC 源文件准备流程，在实际量化模块层次核对存储和计算单元。功能比较使用保存完整存储内容的同步模型；归纳检查覆盖预留计数、循环地址和同地址读写互斥。工艺库链接及器件时序检查使用 ASIC 综合流程中的实际库文件。

具体参数范围和结果格式见 [容量检查](../test/capacity/README.md)、[固定部分和通道](../test/ps_channels/README.md)、[量化缓冲 ASIC 结构](../test/requant_group_buffer_asic/README.md)、[完整 NPU 的 ASIC 结构](../test/requant_group_buffer_npu/README.md)及[SRAM 功能与控制验证](../test/requant_group_buffer_memory/README.md)。

## 模块等价与数值检查

各测试目录保存输入生成、参考计算、逐周期比较、形式证明和独立综合入口。

| 检查对象 | 入口或说明 |
| --- | --- |
| 公共 `regfile` | [存储检查脚本](../test/regfile/run.py) |
| 前端、缓存与加载器的 FPGA 等价 | [完整模块形式比较](../test/frontend_rtl_structure/README.md) |
| 卷积缓存存储与填充范围 | [缓存存储](../test/cache_storage/README.md)、[填充上界](../test/cache_fill_range/README.md) |
| DMA 描述符存储与写入布局 | [描述符存储](../test/dma_context_storage/README.md)、[DMA 输出性质](../test/dma_byte_layout/README.md) |
| IA 数据写入 | [生产 DMA 输入布局](../test/ia_write_layout/README.md) |
| 权重加载计数与候选比较 | [计数路径](../test/kernel_count_paths/README.md)、[候选字段](../test/kernel_candidate_fields/README.md) |
| 阵列数据选择与计算 | [计算模块 RTL 验证](../test/compute_rtl/README.md) |
| 分时量化与整行存储 | [分时量化](../test/requant_time_share/README.md)、[整行 SRAM](../test/requant_group_buffer_memory/README.md) |

按各测试说明选择对应参考提交、参数和输出目录。历史参考提交由完整交接包保存，重新测量时保留命令、源文件摘要及结果报告。

## 完整 SoC 资源与组合路径

以下命令使用本轮的 DSP 选择和 LUT 面积成本配置。完整 SoC 的生产参数由脚本和 `config/npu_fpga.mk` 核对。

```sh
python3 scripts/fpga/open_fpga_synth.py --cases soc_top \
  --out build/rtl45000_pre --through pre_lut \
  --wide-alu-dsp-budget 740 --wide-alu-minimum-width 8 \
  --wide-alu-maximum-chain 1 \
  --lock-file /tmp/mini_tflm_dsa_synthesis.lock

python3 scripts/fpga/test_wide_alu_dsp.py \
  --selected-netlist build/rtl45000_pre/soc_top/pre_alu.json \
  --selection build/rtl45000_pre/soc_top/wide_alu_mapping.json \
  --out build/rtl45000_dsp_formal

python3 scripts/fpga/remap_fpga_luts.py \
  --source build/rtl45000_pre/soc_top \
  --out build/rtl45000_mapped/soc_top \
  --mode physical-cost --small-lut-area-cost 0.75 \
  --max-lut-inputs 6 --wire-delay-ps 500 --delay-target-ps 6667 \
  --lock-file /tmp/mini_tflm_dsa_synthesis.lock

python3 test/soc_rtl_optimization/run_physical.py \
  --source build/rtl45000_mapped/soc_top \
  --out build/rtl45000_physical \
  --nextpnr /path/to/nextpnr-xilinx \
  --chipdb /path/to/chipdb-xc7a200tfbg484-3.bin \
  --package-pins /path/to/prjxray-db/artix7/xc7a200tfbg484-3/package_pins.csv
```

`remap_fpga_luts.py` 保存组合功能验证、资源数量和完整寄存器间路径。`run_physical.py` 完成 LUT 配对、合法布局和逻辑引脚检查，物理资源写入 `resources.json`。

三项目标分别检查：合法布局中的物理 LUT 位置不超过 45,000；最长寄存器间路径不超过 15 个组合单元；目标器件在 6.667 ns 周期下满足布局布线时序要求。物理 LUT 数包含逻辑、分布式 RAM 和 SRL 使用的位置。150 MHz 器件时序按照 [开源 FPGA 综合与资源分析](open_fpga_synthesis.md)中的布线及完整时序模型流程确认。

`--resume` 用于继续输入和工具摘要均一致的阶段。中间文件压缩、已保存展开结果复用、器件工具补丁和各类报告字段也见该说明。

## 导出完整交接包

最终测量记录使用 `docs/data/fpga_rtl45000_measurements.json` 中的 `rtl45000_final`。完成对应测量并生成该记录后，执行：

```sh
python3 scripts/fpga/export_checkpoint.py \
  --ref optimize/rtl-45000 \
  --base b24976b7f51b8db7b9299bf0afcd5f63b5f0250c \
  --label rtl45000 --kind physical-45000 \
  --measurement-file docs/data/fpga_rtl45000_measurements.json \
  --measurement-name rtl45000_final \
  --next-steps docs/fpga_next_optimization.md \
  --include npu=build/rtl45000_npu \
  --include mapped=build/rtl45000_mapped \
  --include physical=build/rtl45000_physical \
  --include dsp-formal=build/rtl45000_dsp_formal \
  --out build/rtl45000_checkpoint
```

`--out` 指定尚不存在的目录。起始提交至固定提交须为连续的线性历史。`--include NAME=PATH` 可以重复使用，以实际存在的目录或文件保存额外结构、容量、ASIC 验证和工具结果。

`physical-45000` 导出检查核对测量源码与固定提交中的 RTL、生产配置及子模块一致，检查功能验证、DSP 参数验证、寄存器间路径分析和合法布局，并要求物理 LUT 位置不超过 45,000。组合级数与 150 MHz 时序状态分别记录在 `manifest.json` 的 `requirement_status` 中。

导出后在新的目标目录分别执行两种恢复脚本，保留生成的 `*.recovery.json`。实际固定提交、提交数量、面积、时序状态及文件摘要均由导出和验证程序写入对应报告。
