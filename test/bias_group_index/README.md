# 偏置组首读取地址

`npu_top` 在配置接收时清零组合读索引，在有效 IS 输出时计算下一行索引。组首读取由 `group_read_start = is_mode && send_ia_trigger && !bias_sleep` 交给偏置缓冲区，缓冲区选择当前组基址。组首触发后的行索引寄存器在原有边沿清零。

## 完整缓冲区验证

`run_formal.py` 从实际 `npu_top.sv` 提取读索引计算、回绕条件的完整组合依赖和 `group_read_start` 连接，接入实际 `bias_loader_buffer.sv`。两个版本使用相同的当前缓冲区，比较全部寄存器、存储操作和公开输出。

两侧存储返回端接受同一任意 64 位值，每个周期均可变化。所有读写地址、使能、写掩码和写数据逐周期相同，因此相同初始存储能够保持每个存储位相同。输入、配置、暂停和触发序列均不受限制。

相对 `cfcc1a95` 的六组配置共 9,433 个比较位全部通过：

| SIZE | BUS_WIDTH | COUNT_WIDTH | GROUP_BLOCKS_MAX |
| ---: | ---: | ---: | ---: |
| 4 | 32 | 1 | 1 |
| 16 | 32 | 12 | 4 |
| 16 | 64 | 29 | 32 |
| 16 | 128 | 29 | 32 |
| 16 | 64 | 32 | 64 |
| 32 | 64 | 32 | 1 |

组合读索引在缓冲区未使用该地址时可以不同；全部存储操作和公开输出始终相同。测试逐一检查实际顶层表达式和缓冲区连接，源码校验值与逐项结果保存在 [偏置行边界验证记录](../bias_row_distance/validation.json)。

## 复现

```sh
python3 test/bias_group_index/run_formal.py \
  --reference-rev cfcc1a95 --out build/bias_group_index/formal
```

独立综合入口为 `prepare_measurement.py`，输入端口路径分析入口为 `measure_paths.py`。完整 SoC 的上游控制和存储器端点由整机综合一并统计。
