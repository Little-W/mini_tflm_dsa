# PicoRV32 SoC 卷积性能对照

这里运行生产 `soc_top` 中的 PicoRV32、NPU、互连、时序缓冲和 `soc_axi_ram`。
RV32 固件执行完整 NMSIS 调用，通过真实 MMIO 提交任务；测试台只装载 RAM、
复位、观测握手并核对 CPU 结果，没有主机 C/MMIO 代理。

这是可从源码重建的测试入口。模型目录、输入、权重、量化、golden、RAM 映像、
固件和运行结果均在执行时生成到 `build/` 或显式 `--out`。不读取历史结果，
补丁不附日志、二进制或生成向量。详细计量解释见
[SoC 性能报告](../../docs/conv_soc_performance.md)；审计规则见
[benchmark_review.md](benchmark_review.md)。

## 实验范围

默认主实验为下列 **5 层 × 原软件路径/硬件 WS = 10 次**独立冷复位执行。
每层两条路径使用同一 ELF、相同张量内容、地址布局和 SoC 可执行文件。

| 原模型层 | 输入 H×W×C | OHWI 权重 | 输出 H×W×C | 原路径预期 START |
|---|---|---|---|---:|
| MNIST op0 | 28×28×1 | 8×3×3×1 | 28×28×8 | 25 |
| MNIST op2 | 14×14×8 | 16×3×3×8 | 14×14×16 | 7 |
| Gesture op7 | 16×16×16 | 32×3×3×16 | 8×8×32 | 2 |
| Gesture op16 | 8×8×32 | 64×3×3×32 | 4×4×64 | 1 |
| MobileNetV2 op52 | 14×14×96 | 576×1×1×96 | 14×14×576 | 14 |

每个硬件 Conv 预期 1 次 START。原 generic 软件基线每批展开 32 行 s8；原
1×1 路径每个输出图像行提交一次 GEMM，每次含 `output_w` 个位置，**本来就没有
CPU im2col**。不能把这个控制项的结果归因于省去软件窗口展开。

完整范围再包括 Gesture op7、RAM 附加响应等待 4 周期的两路径，以及单独编译
IS selector 后的 MNIST op0 一次。这是 **13 次性能执行、58 个 NPU 命令、
261120 个输出元素**，每个输出由 CPU 和测试台独立检查；两次检查不重复计数。
寄存器 smoke 是独立入口，不计入上述 13 次。

模型尺寸和 padding 来自原 TFLite。固定 seed `20261115` 的合成输入、OHWI
权重、bias、multiplier、shift 和独立 C golden 由
[`generate_vectors.py`](../conv_models/generate_vectors.py) 即时生成。
每层数值与选择顺序无关，metadata 和每个 tensor SHA 写入生成目录。
input/output offset −7/−3、activation [−117,109] 为合成测试参数，
不是模型原量化或训练权重；本测试不声称整网精度。

## 依赖与运行

需要 Python 3、NumPy、flatbuffers、原生 GCC/G++、Verilator，以及能生成
RV32IM/ILP32 的 GNU RISC-V bare-metal GCC/binutils。初始化固定 CPU 子模块：

```sh
git submodule update --init picorv32
python3 -m pip install numpy flatbuffers==25.2.10
```

对两条路径使用同一 target libc。本目录保存原样的官方 newlib RISC-V
`memcpy`/`memset` 源码，可用匹配的公共头编译最小内存运行库：

```sh
python3 test/conv_soc_perf/runtime_newlib/build.py \
  --gcc /path/to/riscv64-unknown-elf-gcc \
  --newlib-include /path/to/newlib/include \
  --out build/conv_soc_runtime

python3 test/conv_soc_perf/run.py \
  --out build/conv_soc_perf \
  --verilator /path/to/verilator \
  --gcc /path/to/riscv64-unknown-elf-gcc \
  --newlib-include /path/to/newlib/include \
  --runtime-lib build/conv_soc_runtime/libnewlib_memory.a
```

源版本和 package SHA 常量在
[`runtime_newlib/package_sources.py`](runtime_newlib/package_sources.py)。
库文件与构建 manifest 全部现场生成。完整工具链已有 target libc 时，可省略
两个 newlib 参数，runner 使用 `-lc`；复现特定周期需保持相同编译器和运行库。

`make conv-soc-perf` 调用相同入口，可通过 `CONV_RISCV_GCC`、`VERILATOR`、
`CONV_BUILD_DIR` 和 `CONV_SOC_FLAGS` 传参。`--out` 可为仓库外的任意目录，
case 到生成向量的来源使用相对路径，不要求生成文件位于仓库根目录下。

默认只执行主 10 次。在同一输出目录补齐另外 3 次：

```sh
python3 test/conv_soc_perf/run.py \
  --out build/conv_soc_perf --skip-build --skip-firmware \
  --gcc /path/to/riscv64-unknown-elf-gcc \
  --layers justure_detect_sg0_op7 --modes 0 1 --latency 4 \
  --summary-name latency4_summary.json

python3 test/conv_soc_perf/run.py \
  --out build/conv_soc_perf --skip-build \
  --gcc /path/to/riscv64-unknown-elf-gcc \
  --newlib-include /path/to/newlib/include \
  --runtime-lib build/conv_soc_runtime/libnewlib_memory.a \
  --dataflow 1 --layers mnist_cnn_sg0_op0 --modes 2 \
  --summary-name is_summary.json

python3 test/conv_soc_perf/summarize.py build/conv_soc_perf
python3 test/conv_soc_perf/audit.py --evidence build/conv_soc_perf
```

