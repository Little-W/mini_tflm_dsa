# 查询组号的并行比较

`conv_cache_lookup_set_match` 分别比较需求填充组号、已保存需求组号和当前工作组号与替换选择快照的组号。旁路状态和前台缺失状态在末级选择匹配结果，匹配资格继续用于需求访问、预取访问和元数据写入的冲突检查。

确定的状态选择单比特候选结果。状态包含未知值时，先使用原来的条件运算符合并完整组号，再进行相等比较，保留逐位四态合并规则。所有宏模式使用同一行为。该模块为组合逻辑，缓存公开接口、存储容量、请求接收和返回周期保持原有行为。

## 已完成检查

| 检查 | 范围 | 结果 |
|---|---|---|
| 组合形式等价 | 1、2、4、5、8 位组号，四种宏组合 | 20 组通过，所有输入无约束 |
| 四态比较 | 控制、各候选组号和目标组号的逐位完整组合，以及随机数据 | 1,294,336 次通过 |
| 完整缓存逐周期等价 | generic 和 FPGA；队列深度 1、2、4；包含 SoC 参数 | 8 组通过，共 123,056 个等价点 |
| 实际协议与数据 | Verilator 5.054；SoC 参数，预读开启 | 26 项通过 |

协议检查覆盖连续预读命中、返回反压、配置取消、完整地址和组号不匹配、范围错误及填充冲突。已准备的预读命中仍每周期接收和返回。

## 完整缓存映射

参数为 16 组、两路、128 字节缓存行、64 位总线、64 位返回、两项请求队列，启用预读。采用 6,667 ps 目标、300 ps 连线估计和最多八输入逻辑映射。

| 项目 | 参考提交 `3f8b847a` | 当前实现 |
|---|---:|---:|
| 逻辑 LUT | 3,037 | 3,039 |
| LUTRAM 名义 LUT | 100 | 100 |
| 合计名义 LUT | 3,137 | 3,139 |
| 最长寄存器间组合级数 | 10 | 10 |
| `fg_state` 到 `select_request_set_match` | 4 | 3 |
| `fg_state` 到 `pf_hit_checked` | 9 | 8 |
| `fg_state` 到 `pf_retire_q` | 9 | 8 |
| `windowed_q` 到 `pf_hit_checked` | 9 | 9 |

完整连接图包含全部保留层次，图检查完整且无组合环路。上述结果用于检查组合结构；目标器件的布局布线时序分析用于确认建立时间裕量。

源码摘要、全部参数、测试结果和映射数据保存在 `lookup_set_validation.json`。

## 复现

```bash
python3 test/cache_queued_preview/check_lookup_set_match.py --out build/cache_lookup_set/helper
python3 test/cache_queued_preview/check_parent.py \
  --reference 3f8b847a168df0afba77b08ebc25e707cf302a18 \
  --reference-request-from-git --preview 1 --jobs 1 --out build/cache_lookup_set/parent
python3 test/cache_pipeline/run_queued_preview.py \
  --cache-sets 16 --depth 2 --read-width 64 --mode fpga --jobs 1 \
  --verilator "$VERILATOR_ROOT/bin/verilator" --out build/cache_lookup_set/protocol
python3 test/cache_queued_preview/measure_preview.py --out build/cache_lookup_set/mapping
```
