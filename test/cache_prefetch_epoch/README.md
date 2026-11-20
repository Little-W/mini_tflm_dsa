# 预取项代次比较寄存

每个物理预取位置保存一位代次比较结果。接收新需求时，所有已有预取项同时比较新需求代次；写入新预取项时，使用即将在当前时钟边沿生效的需求代次。配置接收和复位清除比较结果，有效位控制哪些比较结果参与优先选择。

同周期接收新需求与新预取项时，比较两份新代次。原有预取内容、逻辑位置到物理位置的映射、循环优先顺序、入队及出队周期保持一致。

## 映射结果

参考提交为 `2bd1d2b3`。测量采用4 KiB缓存、128组、两路和64位总线。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑LUT | 3,653 | 3,746 |
| FF | 1,905 | 1,913 |
| RAM LUT | 436 | 436 |
| RAMB18E1 | 20 | 20 |
| 整个模块的最长寄存器间组合路径 | 14 | 14 |
| 寄存器至活动预取地址及代次 | 13 | 10 |
| 预取键存储至活动预取地址及代次 | 13 | 2 |
| 保存的比较结果至活动预取地址及代次 | 无路径 | 10 |
| 预取键存储至保存的比较结果 | 无路径 | 7 |

完整SoC结果由对应固定源码的整机报告记录。

## 验证

8个物理位置分别完成时序归纳证明：每个有效位置保存的比较结果始终等于该位置的32位代次与当前需求代次的直接比较。证明覆盖全部输入取值、同时接收和清空操作，存储内容初值任意，控制状态从复位状态开始。证明脚本检查实际源码中新增的更新表达式，并确认除此之外的缓存实现与参考源码一致。

BUS32和BUS64各完成13个生产配置场景，逐周期比较全部13个公开输出。每种总线配置接收264个请求、完成260个请求、取消4个请求，预取队列达到8项，完成14次位置交换，并覆盖同周期入队与出队。测试覆盖复位取消在途请求。

源码SHA256、形式证明结果、数值比较结果及实际连接路径保存在 `docs/data/fpga_cache_prefetch_epoch.json`。

## 重现

```sh
python3 test/cache_prefetch_epoch/run_formal.py --out build/epoch_match/formal
python3 test/cache_storage/compare.py --reference-commit 2bd1d2b3 \
  --cache-sets 128 --bus-widths 32 64 --profiles 4x2 \
  --jobs 1 --verilator verilator-modern --out build/epoch_match/numeric
python3 test/cache_storage/synthesis.py --out build/epoch_match/synthesis/current
python3 test/cache_prefetch_epoch/paths.py \
  --reference build/epoch_match/synthesis/reference \
  --current build/epoch_match/synthesis/current \
  --proof build/epoch_match/formal/summary.json --out build/epoch_match/paths.json
```

参考网表应使用提交 `2bd1d2b3` 的缓存源码和相同配套模块生成；路径脚本核对两份网表、形式证明及所有配套源码的摘要。
