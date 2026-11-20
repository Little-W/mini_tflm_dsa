# 缓存快照匹配

工作请求和缺失请求分别比较快照地址与集合索引。
`work_ready` 使用工作请求的匹配结果，`lookup_ready` 根据前台状态选择相应结果。
这一结构使工作请求出队及下一次预读不再经过缺失请求地址的高位比较。
请求队列、响应队列、预取队列、缓存数据和替换元数据均保持原有更新过程。

参考版本为 `af11d787a50663d62339e36bffc0694340c76734`。
参考 `conv_read_cache.sv` SHA-256 为 `2a790b1396bb8932cd1d2ab9dd3df249a7a1e2081b2cecd782436e87c6fa66ab`，
当前源码为 `beec10a943e7045a35d5a4a12ae6ec74a631ac67a381e6764b2181f6354437ca`。

## 验证结果

`run.py` 直接读取两份源码的组合表达式，核对其它源码完全相同。
在不约束输入、前台状态和计数值的条件下，`lookup_ready` 与 `work_ready` 的组合结果完全一致。
证明覆盖集合数及请求深度 `(2,1)`、`(16,4)`、`(32,4)`、`(128,4)`、`(256,8)`。

生产配置采用128个集合、两路、16字节缓存行、64位AXI和四个请求名额，总数据容量为4 KiB。
参考版本和当前版本在同一输入及AXI返回下逐周期比较全部13个公开输出，同时比较预取队列控制、活动项及逻辑次序。
13组场景全部通过：264个请求接收，260个完成，4个复位取消；在途请求达到4个，预取队列达到8项，完成14次优先项交换，并覆盖同时入队和出队。
驻留数据连续接收和连续返回的间隔均为1周期。

## 独立映射

| 项目 | 参考版本 | 当前版本 |
|---|---:|---:|
| 逻辑LUT | 3,658 | 3,653 |
| RAM LUT | 436 | 436 |
| 触发器 | 1,905 | 1,905 |
| RAMB18E1 | 20 | 20 |
| CARRY4 | 117 | 117 |
| 最长寄存器组合路径 | 14 | 14 |
| `demand_addr[31]` 到 `lookup_snapshot_valid` | 12 | 无组合路径 |
| 全部 `demand_addr` 位到 `lookup_snapshot_valid` | 13 | 3 |

映射参数与上述生产配置相同。综合最大驻留内存为279,684 KiB。
逐位路径、全部资源和源码摘要保存在 `docs/data/fpga_cache_lookup_timing.json`。
修改保持全部接口周期。

## 运行

```bash
python3 test/cache_lookup_timing/run.py --reference af11d787 --out build/cache_lookup/formal
python3 test/cache_storage/compare.py --reference-commit af11d787 --cache-sets 128 --bus-widths 64 --profiles 4x2 --jobs 1 --verilator verilator-modern --out build/cache_lookup/production_interface
python3 test/cache_storage/synthesis.py --out build/cache_lookup/synthesis/current
python3 test/cache_lookup_timing/paths.py --reference "$REFERENCE_CACHE_SYNTH" --current build/cache_lookup/synthesis/current --proof build/cache_lookup/formal/summary.json --out build/cache_lookup/paths.json
```

`REFERENCE_CACHE_SYNTH` 指向相同四份参考源码和相同参数的独立综合目录。
可将参考版本中的 `conv_read_cache.sv`、`conv_sdp_ram.sv`、`conv_axi_span_reader.sv`、`REGFILE.v` 保存到一个目录，再通过 `test/cache_storage/synthesis.py --reference` 生成该结果。
