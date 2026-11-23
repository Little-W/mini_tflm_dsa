# IA 紧凑存储与读流水线

## 存储格式与容量

`ia_loader_cache_mgr` 使用固定物理容量保存输入矩阵。`COMPACT_S8` 决定是否生成紧凑存储逻辑；运行时 `compact_mode` 选择本次任务的存储格式。完整加载器通过 `cfg_compact` 请求紧凑模式，并检查 `DATA_WIDTH=16` 及 `cfg_compact_offset` 位于 −127 至 128。

在 16 位数据配置下，普通格式的每个元素占用两个字节，紧凑格式的每个元素占用一个字节。物理容量为 `CACHE_BLOCKS × SIZE × SIZE × DATA_WIDTH / 8` 字节。普通格式使用 `CACHE_BLOCKS` 个逻辑槽位，紧凑格式使用 `2 × CACHE_BLOCKS` 个逻辑槽位。

紧凑写入保存 `8'(value - offset)`，读取将字节解释为有符号 INT8，再加回当前行的偏移量。这一功能用于已知 INT8 来源的偏移扩展数据。有效列中的零值同样经过编码：偏移为 128 时保存 `8'h80`，偏移为 −127 时保存 `8'h7f`，两者均恢复为零。未写入列由有效列范围控制，输出为零。

IA 管理器固定通过两个 128 位端口访问共享 SRAM。综合比较中的 16384 字节表示共享池最多可分配给 IA 的容量。`slot_written_cols` 单独保存各槽位的有效列范围，属于缓存控制元数据。

`cfg_tile_packed` 控制外部矩阵的 tile 排列方式，与紧凑存储开关独立。

## 读出周期

所有通道在相同周期读取同一行，每周期可以输出一行。紧凑功能开启时，普通格式和紧凑格式共用 RAM 输出寄存器，运行时切换格式保持相同的读出延迟。

| 编译配置 | 从 cache manager 发射行请求到行输出的寄存级数 | 恢复运算 |
|---|---:|---|
| `COMPACT_S8=0` | 2 | 无 |
| `COMPACT_S8!=0` 且 `DATA_WIDTH=16` | 3 | RAM 输出寄存后执行 |

紧凑读出先选择正确的字节并保存，再使用 `parallel_prefix_add` 计算恢复值。完整加载器声明九位有符号偏移，恢复加法使用十位结果，最终扩展为 16 位数据。独立缓存模块的 `p_compact_offset_width` 默认等于 `DATA_WIDTH`，保留完整输入位宽的截断加法语义。

行有效、首次累加标志、最终累加标志、tile 末行、L1 组末行、存储模式和偏移量随读请求保存。`tile_done` 和 `l1_done` 与相应的最后一行同时有效。`ia_tile_start` 提前两个周期指示 tile 首行，供 PS 读取使用。复位清空流水线中的有效位；无效周期的全部输出数据为零。

编译关闭时，紧凑读写选择、恢复加法、额外数据寄存器和双倍槽位处理可由综合消除。加载器将普通格式的恢复偏移状态置为零。

## 配置有效性

矩阵任务要求共享 IA 存储。非共享配置通过现有控制器和帧调度器返回配置错误，完成前不发起 IA 加载或 DMA 请求。

## 验证入口

`test/ia_read_pipeline/run.py` 使用共享端口存储模型，检查编译开关与共享写寄存级的四种组合。每种组合使用相同的 2048 字节物理容量，覆盖连续行、槽位回绕、相邻单行组、不同组的累加标志、已发射行的偏移保持以及复位清空。

`test/ia_shared/run.py` 使用真实共享 RAM 模块、独立端口模型及整数参考模型，检查 IA 与 PS 并行访问、紧凑数据和普通数据、字节写掩码、跨存储字写入及有效列填零。

`test/ia_read_pipeline/run_external_equivalence.py` 对缓存管理器与指定提交的共享分支执行逐周期等价检查，覆盖八通道、十六通道 DMA 与紧凑编译开关的四种组合及全部公开接口。脚本同时检查外层加载器仅删除存储选择参数及其传递，并检查加载控制器源码保持相同。

`test/ia_read_pipeline/check_structure.py` 检查编译关闭后的紧凑输入使用者、额外寄存器、恢复加法及槽号位宽，并检查 RAM 返回端口与输出之间的寄存器边界。

```sh
python3 test/ia_read_pipeline/run.py --out build/ia_read_pipeline/control
python3 test/ia_shared/run.py --compact-offset-width 9 --bus-width 64 \
  --dma-lanes 8 --shared-write-stage 1 --out build/ia_read_pipeline/shared
python3 test/ia_read_pipeline/check_structure.py --out build/ia_read_pipeline/structure
python3 test/ia_read_pipeline/run_synthesis.py --out build/ia_read_pipeline/synthesis
```

读流水线测试使用支持 C++20 的编译器和 Verilator。结构检查及映射使用 pyosys 和项目提供的 `read_slang` 工作流程。

综合比较固定 IA 物理容量为 16384 字节，分别测量八通道和十六通道输入的编译配置。脚本记录 Yosys XC7 映射后的逻辑资源、RAM 返回端口到新增寄存器的组合单元数，以及该寄存器到阵列输入的组合单元数。这些结果描述布局前的资源映射和连接结构；DC 与 Vivado 的时序数值由相应工艺库、约束和实际实现报告给出。
