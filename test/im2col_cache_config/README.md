# im2col 缓存容量检查

本目录验证 `IM2COL_CACHE_BYTES` 从配置文件、构建入口到实际 RTL 存储器及驱动调度的传递。支持 512 B～64 KiB，默认 4 KiB。容量与卷积尺寸关系见 [配置说明](../../docs/im2col_cache_configuration.md)。

## 主机配置与驱动

需要 Python 3、GNU Make 和 GCC。

```bash
make capacity-test
python3 test/im2col_cache_config/run_driver.py
```

配置测试检查八种合法容量、非法参数、配置保存、环境变量和命令行优先级、生成的 C 宏、容量预算及卷积尺寸提示。构建测试检查 VCS、SoC、Python backend 和 ASIC 接收的实际参数。

驱动测试分别编译独立驱动与 NMSIS 驱动，使用 4 KiB、8 KiB 两种编译容量，并启用 UndefinedBehaviorSanitizer。每个配置验证 24 项硬件查询、八种容量下的调度与缓存键，以及 720 项独立集合占用计算。重复规划使用已有结果，缓存旁路使用零容量描述。

## RTL 功能与容量

需要支持 `--json-only` 的 Verilator，以及 C++ 编译器。

```bash
python3 test/im2col_cache_config/run_cache_profiles.py --verilator verilator
python3 test/im2col_cache_config/run_elaboration.py --verilator verilator
python3 test/capacity/run_shared_bank_registers.py \
  --verilator verilator --out build/im2col_config/registers
```

`run_cache_profiles.py` 在全部八种容量下运行生产 im2col 前端，并逐项比较独立数学参考。测试覆盖 S8/S16、分组卷积、步长、dilation、尾部、等待和错误处理，同时检查实际数据 RAM 位数。512 B、4 KiB、64 KiB 另外运行窗口访问测试，统计外部读取字节与前端周期。

`run_elaboration.py` 展开完整 `npu_axil_top`，检查数据数组、每缓存行 75 位元数据、两级顶层参数及能力寄存器参数。覆盖八种缓存容量和两项 FPGA 共享 RAM 配置。硬件容量检查与软件预算检查分别执行；使用较大缓存时通过 `make capacity-check` 检查所选总容量预算。

寄存器测试在 23 种配置下执行真实 AXI-Lite 读写，检查 `0x13c` 的容量返回值、只读属性、关闭 Conv 时的返回值，以及 IA/PS 分配、busy、返回等待和复位期间的行为。

## 完整构建入口

SoC 测试使用仓库中的 PicoRV32 子模块，也支持显式提供源码目录。

```bash
python3 test/im2col_cache_config/run_build_entrypoints.py \
  --verilator verilator --picorv32 picorv32
python3 fpga/vivado/tflm_ai_dsa_soc/scripts/test_npu_config.py
```

`run_build_entrypoints.py` 调用 SoC 和 Python backend 的实际命令行入口，在保留源码列表、define、include 与顶层的情况下执行 Verilator JSON 展开。检查非默认 8 KiB 配置对应的 256 组、两路、16 B 缓存行、实际数据 RAM 和能力寄存器参数。

Tcl 测试使用记录命令参数的替代过程，检查 Vivado 工程创建、综合、实现、仿真和导出的参数及配置快照。实际 FPGA 资源与时序由 Vivado 综合和实现报告给出。

各测试将结果和源码 SHA256 保存到指定输出目录。仿真结果的适用范围由报告中的测试类型与参数共同确定。
