# 卷积几何感知缓存的可再生验证

当前生产实现采用 DMA 内的 im2col 前端与 raw-input cache，默认主数据容量
1 KiB、policy 2，另有 16 B 当前 line transient。实现说明见
[DESIGN_RTL.md](DESIGN_RTL.md) 和 [block_dma_im2col](../../docs/block_dma_im2col.md)。

本目录只保留生成器、数学模型、testbench 和运行脚本。所有层元数据、descriptor、
输入/权重/量化/golden、请求轨迹及 predictor 向量都在本次 `build/` 或 `--out`
目录即时产生；不读取旧 evidence、压缩 trace、内存文件或源码快照。

## 数据来源与独立性

公共 `test/conv_models/generate_vectors.py` 从仓库 TFLite 模型重新提取十个真实
Conv 层的完整尺寸，并编译调用当前 C planner 选择自动 R/W。默认 seed 固定为
`20261115`，每层使用同一 seed，选择子集或改变执行顺序不会改变该层数值。
输入/权重/bias/量化参数是合成数据；这不是训练权重的整网准确率实验。
标量 C 卷积与仓库 NMSIS requant 函数在每次执行时产生完整参考输出。

`trace_model.py` 按 WS 原生调度枚举请求：p-block → output-group → q-tile →
R 个 p-tile → tile 内 position → reduction column。它过滤 padding/尾部，并建模
前端跨 tile 保持的 4 B word register；只有需要不同 word 时才产生 cache 请求。

`geometry_oracle.py` 独立从输入坐标逆推最多 Kh×Kw 个候选输出位置，再求下一次
事件 rank/剩余次数。参考值由 forward 序列反向扫描获得，测试不把未来表提供给
生产 predictor。真实模型中七层适用快路、三层按 guard 跳过；另有五个 synthetic
几何覆盖 group offset、dilation、稀疏 stride、25 taps、尾块和相邻同地址事件。

## 验证层次

| 脚本 | 实际动作 | 输出 |
|---|---|---|
| `trace_model.py` | 现生成十层 forward 请求，计算 LRU/旁路读取模型 | traces、计数 JSON |
| `focus.py` | 三难层的 LRU、next-use、次数准入、XOR/全相联模型 | 离线 JSON/CSV |
| `geometry_oracle.py` | 独立几何逆推与 forward future 比较 | 校核报告、可选向量 JSON |
| `predictor_test.py` | 将现生成向量送入生产 predictor RTL | 31 配置、13046 向量检查日志 |
| `run_cache_policy.py` | 生产 cache 的过程激励，独立于几何 oracle | 39 事务的协议/准入检查 |
| `rtl_compare.py` | 完整真实尺寸 NPU 执行、C golden、每字节 AXI 计数比较 | 当前周期、流量、逐地址直方图 |
| `cost/audit.py` | 当前源码显式寄存器/数组位数的静态审计 | 逻辑存储报告，无面积/Fmax 推断 |

离线模型不预测周期，也不等同于 RTL 执行。`rtl_compare.py` 的 policy 0 预期由
LRU 模型现算；policy 1/2 在 eligibility 内用 next-use 模型，其他几何走原 LRU。
不仅比较总 input bytes，还逐个核对整个输入分配的实际外部读取次数，并比较完整
输出和保护区。各 policy 使用同一批本次生成的数值与 descriptor。

## Transient 与模型成本

预测从整个当前 line 事件完成之后算起，不把该 line 剩下三个 word 当远期复用。
拒绝准入时仍外读完整 line 至 16 B transient；任何不同 line 的请求都会使它
失效，包括主缓存命中。因此 data storage 是 C+16 B，另计 tag/valid/next-use。
几何快路的 aligned 输入使每个有效 fragment 恰好是四个 word。

`focus.py` 额外展示相同容量的全相联 next-use 模型；它只是该 line/miss 合同的
比较下界，不能视为两路硬件能力。XOR 不保证每例周期更快，次数策略与 next-use
也不保证在所有轨迹上相等。当前 RTL 仅实现 policy 0/1/2 三种选择。

## 运行

需要 Python 3、NumPy、FlatBuffers、GCC/G++、make 和 Verilator，模型依赖说明见
[conv_models](../conv_models/README.md)。从仓库根目录执行：

```sh
python3 test/conv_replacement/trace_model.py
python3 test/conv_replacement/focus.py
python3 test/conv_replacement/geometry_oracle.py
python3 test/conv_replacement/predictor_test.py --verilator verilator
python3 test/conv_replacement/run_cache_policy.py --verilator verilator
python3 test/conv_replacement/rtl_compare.py --verilator verilator
```

缺省 RTL 对照为三难层 × 五个 profile，共 15 条；profile 格式为 `policy:data_bytes`。
完整 Make 入口执行六个 profile 的三难层，再复用新构建的 P2/1KiB 跑其余七层，
共 25 条当前 RTL 命令：

```sh
make conv-replacement VERILATOR=/path/to/verilator

# 较小的真实 RTL 对照：三难层 × LRU / 几何 XOR，各为 1 KiB。
python3 test/conv_replacement/rtl_compare.py --profiles 0:1024 2:1024 \
  --out build/replacement_compare --verilator verilator
```

`--layers` 可选择原模型 layer ID。`--skip-build` 与可选 `--reuse-builds-root` 只
复用通过 source SHA/profile 核验的本地 executable；输入和参考仍每次生成。
没有缓存时正常构建即可，运行不需要任何先前的报告或 binary。
