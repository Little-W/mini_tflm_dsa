# FPGA 优化版本的恢复与运行

## 恢复提交与验证参考

`fpga_optimization.bundle` 保存从 `aa2ef9a3` 开始的新增提交和 `experiment/no-ps-compression` 分支，保留完整提交标识。其前置版本为远程仓库已有的 `aa2ef9a32daaded9ff16db0b8d3c905763dc95cb`。

在已有仓库的目标分支中执行：

```sh
git switch experiment/no-ps-compression
git bundle verify /path/to/fpga_optimization.bundle
git fetch /path/to/fpga_optimization.bundle refs/heads/experiment/no-ps-compression
git merge --ff-only FETCH_HEAD
git submodule update --init picorv32
```

该流程使用快进合并，保存各模块等价检查使用的历史参考版本。`fpga_optimization.patch` 提供相对 `aa2ef9a3` 的完整源码差异。完整测试使用 bundle 恢复的提交历史。

## 完整交接包与逐提交补丁

`scripts/fpga/export_checkpoint.py` 从固定提交生成完整交接包。包内包含 `patches/`、顺序文件 `series`、原始 Git 提交对象、`source.bundle`、子模块 bundle、源码快照、修改记录、后续方向、测量结果和 SHA-256。

`apply_patches.sh` 逐项应用二进制补丁，每项均检查源码树，并恢复原始作者、提交者、时间、说明和父提交，因此最终提交标识与导出版本完全相同。`restore_bundle.sh` 提供直接恢复方式。两种方式均使用尚不存在的目标目录，并恢复 PicoRV32 子模块。

```sh
./apply_patches.sh --destination /path/to/restored_soc
./restore_bundle.sh --destination /path/to/another_restored_soc
```

已有仓库包含起始提交时，可使用 `--repository /path/to/mini_tflm_dsa` 在独立工作树中应用补丁。恢复程序先核对包内文件摘要，完成后检查最终提交、源码树和清洁工作目录，并在目标目录旁写入 `*.recovery.json`。

导出面积检查点时，`--kind synthesis-60000` 要求完整 SoC 的逻辑 LUT 不超过 60,000；`--kind physical-60000` 要求合法布局完成、无资源错误或未放置单元，并且物理 LUT 位置不超过 60,000。导出程序同时核对固定 RTL 和生产配置，以及组合网络与 DSP 参数的等价验证。`--include NAME=PATH` 可将实际综合、实现、仿真和工具文件收入交接包。

135 个连续提交已通过两种恢复方式，逐提交检查保持全部原始提交标识。验证结果见 [交接恢复检查](data/fpga_checkpoint_recovery_validation.json)。

## 工具环境

开源综合使用 `pyosys==0.71.post40`。完整 NPU 仿真使用 Verilator Python 包 `5.48.0`、GCC 14.2.0 和 GNU Make，展开后的工具版本字符串为 `rev vUNKNOWN-built20260516-4e853d8`。单模块检查同时使用 Verilator 5.032；四态检查使用 Icarus Verilog 12.0。

以下命令在单独的工具目录安装完整 NPU 仿真环境，并配置 GCC 的语言、协程和预编译头文件选项：

```sh
python3 -m pip install pyosys==0.71.post40
python3 -m pip install --target /path/to/tools/verilator verilator==5.48.0
patch -d /path/to/tools/verilator/verilator -p1 < scripts/fpga/patches/verilator_5_48_gcc.patch
export VERILATOR_ROOT=/path/to/tools/verilator/verilator
export VERILATOR_BIN="$VERILATOR_ROOT/bin/verilator_bin"
```

## 完整 NPU 与容量检查

```sh
python3 test/fpga_integration/run.py \
  --verilator "$VERILATOR_ROOT/bin/verilator" --jobs 2 \
  --out build/fpga_integration

python3 test/ps_capacity_limits/run_npu.py \
  --verilator "$VERILATOR_ROOT/bin/verilator" \
  --sim build/fpga_integration/npu/s16 --out build/ps_capacity \
  --suite-timeout 900

python3 test/writeback_cyclic/run_npu.py \
  --sim build/fpga_integration/npu/s16 --out build/writeback_npu

python3 test/ps_channels/run_npu_structure.py \
  --out build/fpga_npu_structure

python3 test/capacity/check_elaboration.py \
  --config config/npu_fpga.mk --verilator "$VERILATOR_ROOT/bin/verilator" \
  --output-root build/capacity
```

完整 NPU 仿真启用实际 FPGA 实现分支与官方原语功能模型。容量与输出合并任务复用同一仿真器，并核对配置、RTL 和二进制摘要。`run_npu_structure.py` 检查实际 FPGA 分支中的固定部分和通道、完整存储容量、256 个阵列计算单元和 8 路向量 PE。通用容量检查同时保留 ASIC 分支的存储结构统计。

## 组合逻辑与数值检查

各模块的测试目录保存输入生成、参考计算、逐周期比较、形式证明和独立综合入口：

| 检查对象 | 入口 |
| --- | --- |
| 公共存储器 | `test/regfile/` |
| 卷积缓存及预取 | `test/cache_storage/`、`test/conv_replacement/` |
| 卷积描述符与读取范围 | `test/conv_frontend/`、`test/conv_guard/` |
| IA 加载器 | `test/ia_timing/` |
| 权重存储与加载计数器 | `test/kernel_prefetch/` |
| 阵列权重加载 | `test/dip_array/` |
| 偏置选择与相加 | `test/select_add/` |
| 偏置驻留范围 | `test/bias_loader_range/` |
| 部分和容量 | `test/ps_capacity_limits/` |
| 固定部分和通道 | `test/ps_channels/` |
| 配置幂次判断 | `test/config_onehot/` |
| 量化流水 | `test/requant_pipeline/` |
| 输出写回及 FIFO | `test/oa_writer/`、`test/writeback_bus/` |
| 向量计算与参数存储 | `test/vector_engine/`、`test/vector_params/` |

正式结果采用保存的源码摘要对应的参数和命令。重新测量时使用独立输出目录，保留相应报告及源码摘要。

## 完整 SoC 面积与器件时序

完整 SoC 的固定参数、DSP 映射、布局布线和器件模型见 [开源 FPGA 综合与资源分析](open_fpga_synthesis.md)。当前设计和目标状态见 [FPGA 优化交接](fpga_optimization_handoff.md)。

```sh
python3 scripts/fpga/open_fpga_synth.py --cases soc_top \
  --out build/open_soc --lock-file /path/to/synthesis.lock

python3 scripts/fpga/open_fpga_synth.py --cases soc_top \
  --wide-alu-dsp-budget 740 --reuse-elaboration-from build/open_soc/soc_top \
  --out build/open_soc_dsp --lock-file /path/to/synthesis.lock
```

面积目标使用合法器件布局后的物理 LUT 位置数，150 MHz 目标使用目标器件与速度等级的布局布线时序检查。映射网表中的逻辑 LUT 数和组合路径单元数分别用于分析资源及结构。
