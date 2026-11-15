# SoC 基准的公平性与独立审计

本说明定义可重复的审查条件，实际状态由每次运行目录中的 JSON 和日志决定。
源码包不附历史结果。先按 [README](README.md) 从源码生成向量、编译固件并运行，
再执行：

```sh
python3 test/conv_soc_perf/audit.py --evidence build/conv_soc_perf
```

`--evidence` 接受绝对路径或相对于当前工作目录的路径；结果缺省写入该目录下
`fairness_audit/`，可用 `--out` 指定其他位置。审计只读实际运行，不新增仿真或
重新生成 golden；它检查生成物的来源和哈希，而不是把“存在文件”当成通过。
默认审计主 10 次、latency 4 的两次和 IS 一次，共 13 次；`--summaries` 可明确
选择已有结果文件。审计失败即返回非零，不能只引用本文宣称测试通过。

## 原实现与数据对齐

`benchmark_baseline_e8.c` 保留提交 `e8a73373009064026fd0be1cbf3af6870d592ebb`
原 `riscv_conv_acc.c` 的全部字节。源 SHA 为
`b7a38e67f1196c35d714de3c74b1f0afa03fd8508ffd7f84c8f5445d6a87d49b`；
包装文件只重命名公开函数以便两条路径链接进同一 ELF。审计还核对原矩阵加速
helper 的源身份。固定的是原始源码身份，不是向量或期待的仿真输出；因此审计
不要求仓库包含旧提交历史，也适用于导出源码目录。

原 generic 路径每次展开 32 行 s8 再调用同一生产 DSA GEMM 驱动。原 1×1
路径不做 im2col，每个输出图像行提交一次 GEMM，每次 `output_w` 个位置。
五层主实验的 legacy START 数应为 25/7/2/1/14，硬件 WS 各为 1。
没有优化、重排或替换旧算法来改变基准；所选 batch1/group1、有 bias 的层也
未触发原实现对空 bias 或非单位 pointwise stride 的既有限制。

两条主路径链接相同 GCC 选项和官方 newlib 内存函数，并在同一个 ELF 中运行。
每次冷复位，instruction cache 缺省关闭。审计要求配对的实际 ELF SHA 相同，
而不仅是报告相同编译选项。

每次运行从原 TFLite 重新提取完整 NHWC/OHWI geometry，再从固定种子生成
input/filter/bias/multiplier/shift 和 C golden。审计核对生成器源摘要、每个
case 的 tensor/hash、实际 RAM 映像 SHA、两模式的几何/量化及全部 descriptor。
38 个配置词除 mode 和预期 START 两项外应一致。数值为合成测试数据，
不是训练权重；offset −7/−3、activation [−117,109] 也不是各模型原量化。

## 时间和硬件接管

性能时间来自真实 PicoRV32 `rdcycle` 包围完整 NMSIS 调用的 32 位模差。
初始化、golden 生成、保护字节设置和完整输出比对在计时外；没有使用主机耗时。
总线与 busy 计数来自 BEGIN/END marker；审计核对原日志和 JSON 完全一致，
且 marker 差值、CSR 差值、busy 上界均合理。等待 0 时 marker 多 45 周期，
等待 4 时多 65 周期，不能把两个区间混用成精确相等。

`call_cycles - npu_busy_cycles` 包含 CPU 参数准备、验证、MMIO、状态处理和等待，
不能命名为纯 im2col 时间。legacy 的 `CONV_CYCLES` 字段不适用，NPU 周期来自
测试台实际 busy 计数。CPU native 读为接受的 32 位 word，NPU 读为 AXI 有效
寻址字节，两者口径应分别保留。

硬件数值正确还必须满足真实提交合同：WS 仅 IA owner 发 im2col，IS 仅 kernel
owner 发出，legacy 没有 im2col 分块。硬件路径调用 scratch 为 NULL，标记区间
CPU 原图/权重读、scratch 读写和 NPU scratch 读均为 0。每条任务成功 DONE、
输出计数和原模型完整尺寸一致，CPU FNV 与独立 golden 一致，无 mismatch 或
破坏 guard；软件 fallback 算对结果也不能冒充硬件通过。

## 生成结果与源码完整性

审计读取当前运行目录 `sim/build.json`、`firmware_df*/firmware.json` 和三个
summary，再读取每条实际 `case.json`、`run.log`、`result.json`、`data.mem`。
生成向量以 case-relative 路径定位，整个目录可放在仓库外。可选本地归档支持
gzip 压缩的原始文件，不能替换其未压缩内容的 SHA。

完整 source manifest 检查 RTL/文件表与固件 C/头文件，实际 ELF/boot image
SHA 必须匹配。若复用已构建的纯 RTL sim，其完整源、参数和 binary SHA 仍需
一致，并明确标记复用；新的固件、向量和实际 CPU 执行不能由修改 manifest 代替。
独立审计汇总次数、命令和逐字节输出数量，不把 CPU 与测试台两次检查重复计数。

## 解释边界

应保留所有速度改善和退化。MobileNetV2 op52 是原 1×1 无软件 im2col 的控制项；
在 README 配置下，原完整调用 397961 周期，硬件 WS 600717 周期，后者约慢
50.95%。原 NPU busy 289954，硬件 441841。总读虽然从 927360 降至 478848 B，
减少的 448512 B 中原图仅 13056 B，权重 387072 B、参数 48384 B；大部分来自
原 14 次逐行 GEMM 和新全层分块的调度差异，不能全归因于输入 cache。

空间卷积的端到端收益包含取消 CPU 展开、scratch 搬运和减少命令提交；所有
五层新路径 NPU busy 都增加，不能声称阵列 MAC 更快。附加 IS 是真实入口验证，
latency 4 是内存等待敏感性补测，均不扩充主五层 WS 加速比。
结论只限于指定 SoC、编译器和内存配置，不声称整网精度、面积、Fmax、功耗或
真实硅片时间。实际复测数值以运行生成的 summary 与独立审计为准。
