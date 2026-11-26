# 缓存有效位存储与替换冲突资格

`conv_cache_metadata_way` 在至少 16 组的配置中使用普通数组 RTL 推断分布式存储，保存每组有效标志。查询端口数、异步读取行为、配置清除过程和写入转发保持原有定义。

`conv_windowed_cache` 先计算当前需求与替换缓存行的身份关系，再用查询就绪信号限定最终冲突结果。身份计算包含需求状态、旁路状态、组号、路号和被选择路的命中结果。通用模式继续使用原有四态处理。

## 功能检查

完整缓存比较从提交 `d485d636` 提取参照 RTL，逐周期检查全部公开输出、共同寄存状态和存储内容。输入不附加约束。配置覆盖 1、2、4 项需求容量，1、2 路缓存，32、64 位总线，以及启用和关闭请求预读。通用模式显式使用 `-USYNTHESIS -UXILINX_FPGA`。

| 检查范围 | 配置数 | 检查数量 |
| --- | ---: | ---: |
| 完整缓存等价 | 16 | 244,195 个等价点 |
| 替换冲突资格 | 12 | 1,769,472 次四态输出比较 |
| 元数据读写与转发过程 | 6 | 612,800 次四态输出比较 |

运行命令：

```bash
python test/cache_metadata_storage/check_parent.py --reference d485d636 --preview 0 --out build/cache_metadata_disabled --jobs 2
python test/cache_metadata_storage/check_parent.py --reference d485d636 --preview 1 --out build/cache_metadata_enabled --jobs 2
python test/cache_metadata_storage/check_victim.py --reference d485d636 --out build/cache_metadata_victim
python test/cache_queued_preview/check_metadata.py --reference d485d636 --out build/cache_metadata_process
```

详细结果、源码 SHA-256 和工具输入保存在 `results/` 与 `validation.json`。

## 资源和组合深度

两侧均采用相同的 physical-cost 映射设置：目标延时 6,667 ps、连线延时 300 ps、最大 LUT 输入数 8。名义 LUT 数包含逻辑 LUT、LUTRAM 和 SRL。

完整缓存使用 16 组、2 路、128 字节缓存行、64 位读写数据、2 项需求容量和请求预读。

| 完整缓存指标 | 参照 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 3,040 | 2,929 |
| LUTRAM | 68 | 100 |
| 名义 LUT 总数 | 3,108 | 3,029 |
| 触发器 | 2,002 | 1,970 |
| DSP | 18 | 18 |
| 最长寄存器间组合级数 | 10 | 10 |

完整 DMA 使用同一份 `mapping_following_capacity_source` 前端及相同依赖，只替换上述两个缓存文件，`CACHE_BLOCKS=32`。名义 LUT 从 16,239 降至 16,175；该组合的最长路径为 18 级，参照为 17 级。起点是前端 `column_lane_allowed_q`，终点是缓存 `lookup_valid_q`。完整 DMA 的十级目标仍需结合前端请求字段计算继续处理。
