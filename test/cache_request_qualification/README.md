# 缓存请求资格与预取读取

本文保存的资源与路径记录使用当次固定源码、RTL 算术属性选择和 740 个 DSP 的总预算，具体源码与配置见随文测量报告。文中的运行命令用于当前工作区，采用普通 RTL 自动映射并生成新的资源与路径报告。

`conv_windowed_cache` 对四个查询位置分别计算填充冲突和组号匹配，请求出队时选择对应的单比特结果。实际数据读取地址、同拍填充转发和输出周期保持一致。

预取描述与查询快照更新时同时保存四个组号匹配结果。后续预取接收直接使用匹配状态。活动预取项的动态单路读取与固定条目的并行比较分别采用行为级存储，写入事件相同；已有接收寄存级参与块存储器读取推断。全部存储和算术均通过 RTL 描述实现。

## 完成的检查

- 四组参数的完整状态、存储和输出等价证明通过，共 61,344 个比较位。生产参数为 `SETS=16`、`WAYS=2`、`LINE_BYTES=128`、`DEMAND_DEPTH=2`、`BUS_WIDTH=64`、`READ_WIDTH=64`、`p_defer_retire_shift=1`，其中 43,900 个比较位全部通过。所有输入保持未约束，新增单路存储的每个位置与并行比较存储建立同写入状态关系。
- 查询冲突、有效位保存及预取快照资格的四态检查共完成 578,770 次比较，覆盖数据和控制 X/Z、同地址写入转发、复位及复位恢复。
- 生产缓存容量 4,096 字节下，深度 1 和深度 2 各完成十二项事务测试。覆盖持续命中、返回阻塞、冲突替换、范围错误、填充错误、预取、配置排空、复位取消、旁路读取及几何提示。两种深度的持续接受和返回间隔均为一个周期。
- 完整卷积前端在 `SIZE=16, BUS_WIDTH=64, LANES=8` 下完成普通缓存和窗口缓存共 84 个数值任务，以及 23 项控制检查。持续描述符、两路在途、返回顺序、背压及错误恢复均通过。

## 独立综合

生产缓存参数使用同一公共模块和相同综合配置进行测量。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 3,439 | 3,264 |
| 分布式存储 LUT | 420 | 412 |
| 名义 LUT 总数 | 3,859 | 3,676 |
| 寄存器 | 2,461 | 2,410 |
| DSP | 21 | 21 |
| RAMB36 | 0 | 1 |
| RAMB18 | 9 | 10 |
| 寄存器间最长组合单元数 | 10 | 10 |

两个连接图均完整。当前实现减少 183 个名义 LUT 和 51 个寄存器，增加一个 RAMB36 和一个 RAMB18。完整 SoC 中的外围资格和返回条件继续使用整机连接图统计。

## 重复执行

参考缓存源代码来自提交 `cedf4ed3`。以下命令生成证明日志、数值结果和资源报告。

```bash
mkdir -p build/cache_request_reference
git archive cedf4ed3 rtl/common rtl/npu/dma/cache rtl/npu/conv/conv_axi_span_reader.sv | tar -x -C build/cache_request_reference
python3 test/cache_request_qualification/run_formal.py --source-root . --reference-root build/cache_request_reference --profiles 2:2:16:2:32:32:0 16:2:128:2:64:64:1 4:1:32:1:64:32:0 4:1:32:4:64:32:0 --out build/cache_request_qualification/formal
python3 test/cache_request_qualification/run_offer_four_state.py --source-root . --reference-root build/cache_request_reference --out build/cache_request_qualification/offer_four_state
python3 test/cache_request_qualification/run_conflict_four_state.py --source-root . --reference-root build/cache_request_reference --out build/cache_request_qualification/conflict_four_state
python3 test/cache_request_qualification/run_valid_four_state.py --source-root . --reference-root build/cache_request_reference --out build/cache_request_qualification/valid_four_state
python3 test/cache_pipeline/run.py --source-root . --fpga --bus-width 64 --read-width 64 --line-bytes 128 --cache-bytes 4096 --profiles 1:2 2:2 --jobs 1 --out build/cache_request_qualification/pipeline
python3 test/conv_frontend/tools/run_numeric.py --source-root . --fpga --sizes 16 --continuous --out build/cache_request_qualification/frontend
python3 scripts/fpga/open_fpga_synth.py --source-root . --case-config test/cache_request_qualification/synthesis_cases.json --cases windowed_cache --out build/cache_request_qualification/synthesis --max-register-path-cells 10
```

`validation.json` 保存参数、通过数量、源代码散列和原始报告位置。详细证明日志与逐事务数据保存在对应测试目录。
