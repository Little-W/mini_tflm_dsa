# 原始输入到 NPU 输出的卷积验证

本目录实例化真实 `npu_top`、IA/kernel loader、共享 block DMA、阵列、部分和、
逐通道 bias/量化与写回。内存模型支持带等待的 AXI、窄读和 4 KiB 分段，并检查
读取范围。输入文件为原始 NHWC，权重为 OHWI；NPU 不读取 CPU 展开的 im2col 矩阵。

参考 [`reference_conv.c`](reference_conv.c) 执行独立直接卷积，并调用本仓库
原始 NMSIS `riscv_nn_requantize`。`host_compat.h` 仅提供主机编译需要的辅助
定义，不改变标量量化公式。所有向量、参考输出、日志、可执行文件和结果均在
运行时生成到 `build/` 或 `--out`，不从历史结果目录读取，也不包含在源码补丁中。

当前 frontend/raw cache 由共享 block DMA 实例化。WS 的 IA loader 和 IS 的
kernel loader 只发矩阵分块描述符，接收统一 signed16 行/列/有效 lane 返回。
完整当前架构入口见 [`test/conv_dma`](../conv_dma/README.md)。

## 运行范围

需要 Python 3、原生 GCC/G++、make 和支持 `--binary --timing --assert` 的
Verilator。真实模型提取另需 NumPy、flatbuffers。可选官方 Verilator 源码构建
脚本为 `test/conv_regression/build_verilator.sh`。

```sh
# 当前 DMA 架构：SIZE4/16 各 8 条命令，含实际 IS、混合调度及错误恢复。
python3 test/conv_dma/npu_cases.py --sizes 4 16 \
  --out build/conv_dma/npu --verilator verilator

# 54 条基础功能命令：45 次成功 Conv、3 次 IS GEMM、6 次预期错误。
python3 test/conv_npu/run.py --sizes 4 8 16 \
  --out build/conv_npu --verilator verilator

# 18 条逐输入字节核验命令，包含 Cout=33 的跨输出通道组。
python3 test/conv_npu/run.py --sizes 4 8 16 --reuse-audit \
  --out build/conv_read_audit --verilator verilator

# 5 档容量 × 2 个固定形状，共 10 条真实 RTL 命令。
python3 test/conv_npu/capacity.py --out build/conv_capacity --verilator verilator

# 现场提取原 TFLite、生成 10 个完整层的向量并复用上一条五档 binary。
# 五档容量加旁路，共 60 条；不是用模型目录 JSON 或旧向量作输入。
python3 test/conv_npu/model_shapes.py \
  --binaries-root build/conv_capacity --out build/conv_real_cnn \
  --tiling-policy driver-auto --bypass
```

这些数量描述各命令请求的范围，不表示未执行时已经通过。`--out /tmp/...`
支持仓库外目录。`run.py --smoke --sizes 4` 只跑一个 3×3 案例；`--skip-build`
核对 RTL/测试源 SHA 和 SIZE、sets、ways、line、policy，不接受过期 executable。

`run.py` 缺省配置为 **1 KiB 原图主缓存、policy2（几何 next-use + XOR）、
2 路、16 B line、4 个 IA tile 槽**，另有 16 B 当前 line transient。
`--cache-sets` 缺省 32，`--cache-policy` 缺省 2，均进入构建和复用校验。
`capacity.py` 固定 SIZE16/2-way/16 B line，显式构建 256/512/1024/2048/4096 B，
分别运行 75 B 小输入与 2304 B 稠密输入；不同容量可能发生真实重读。
可以给容量和模型 runner 同时传 `--cache-policy 0` 对照 LRU，不能混用不同
policy 的 build manifest。

需要同源码 LRU/几何策略隔离比较时，使用
[`test/conv_replacement/rtl_compare.py`](../conv_replacement/rtl_compare.py)。
它也现场生成向量，并将逐字节 RTL 读取直方图与明确标记为模型的轨迹回放核对。
模型推导不能替代真实 RTL 的输出、周期与总线统计。

## 真实 CNN 层与公共生成器

`model_shapes.py` 调用 [`generate_vectors.py`](../conv_models/generate_vectors.py)
直接读取原 TFLite，并检查来源 SHA、全部维度和 padding。完整 Cin/Cout、空间、
kernel、stride、dilation 保持不变；仅选择普通 INT8 Conv，不包含 depthwise。
每层生成一份原始输入、权重、量化与直接 C golden，所有容量和 bypass 使用
相同数值。每层种子独立固定，选子集或改变顺序不会改变相同层的数据。

默认 `--tiling-policy driver-auto` 调用真实 `gempact_tiling.h` C planner，
requested R/W=0/0；`stress-w2` 显式请求 2/2，用于单独压力对照。两种配置只改变
分组描述符，不改变 tensor/golden。`--layers` 接受模型原 ID 或安全 slug。
此 runner 核对已有五档 binary 的完整源/参数并记录实际 binary SHA，未提供
对应构建会失败，不暗中调整模型尺寸或换成模型预测值。

提取目录保存模型原始量化字段，数值仿真使用明确标记的确定性合成数据；
不能将单层结果描述为原训练权重推理或整网准确率。字段/API 详见
[`test/conv_models/README.md`](../conv_models/README.md)。

## 生成输出及计数含义

每轮 `summary.json` 保存实际通过状态，`build.json` 保存命令、profile、源摘要
和警告。任务的 `*.input_reads.csv` 逐字节记录逻辑窗口需求与真实 AXI 读取次数；
权重、bias、multiplier、shift 不计入 input 数字。容量实验另输出 `capacity.csv`，
包含有效 input 字节、unique、duplicate、miss、周期以及 RTL 元数据存储位数。

“重复读字节”是总有效 input 读取量减不同 input 字节数。“未使用但预取”是整
16 B line 填充取入、却不属于窗口逻辑需求的不同字节。稀疏 stride/dilation
或通道组可没有重复读，同时存在合法行内预取。padding 无输入地址，不发 AXI。
计数按单条命令统计，每个新 job 配置使原图 cache 失效。

IA tile 存储与原图 cache 不同：signed16 A tile 为 `SIZE²×2` B，4 槽共
`4×SIZE²×2` B，SIZE16 时分别为 512 B/2 KiB。原图 cache 数据容量不能计作
IA 容量。存储成本来自 RTL 数组位数，几何策略另有控制/预测器与 16 B transient；
这些数字不是 FPGA BRAM 分配或 ASIC 面积报告。
