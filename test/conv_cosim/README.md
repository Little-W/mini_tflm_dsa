# NMSIS C 与 NPU RTL 的协同仿真

从仓库根目录运行：

```sh
python3 test/conv_cosim/run.py --verilator /path/to/verilator
```

需要 Linux、GCC/G++ 和支持 timing/assert 的 Verilator。默认 SIZE=4；
`--size 8` 或 `--size 16` 选择其他阵列尺寸。测试使用普通 Conv 引擎配置，
不继承 menuconfig 的 PCR 默认值。默认编译产物在
`build/conv_cosim/objects/s<SIZE><profile>/`，日志及结果在
`build/conv_cosim/s<SIZE><profile>/results/`。`--build` 和 `--out` 可分别覆盖。

本目录只保存源码。输入、权重、量化参数、哨兵和参考输出均在运行时生成；
不需要归档向量、已有二进制或历史结果。`--skip-build` 仅复用本机已经成功构建、
参数和源文件 SHA 一致的可执行文件，不能跳过首次构建。

## 执行路径与数值核验

真实 NMSIS 普通、wrapper 和 fast 1×1 入口调用生产驱动。
`DSA_MMIO_CUSTOM` 只替换底层 MMIO 动作，每次访问在真实 AXI-Lite 上握手。
硬件为生产 `npu_axil_top`，时钟门控开启；共享 block DMA 内部生成 im2col，
后接实际 loader、阵列、bias、逐通道量化和写回。

存储器直接实例化生产 `rtl/soc/soc_axi_ram.sv`。测试仅在 NPU 空闲时通过
第二个 AXI 主接口装载输入和读回输出，不修改内部 RAM 数组。
输入/权重包含非对齐首尾和跨 4 KiB 的地址；输出前后哨兵检测越界写回。

主机在 `0x10000` 建立 32 位地址空间内的映射。硬件调用期间，输入、权重和
输出页面为 `PROT_NONE`，硬件路径的 scratch 为 NULL；CPU 不能借助读取这些
页面完成 im2col 或卷积。参考值提前由独立 NHWC/OHWI 直接卷积及仓库
`riscv_nn_requantize()` 生成。解除保护后经 AXI 读回并逐元素比对。

IS 用例调用生产低层 `dsa_conv_s8_execute()` 的 dataflow selector；NMSIS
公共入口在本测试中使用默认 WS。NMSIS 编译期 IS selector 的真实 CPU 执行
由 `test/conv_soc_perf` 的独立固件配置验证。

这是主机 C 与真实 RTL/RAM 的协同仿真，不执行 RISC-V CPU 指令，也不等同于
完整网络推理或板上测试。

## 可复现覆盖

每轮生成 14 个用例，分别在固定等待和随机 AR/W/R 等待下执行：

- WS 3×3、fast 1×1、batch/group、矩形核及 stride/dilation；
- 相同地址换输入内容后的任务失效；
- 超出 32 位总线范围时的真实 NMSIS 软件回退；
- IS 3×3、1×1、batch/group、矩形核及 stride/dilation；
- 同一 C16 对齐形状的 WS → IS → WS，及 IS 主动旁路和双尾块。

状态文件记录每个用例的输出数、硬件命令数、周期、总线字节数和源码 SHA。
批次/组中的最后一条命令缓存统计不能当作整个层的统计。调用计时包含
AXI-Lite 配置与轮询，不包含测试数据装载和结果读回。

## 独立协议与能力配置

```sh
python3 test/conv_cosim/run.py --axil-protocol-only
python3 test/conv_cosim/run.py --disabled-per-channel
python3 test/conv_cosim/run.py --disabled-is
python3 test/conv_cosim/run.py --narrow-kernel
```

协议专项检查寄存器回读、打包字段的 partial WSTRB、busy 时配置和重复 START
的 SLVERR、sticky error 及完成状态 W1C。它使用独立 profile 输出目录。

能力关闭配置检查生产驱动在 START 前拒绝请求，并强制向 RTL 发一个非法 Conv
命令以确认安全报错且不产生外存事务。`--narrow-kernel` 使用外部 WEIGHT_WIDTH=8；
普通核内部仍提升到至少 16 位，因此执行完整 WS/IS 数值用例。

C 构建启用 `-Wall -Wextra -Werror`。所有 Verilator 警告写入本次构建日志，
不依赖旧版本的诊断统计。没有执行综合、器件映射或时序分析。
