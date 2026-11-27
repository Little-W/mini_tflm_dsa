# 连续预读的并行组号匹配

`conv_cache_preview_set_match` 同时比较正式请求的地址哈希和窗口索引与预读快照组号。每组两位哈希直接比较异或结果，`windowed_q` 与索引有效位只选择最终的一位匹配结果。`conv_cache_queued_preview` 独立归并完整 32 位地址和接收状态，组号结果参与最后一级资格计算。

窗口模式使用原有过程式 `if` 语义。控制信号为未知值时，组号计算选择地址哈希；地址、索引或保存组号中的未知值和高阻态保持原有比较结果。预读资格要求全部匹配条件为确定的一，保存的范围状态为确定的零或一。公开接口、队列容量、接收周期和返回周期保持原有行为。

## 验证结果

| 检查 | 范围 | 结果 |
|---|---|---|
| 组合形式等价 | 1、2、4、5、8 位组号，四种宏组合 | 20 组通过，全部输入无约束 |
| 四态比较 | 控制信号的全部四态组合，逐位地址、索引、组号及随机数据 | 1,029,120 次通过 |
| 完整缓存逐周期等价 | generic、FPGA 两种模式；队列深度 1、2、4；包含 SoC 参数 | 8 组通过，共 123,048 个等价点 |
| 实际协议与数值 | 16 组、两路、128 字节缓存行、64 位总线和返回、两项队列 | 26 项通过 |

协议测试使用 Verilator 5.054，覆盖连续预读、返回反压、配置取消、地址或组号不匹配、范围错误以及填充冲突。已准备的连续预读命中保持每周期接收和返回，正式接收与返回发生在同一周期。

## 完整缓存映射

测量使用上述 SoC 参数，启用 `p_preview_request=1`。目标组合延迟为 6,667 ps，连线估计为 300 ps，最多八输入逻辑映射。所有层次均展开参与连接图检查。

| 项目 | 参考版本 | 并行组号匹配 |
|---|---:|---:|
| 逻辑 LUT | 3,032 | 3,037 |
| LUTRAM 名义 LUT | 100 | 100 |
| 合计名义 LUT | 3,132 | 3,137 |
| 最长寄存器间组合级数 | 12 | 10 |
| `windowed_q` 到 `preview_match` | 4 | 2 |
| `windowed_q` 到 `pf_hit_checked` | 12 | 9 |
| `fg_state` 到 `pf_hit_checked` | 11 | 9 |

上述级数来自完整映射连接图。布局布线后的建立时间裕量需由目标器件时序分析确认。源码摘要、形式检查、协议场景和映射数据保存在 `parallel_set_validation.json`。

## 复现

```bash
python3 test/cache_queued_preview/check_helper.py --out build/cache_parallel_set/helper
python3 test/cache_queued_preview/check_parent.py \
  --reference 92f722e6c3adbce254672dea17aa170d73f9a9c6 \
  --reference-request-from-git --preview 1 --jobs 1 \
  --out build/cache_parallel_set/parent
python3 test/cache_pipeline/run_queued_preview.py \
  --cache-sets 16 --depth 2 --read-width 64 --mode fpga --jobs 1 \
  --verilator "$VERILATOR_ROOT/bin/verilator" --out build/cache_parallel_set/protocol
python3 test/cache_queued_preview/measure_preview.py --out build/cache_parallel_set/mapping
```

`inspect_preview_paths.py` 从保存的综合寄存器名称恢复起点和终点，在完整网表中重新计算指定路径。用于观察 `preview_match` 的采样终点只加入分析图，资源统计采用原始映射网表。
