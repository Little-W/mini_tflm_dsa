# IA 写入范围编码

`ia_loader_cache_mgr` 在写入缓存分块的第零行时保存本次写入的结束列。对于 `SIZE <= 32` 且 `DMA_LANES < SIZE` 的配置，每个原始 DMA 通道并行计算结束列和行内资格，再由最高有效通道选择写入范围。写使能直接归并这些行内有效通道。

列偏移由普通 `case` 完整列举。已知偏移使用原始通道编码；包含 X/Z 的偏移使用完整物理列移位表达式。因此，任意有效掩码、越过行尾的通道和四态传播均保持原有语义。其他参数配置继续使用物理列编码。

接口、存储容量、时钟边沿和请求周期保持不变。实现使用常规组合 RTL，所有存储单元由综合工具推断。

## 验证结果

| 检查 | 范围 | 结果 |
|---|---|---|
| 完整输入证明 | 27 组 `SIZE`、`DMA_LANES` 参数，包含非二次幂行宽 | 通过 |
| 四态比较 | 全部列偏移、低八位有效掩码的逐项检查，以及每组 20,000 个含 X/Z 的随机输入 | 982,368 次通过 |
| 完整 IA 等价检查 | 生产、通用、局部 RAM 三种配置，31,240 个等价目标位 | 通过 |
| 八通道写入数值 | 16 个列起点、65,536 组字节与偏移、20,000 个随机周期 | 通过 |
| 预取和请求协议 | 三种实现配置，每种分别使用受阻授予和持续授予 | 1,518 条命令、1,088,640 个数值检查通过 |
| 请求取消与恢复 | 六次明确取消，随后继续执行请求 | 通过 |

完整 IA 等价检查未约束输入，比较公开输出、可对应的内部状态和有效 RAM 写入数据。生产与通用配置启用 `p_register_dma_request=1`；局部 RAM 配置使用默认请求方式。预取测试同时检查缓存复用、不同尾部宽度、槽号回绕、需求请求优先级以及背景传输期间重新配置。

与相同配置的参考设计比较，FPGA 有序任务在受阻授予和持续授予下分别为 59,396 与 59,337 周期，通用无序任务分别为 58,759 与 58,677 周期，均保持相同周期数。

## 独立综合

生产参数为 `SIZE=16`、`BUS_WIDTH=64`、`COUNT_WIDTH=29`、`CACHE_BLOCKS=32`、`EXTERNAL_RAM=1`、`ORDERED_JOB=1`、`PS_FRAME_COUNT=16`，启用原始 DMA 通道排列、共享写入阶段及请求寄存。

| 指标 | 参考设计 | 当前设计 |
|---|---:|---:|
| 名义 LUT 数 | 5,001 | 5,034 |
| 触发器 | 2,537 | 2,537 |
| DSP | 28 | 28 |
| RAMB36 / RAMB18 | 2 / 1 | 2 / 1 |
| 最长寄存器间组合级数 | 10 | 10 |
| `ext_dma_wr_valid` 到范围存储数据端 | 9 | 7 |
| `ext_dma_wr_valid` 到范围存储写使能 | 8 | 5 |

端口深度统计包含 IA 内部全部连接，起点是 `ext_dma_wr_valid`，终点是 `slot_written_cols` 的同步存储端口。上游模块的组合逻辑由完整 SoC 测量统计；目标频率需结合目标器件的实现时序报告检查。

## 运行检查

从仓库根目录执行，`REFERENCE_ROOT` 指向保留的参考源码目录。

```bash
python test/ia_write_extent/check_extent.py \
  --source-root . --reference-root "$REFERENCE_ROOT" \
  --out /tmp/ia_write_extent_inputs

python test/ia_write_extent/run_formal.py \
  --source-root . --reference-root "$REFERENCE_ROOT" \
  --out /tmp/ia_write_extent_state

python test/ia_shared/run_receive_write.py \
  --source-root . --out /tmp/ia_write_extent_values --fpga

python test/ia_request_stage/run_prefetch.py \
  --source-root . --out /tmp/ia_write_extent_prefetch --ordered-job --fpga
```

通用有序任务省略 `--fpga`，通用无序任务同时省略 `--ordered-job`。完整输入脚本可通过 `--reuse-results` 复用已完成的四态结果；复用前会检查 RTL、生成模型、测试程序、可执行程序和输出日志的 SHA256，以及全部参数和比较次数。

生产综合配置由 `test/ia_request_stage/prepare_measurement.py` 生成。端口路径可在两份独立综合完成后统计：

```bash
python test/ia_write_extent/measure_paths.py \
  --reference "$REFERENCE_MAPPING" --current "$CURRENT_MAPPING" \
  --out /tmp/ia_write_extent_paths.json
```

`validation.json` 保存源码散列、参数、检查摘要和测量结果。
