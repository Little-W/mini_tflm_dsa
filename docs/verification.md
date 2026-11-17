# 仿真与 FPGA

以下命令在仓库根目录运行。首先执行 `git submodule update --init --recursive`，确保 PicoRV32 源码可用。

## 共享 IA/PS、DiP 与初始化配置

Verilator 检查使用统一 NPU 路径，并以独立整数模型比较输出。驱动、配置和原生接口测试可在主机执行。

```bash
make capacity-test
make dip-array-test VERILATOR=/path/to/verilator
make ps-stream-verify VERILATOR=/path/to/verilator
make shared-memory-test VERILATOR=/path/to/verilator
```

| 检查范围 | 内容与入口 |
|---|---|
| DiP | 完整行输入、对角传递、权重旋转、shadow 权重切换，见 [阵列测试](../test/dip_array/README.md)和[权重测试](../test/dip_weights/README.md) |
| 无损 PS | COPY、literal、Rice、Sparse128、frame 分配与逐行恢复，见 [PS 测试](../test/ps_compression/README.md) |
| 共享 bank | IA/PS 独立端口、同周期访问、字节写掩码、bank 分配、结构及物理映射，见[共享 RAM 映射](shared_ram_mapping.md) |
| AUTO 驱动 | 物理 AXI 读写拍、请求开销、WS/IS、R/W、bank 分配、严格范围与输出容量，见[容量检查](../test/capacity/README.md) |
| Prepared 接口 | 两套驱动 API、NMSIS 适配、arena 指针与软件回退，见 [TFLM 接口](../drivers/tflm/README.md) |
| 重复 Invoke | 模型、权重、持久配置、arena 用量和规划计数保持稳定，见[生命周期测试](../test/prepared_lifecycle/README.md) |

8 KiB bank 配置另行运行完整 NPU 的最大复用测试：

```bash
python3 test/shared_ia_ps/run_geometry_npu.py \
  --bank-count 7 --bus-width 64 --jobs 2 \
  --verilator /path/to/verilator --out build/shared_geometry
```

该测试覆盖 WS/IS、S8 R64、S16 输入 R32、硬件 im2col、packed 尾部、连续 K 与 frame 调度。固定与随机 AXI 等待共 36 个用例，检查 753,232 个 INT32 结果。输出缓冲与寄存器能力报告分别检查，确保完整行组的输出均有存储空间。

## RAW32 与压缩模式比较

每个比较使用同一个 RTL 可执行文件、同一个固件 ELF、相同物理 RAM、相同模型和输入；在初始化前设置 RAW32 或 adaptive，并分别执行生产驱动 AUTO。记录配置、源码 SHA-256、模拟器与 ELF 摘要、硬件周期、CPU Invoke 周期和 PS 保存/恢复内容。

已完成的测试包括默认 2 KiB × 7 bank 的 32 次完整网络运行、FPGA 8 KiB × 7 bank 的 8 次完整网络 trace、三种物理配置下的批量 64 Dense，以及五个原始 Dense 的两个输入。结果及复现命令见[性能测量](shared_ia_ps_performance.md)和[结构化结果](measurements/shared_ia_ps_20261116.json)。perf 与 trace 分别汇总，初始化成本与 Invoke 成本分别报告。

分阶段导出包为各提交保存独立检查记录，包括 commit、tree、执行报告与 SHA-256。PS 接入、DiP、容量调度、TFLM arena、物理 RAM 和测量工具分别提交。提交脚本逐阶段生成相应文件状态，并可在任一阶段结束或从已生成阶段继续。

## VCS

```bash
make vcs-unit
make vcs-axil
make vcs-soc
make vcs-nmsis-abi
make vcs-tflm
```

`vcs-unit` 运行 DMA、部分和存储、计算核心和 NPU 顶层测试；`vcs-axil` 和 `vcs-soc` 运行 UVM 测试；`vcs-nmsis-abi` 运行驱动接口测试。`make vcs-pcr-soc` 运行统一路径 PS 压缩的 SoC 测试。运行日志和构建产物分别位于 `build/vcs/` 和 `veri/sim/runs/`。

可用 `SIZE`、`IA_CACHE_BLOCKS`、`PS_FRAME_COUNT`、`SEED` 等变量设置参数，使用 `make help` 查看入口。

## Python 接口

[Python 模型说明](../veri/python_model/README.md)介绍 Verilator 后端的构建及逐周期比较。`veri/pcr_model/` 提供共享计算阵列与 PS 压缩的兼容构建入口，构建命令见 [TFLM 说明](../drivers/tflm/README.md)。

## FPGA

Vivado 工程入口、器件和时钟参数见 [Vivado 工程说明](../fpga/vivado/tflm_ai_dsa_soc/README.md)。例如：

```bash
vivado -mode batch -source fpga/vivado/tflm_ai_dsa_soc/scripts/run_batch_synth.tcl
```

FPGA 默认配置为 `config/npu_fpga.mk`，共享 bank 为 8 KiB。Yosys 实际映射检查覆盖 6、7、8、9 个 bank，对应 12、14、16、18 个 `RAMB36E1`，共享数据容量全部使用。测试命令及独立 parity 容量见[共享 RAM 映射](shared_ram_mapping.md)。

本次已运行 Verilator 和 Yosys。当前环境没有 Vivado，Vivado 综合、布局布线和时序结果由上述工程流程生成。

## ASIC

SMIC40 标准单元、SRAM 宏、综合与功能仿真入口见 [ASIC 综合环境](../asic/README.md)。
