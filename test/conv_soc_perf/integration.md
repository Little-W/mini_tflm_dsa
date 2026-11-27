# CPU 与 NPU 卷积集成检查

本检查运行实际 `soc_top`。PicoRV32 执行 RV32IM 固件，通过 AXI-Lite 配置 NPU；
NPU 经 AXI 读取输入、权重和量化参数，并将完整卷积输出写回共享主存。
CPU 和测试台分别核对输出内容、保护区、命令完成状态及 AXI 响应。

固定硬件配置为 16×16 阵列、16 位输入和权重、32 位 AXI、8 个向量计算通道，
共享 IA/PS 存储为 7×8 KiB。卷积缓存为 4 KiB、16 组、2 路、128 B 缓存行、policy3。
测试台在启动时核对实际展开的共享存储和缓存参数。

## 覆盖范围

1. 寄存器检查：真实 CPU 读写配置寄存器，检查字节写入使能、数据流选择和未分配地址。
2. WS 卷积：IA 读取端生成窗口，完成一次 NPU 任务和全部输出写回。
3. IS 卷积：kernel 读取端生成窗口，完成一次 NPU 任务和全部输出写回。
4. WS 卷积加 RAM 等待：AXI RAM 附加 4 周期响应等待，检查握手及输出。

三个卷积场景均使用 `mnist_cnn_sg0_op0` 的完整模型尺寸，每次核对 6,272 个输出元素。
输入、权重和量化参数按固定种子生成，数值结果由独立 C 实现计算。
`integration_validation.json` 保存实际运行摘要及构建身份，运行目录保存完整日志和映像。

## 从源码运行

需要固定的 PicoRV32 子模块、Verilator、GNU RISC-V 编译器、NumPy、flatbuffers
以及 newlib 公共头。下面使用仓库内的官方 newlib 内存函数构建最小运行库。
可将路径变量替换为本地工具位置。

```sh
SOC_GCC=/path/to/riscv64-unknown-elf-gcc
SOC_NEWLIB=/path/to/newlib/include
SOC_OUT=build/conv_soc_integration

git submodule update --init picorv32
python test/conv_soc_perf/runtime_newlib/build.py \
  --gcc "$SOC_GCC" --newlib-include "$SOC_NEWLIB" \
  --out build/conv_soc_runtime

python test/conv_soc_perf/run.py --out "$SOC_OUT" --stage smoke \
  --gcc "$SOC_GCC" --newlib-include "$SOC_NEWLIB"

python test/conv_soc_perf/run.py --out "$SOC_OUT" --skip-build \
  --gcc "$SOC_GCC" --newlib-include "$SOC_NEWLIB" \
  --runtime-lib build/conv_soc_runtime/libnewlib_memory.a \
  --firmware-optimization Os --firmware-lto \
  --layers mnist_cnn_sg0_op0 --modes 1 --summary-name ws_summary.json

python test/conv_soc_perf/run.py --out "$SOC_OUT" --skip-build \
  --gcc "$SOC_GCC" --newlib-include "$SOC_NEWLIB" \
  --runtime-lib build/conv_soc_runtime/libnewlib_memory.a \
  --firmware-optimization Os --firmware-lto --dataflow 1 \
  --layers mnist_cnn_sg0_op0 --modes 2 --summary-name is_summary.json

python test/conv_soc_perf/run.py --out "$SOC_OUT" --skip-build --skip-firmware \
  --gcc "$SOC_GCC" --firmware-optimization Os --firmware-lto \
  --layers mnist_cnn_sg0_op0 --modes 1 --latency 4 \
  --summary-name latency4_summary.json

python test/conv_soc_perf/audit.py --evidence "$SOC_OUT" \
  --summaries ws_summary.json is_summary.json latency4_summary.json
```

`--firmware-optimization` 和 `--firmware-lto` 写入固件摘要，构建复用时检查选项一致。
当前集成配置使用 `-Os -flto`，并检查代码、数据和 BSS 的末地址低于输入区起点 `0x10000`。
寄存器程序保持其默认编译选项，独立于卷积程序。

源码修改后应去除 `--skip-build` 重新构建仿真器；固件源码或编译选项修改后应去除
`--skip-firmware`。复用检查同时核对实际源码、参数及二进制摘要。
完整调用周期包含 CPU 参数准备、提交和等待；NPU 忙周期由硬件独立统计。
比较不同 RTL 的性能时使用相同编译器、固件选项、张量和硬件参数。