`--skip-build` 核对完整 RTL/文件表源、profile 和实际 executable SHA；
`--skip-firmware` 核对当前 C/头源及 ELF，不能将旧构建重标为新源码。
若已有独立输出目录中的纯 RTL simulator，可用 `--reuse-sim /path/to/old/sim`：
同样要求完整源/参数/binary SHA 一致，manifest 明确记录复用来源。
该选项仍重新编译当前固件，生成当前向量并实际执行所请求的 CPU 仿真。
缺省行为始终从源码编译，不需要任何预构建文件。

`--stage smoke` 单独让真实 CPU 执行现有 SoC 寄存器测试；性能主程序从 `main()`
返回 0，由现有 `start.S` 写 SoC finish/status。主测试不依赖 UART 或主机计时。

## 固定条件与计量单位

- 标准支持 Conv 的 profile：`PCR_ENGINE=0`、SIZE16、IA 4 slots、PS 16 frames，
  默认 1 KiB 原图主 cache、policy2、16 B transient；不是默认 PCR profile。
- PicoRV32 固定 submodule `ef203c2b0a3fb793280f5114941416c425c5b461`；
  RV32IM、乘除开启、无压缩指令、32 位 cycle CSR，CPU instruction cache 缺省关闭。
- 2 MiB 共享 RAM，读写 outstanding 各 4，主实验固定附加响应延迟为 0。
- 固件 `-O3 -march=rv32im_zicsr -mabi=ilp32`。可复现配置使用 GCC 14.2.0、
  newlib 4.5.0.20241231 官方优化内存函数；两个主模式链接同一个 ELF。
- 主时间是 CPU `rdcycle` 包围完整 NMSIS 调用的模差。初始化、golden 生成、
  guard 初始化、完整输出比对、统计读回均在区间外，无函数级 `--wrap` 性能探针。
- 测试台 BEGIN/END marker 窗口略宽于 CSR 窗口；RAM 延迟 0 时多 45 周期，
  延迟 4 时多 65 周期。CPU 指令/data/MMIO 计数来自此窗口，NPU 所有任务位于调用内。
- CPU native 读计数是 32 位传输：`reads × 4` 为总线字节，不是 C `int8_t`
  逻辑字节数。CPU/NPU 写入按实际 byte strobe 累计。
- NPU 读按接受 AR 的有效字节范围计数，扣除未对齐首拍未用 lane；input、weight、
  scratch、output 和 params 分区统计。
- `call_cycles - npu_busy_cycles` 包括 CPU 准备、验证、MMIO 和状态处理，
  不能称为纯 im2col 时间，也不是所有 CPU 工作的独立计时。

## 内存与成功条件

| 区域 | 字节地址 |
|---|---:|
| 固件 text/data/bss | 0 起，链接检查必须小于 0x10000 |
| 输入 / 权重 | 0x10000 / 0x20000 |
| bias / multiplier / shift | 0x30000 / 0x31000 / 0x32000 |
| 输出 / 原软件 scratch | 0x40000 / 0x60000 |
| golden / runtime descriptor | 0x80000 / 0xA0000 |
| 栈顶 | 0x200000 |

`benchmark.h` 定义 descriptor 的 38 个小端 32 位字段。主成对比较仅 mode 和
预期 START 数不同，所有张量、几何与量化相同。24-word `benchmark_result` 由
ELF 的 `nm` 符号定位；CPU 完成后测试台读取真实 RAM。

测试核对完整输出、guard、实际 START/DONE 数、Conv/IS 位及真实 im2col owner。
WS 应由 IA client 发 im2col，IS 应由 kernel client 发出；硬件路径的 CPU 原图
读取和 scratch 读写应为 0。软件回退、发错 owner、提前完成或漏比输出都判失败。

## 结果文件与解释

运行目录包含 `sim/build.json`、`firmware_df*/firmware.json`、每次 `case.json`、
`data.mem`、`run.log`、`result.json`，以及各轮独立的 `vectors_*` 目录。
三个 summary 汇总主 10 次、latency 两次及 IS 一次。`summarize.py` 生成 CSV/
比较 JSON；`audit.py` 生成 `fairness_audit/`，逐项核对当前源、生成器、向量、
映像、固件、counter 日志和结果。绝对路径和从仓库执行的相对路径均可使用。

`archive.py SOURCE DESTINATION` 是可选的本地结果打包工具，拒绝覆盖已有目标，
复制前检查源摘要；生成向量也随目录一并复制。归档、ELF、MEM、日志和仿真
二进制不属于源码补丁，也不是下一次运行的必需输入。

结果应同时报告速度改善与退化：在上述配置下，四个空间卷积的完整调用加速，
但 MobileNetV2 op52 的原 1×1 路径无需 CPU im2col，硬件路径约慢 50.95%。
所有五层的新 NPU busy 都增加，不能把总体收益说成 MAC 阵列更快。输入 cache
与全层任务调度共同影响流量，尤其该 1×1 大部分读流量节省来自权重/参数。
这些是指定 SoC/编译器/内存条件下的单层 RTL 周期，不外推为板级频率、面积、
完整网络准确率或所有 CNN 的加速保证。
