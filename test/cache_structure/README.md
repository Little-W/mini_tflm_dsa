# 缓存元数据职责与预测器阶段数组

## 模块职责

`conv_windowed_cache.sv` 管理请求接收、查找快照、填充、清理、响应队列和预取调度，共 1423 行。每个缓存路实例化一个 `conv_cache_metadata_way.sv`，后者独立管理有效位、同步标签、填充与命中时期、替换等级及等级来源，共 382 行。缓存路数、集合数、行容量、读取端口、更新优先级和返回周期保持一致。

元数据模块保留实际存储的读写使能、地址选择和旁路条件。`NPU_SIM_ASSERT` 对逻辑写事件建立的元数据记录随存储移入子模块；读取有效标签和消费替换等级时继续检查未知值。公共缓存观察模块仍通过父模块的事件、状态和接口工作。

`conv_next_use_predictor.sv` 共 359 行，使用以下数组表示类型和含义相同的流水阶段：

| 数组 | 下标范围 | 每项位宽 | 含义 |
| --- | --- | --- | --- |
| `tap_pipe` | 0–1 | 5 | 卷积核抽头索引 |
| `coordinate_good` | 0–2 | 1 | 坐标有效状态 |
| `candidate_good` | 3–6 | 1 | 后续使用候选有效状态 |
| `block_pipe` | 3–4 | 32 | 逻辑块索引 |
| `local_pipe` | 3–5 | 32 | 块内位置 |

32 位准备坐标和 16 位后续坐标分别保留各自类型。数组转换保持复位值、使能条件、阶段传递和公共输出周期。

## 验证方法

`run_formal.py` 从指定源码目录读取完整模块及其依赖，对所有公开输出、对应寄存状态和存储内容执行逐周期等价证明。外部输入不添加约束。比较时仅规范化元数据模块的实例层次名称，并在测试副本中为数组阶段建立对应名称；生产 RTL 不添加这些测试别名。

`check_metadata_four_state.py` 比较完整元数据读写逻辑的每个输出，覆盖不同集合数、路数、行大小和请求队列深度。所有外部事件独立驱动，配置、复位、地址、写入数据和控制均包含 X/Z。`check_predictor_four_state.py` 同时比较预测器公共输出与全部被数组化的阶段状态，并确认其余 RTL 语句保持相同。

实际 SRAM 功能模型用于 READ128/BUS64、16 集合、2 路、128 字节缓存行、请求深度 2 的完整数值和周期比较。该测试同时比较八个固定预取读取端口及活动选择端口，检查请求取消、错误返回、预取并发、队列满载和连续命中。

## 已完成结果

| 检查 | 覆盖 | 结果 |
| --- | --- | --- |
| 完整形式比较 | 4 个缓存配置与 2 个预测器配置，合计 109,838 个等价位 | 通过 |
| 生产缓存形式比较 | FPGA 与 `ASIC_SYNTHESIS` 配置各 43,644 个等价位；两侧各 41,291 个状态位 | 通过 |
| 元数据四态比较 | 4 组参数，48,192 次时钟边沿前后比较，14,392,492 个输出位比较 | 通过 |
| 元数据断言记录比较 | SETS=2、16、128，每组 4096 周期，5,980,160 次检查 | 通过 |
| 实际 ASIC SRAM 缓存数值比较 | 13 个场景，接收 250 个请求，完成 248 个，清理取消 2 个 | 通过 |
| 预取存储周期比较 | 八个固定读取端口和一个选择端口，9996 周期；队列最多 8 项 | 通过 |
| 预测器数值与周期比较 | 40 组配置、13,303 个输入向量、208,633 个周期 | 通过 |
| 预测器四态比较 | 214 个公共与阶段状态位，20,004 次比较，4,280,856 个位比较 | 通过 |
| 参数展开检查 | FPGA 缓存、ASIC SRAM 缓存及预测器，启用内部断言 | 通过 |

缓存连续命中时，请求接收与响应返回间隔均为 1 个周期。数值测试覆盖 11 次预取槽位轮换和 2 次同时入队出队。

完整结果、源码 SHA-256、日志 SHA-256 和参数列表见 `validation.json`。详细运行结果位于 `build/cache_structure/`。

工程源文件检查覆盖 145 个 RTL 文件、140 个模块和 5 个包；每个文件包含一个模块或包，NPU 文件最多 1488 行。ASIC、AXI-Lite、SoC 和五个 Makefile 单元入口的依赖与包顺序检查通过，Vivado 源文件覆盖及 Tcl 检查共 17 项通过。编译入口与结果文件的 SHA-256 同样记录在 `validation.json` 中。

## 运行方法

以下命令从仓库根目录执行，参考目录应包含待比较版本的完整 RTL 依赖。

```bash
python test/cache_structure/run_formal.py \
  --reference-root build/cache_structure/reference \
  --source-root . \
  --out build/cache_structure/formal_current

python test/cache_structure/check_metadata_four_state.py \
  --reference-root build/cache_structure/reference \
  --source-root . \
  --out build/cache_structure/metadata_four_state_current

python test/cache_structure/check_predictor_four_state.py \
  --reference-root build/cache_structure/reference \
  --source-root . \
  --out build/cache_structure/predictor_four_state_current

python test/cache_bram_reset/check_metadata_observer.py \
  --source-root . \
  --out build/cache_structure/metadata_observer_current

python test/conv_replacement/predictor_test.py \
  --reference-root build/cache_structure/reference \
  --source-root . --jobs 1 \
  --build build/cache_structure/predictor_numeric_current \
  --out build/cache_structure/predictor_numeric_current/summary.json

python test/cache_storage/compare.py \
  --reference-root build/cache_structure/reference --source-root . \
  --asic --extra-source asic/rtl/smic40_sram_1r1w.sv \
  --extra-source test/asic_regfile/sram_model.sv \
  --cache-sets 16 --line-bytes 128 --read-width 128 \
  --defer-retire-shift --bus-widths 64 --profiles 2x2 \
  --compare-prefetch-keys --jobs 1 \
  --out build/cache_structure/cache_numeric_asic_current
```
