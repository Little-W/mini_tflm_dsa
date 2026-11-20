# 缓存替换来源的异或存储

每个缓存行用两位来源编码选择最近一次替换信息：`0` 选择填充记录，`1` 选择提示记录，`2` 选择命中记录。`conv_cache_rank_table` 将该编码表示为三个存储体的异或值，每个存储体各自提供一个写端口和三个异步读端口。输出仍在原有时钟边沿同步采样。

## 存储和更新

设某一行的三个存储值分别为 `B0`、`B1`、`B2`，其来源为 `B0 ^ B1 ^ B2`。填充写入 `B0` 时，用目标编码 `0` 异或另外两个存储值；提示写入 `B1` 时使用目标编码 `1`；命中写入 `B2` 时使用目标编码 `2`。这样可以在一个周期内更新三个不同地址。

同地址写入依次采用填充、提示、命中的优先次序。命中写入继续要求窗口模式或有效提示。配置清空阶段按原有行号，同时清零三个存储体；缓存有效位继续控制行的使用。读取与写入同地址时，输出保存该边沿写入之前的来源编码；暂停读取时保持输出。

数据缓存仍为 128 组、两路、每行 16 字节，共 4,096 字节。四个在途请求、八个预取项、AXI 接口及请求响应周期均保持原有行为。

## 独立综合

比较源码来自 `24d2fdf6`。综合参数为 `SETS=128`、`WAYS=2`、`BUS_WIDTH=64`、`LINE_BYTES=16`，目标为 Xilinx 7 系列。两份输入源码及 SHA-256 保存在测量结果中。

| 项目 | 参考实现 | 异或存储实现 | 变化 |
|---|---:|---:|---:|
| 逻辑 LUT | 5,026 | 3,658 | −1,368 |
| 分布式 RAM 的名义 LUT 数量 | 340 | 436 | +96 |
| 合计名义 LUT 数量 | 5,366 | 4,094 | −1,272 |
| 触发器 | 2,410 | 1,905 | −505 |
| RAMB18E1 | 20 | 20 | 0 |
| CARRY4 | 117 | 117 | 0 |
| 模块内部最长组合单元数 | 14 | 14 | 0 |

当前综合进程的峰值常驻内存为 276,236 KiB。上表统计映射单元与分布式存储所需的名义 LUT 数量；完整 SoC 的布局结果用于统计最终物理 LUT，布局布线时序报告用于检查 150 MHz。

## 验证

`rank_banks_equivalence.py` 从实际 RTL 提取三个写端口及读地址计算，对 2、8、128 项存储的全部来源状态执行逐行形式证明，共比较 276 位。存储初值、读写地址及各类事件均作为无约束输入，覆盖同地址优先级、不同地址同时写入、清空和保持。脚本同时核对来源表的全部实例连接，并逐字比较来源存储以外的模块内容。具名组合连接展开后还需通过完整模块文本比较，各项检查保留实际使用的源码哈希。

四态仿真先执行 128 行初始化，再运行 100,001 个检查周期；每周期比较全部 256 位来源状态及同步读输出，覆盖清空、碰撞写入、读写同址和读取暂停。

接口比较使用参考实现的真实周期行为，逐周期检查全部 13 个公开输出，包括无效周期的载荷值，同时比较活动预取描述和队列状态。测试覆盖以下七种配置：

| 缓存组数 | AXI 位宽 | 路数与在途请求深度 |
|---:|---|---|
| 8 | 32、64 | 双路深度四、单路深度四、双路深度一 |
| 128 | 64 | 双路深度四 |

每种配置运行 13 项场景，包含满队列、响应背压、错误恢复、复位、八项预取全部占用、预取优先次序和同周期入队与移除。生产配置接受 264 个请求，完成 260 个，另外四个按复位行为取消；缓存命中时连续接受和返回的间隔均为一个周期。

4 KiB 配置还完成预取开启及关闭各九项窗口数值检查，共 711,918 个周期和 41,636 个描述符。检查使用 32 位 AXI，覆盖深度卷积、步长、膨胀、非整齐通道数和逐点卷积。策略 2 的 39 个几何提示请求也已通过。详细参数、数值结果及源码哈希见 [`cache_rank_banks_validation.json`](../../docs/data/cache_rank_banks_validation.json)。

```sh
python3 test/cache_storage/rank_banks_equivalence.py --out build/cache_rank_banks/formal
python3 test/cache_storage/compare.py --reference-commit 24d2fdf6 --out build/cache_rank_banks/interface
python3 test/cache_storage/compare.py --reference-commit 24d2fdf6 --cache-sets 128 --bus-widths 64 --profiles 4x2 --out build/cache_rank_banks/production_interface
python3 test/windowed_cache/run.py --cache-sets 128 --cache-policy 3
python3 test/windowed_cache/run.py --cache-sets 128 --cache-policy 3 --no-prefetch
python3 test/conv_replacement/run_cache_policy.py --out build/cache_rank_banks/cache_policy
python3 test/cache_storage/synthesis.py --out build/cache_rank_banks/synthesis
```

形式证明和综合需要项目的 `PYTHONPATH`。仿真命令可通过 `--verilator`、`--iverilog` 和 `--vvp` 指定本机工具路径。并行测量时，同类独立综合共用项目规定的锁。
