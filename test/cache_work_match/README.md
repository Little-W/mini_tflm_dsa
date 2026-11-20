# 缓存工作及需求字地址的保存比较

工作请求和预读快照在同一时钟边沿更新。当前实现同步保存字地址是否相同，后续握手直接读取该结果。需求请求的字地址比较根据同周期出队条件选择即将生效的地址，配置接收及复位期间由快照有效位控制结果的使用。

组号比较、缓存命中判断、需求队列、预取队列和全部请求及响应周期保持一致。综合器移除不再参与输出计算的30位字地址快照，保留两位字地址比较结果。

## 资源与路径

参考提交为 `a52df78e`，测量使用4 KiB缓存、128组、两路和64位总线。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑LUT | 3,746 | 3,547 |
| FF | 1,913 | 1,885 |
| RAM LUT | 436 | 436 |
| RAMB18E1 | 20 | 20 |
| 整个模块的最长寄存器间组合路径 | 14 | 14 |
| 工作请求至预取及快照控制寄存器 | 12 | 11 |
| 所有寄存器至预取及快照控制寄存器 | 12 | 11 |
| 快照字地址至预取及快照控制寄存器 | 12 | 无路径 |

控制终点包括 `pf_hit_checked`、`lookup_snapshot_valid` 和 `select_stage_valid`。完整SoC的组合路径使用对应固定源码的整机报告。

## 验证

时序归纳证明覆盖全部30位字地址取值、任意请求出队、配置接收、快照有效变化和复位。复位之后，每个有效快照的两位保存结果均等于直接比较。证明脚本使用实际新增更新表达式，并确认缓存其他逻辑与参考实现一致。

BUS32和BUS64各完成13个生产配置场景，逐周期比较全部13个公开输出。每种配置接收264个请求、完成260个请求，复位取消4个请求；预取队列达到8项，完成14次位置交换，并覆盖同周期入队与出队。

源码摘要、证明结果、数值结果及具体连接路径保存在 `docs/data/fpga_cache_word_matches.json`。

## 重现

```sh
python3 test/cache_work_match/run_formal.py --out build/word_matches/formal
python3 test/cache_storage/compare.py --reference-commit a52df78e \
  --cache-sets 128 --bus-widths 32 64 --profiles 4x2 \
  --jobs 1 --verilator verilator-modern --out build/word_matches/numeric
python3 test/cache_storage/synthesis.py --out build/word_matches/synthesis/current
python3 test/cache_work_match/paths.py \
  --reference build/word_matches/synthesis/reference \
  --current build/word_matches/synthesis/current \
  --proof build/word_matches/formal/summary.json --out build/word_matches/paths.json
```

参考网表使用 `a52df78e` 的缓存源码和相同配套模块生成。路径脚本核对参考及当前缓存、配套模块与形式证明的源码摘要。
