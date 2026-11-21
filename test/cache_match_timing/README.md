# 缓存预读字地址匹配验证

`conv_windowed_cache` 在同一时钟边沿保存预读请求、工作请求匹配状态和缺失请求匹配状态。实现先分别比较输入请求、队首请求与下一请求的字地址，再根据队列状态选择一位匹配结果。缺失状态下，工作请求的匹配条件直接使用队首或输入请求，需求请求的匹配条件使用当前需求地址。

这些比较保持原有寄存位置、接收条件、队列顺序和响应周期。32 位地址与元数据字段保留完整宽度。

## 组合等价检查

```sh
python test/cache_match_timing/check.py --out build/cache_match_timing/proof
```

检查脚本从指定 Git 版本及当前实际 RTL 提取请求选择逻辑和匹配寄存器的更新表达式，比较完整预读描述符、预读组地址、预读字地址及两个匹配结果。覆盖 1、2、4、8 项需求队列，以及 1 位和 7 位组地址。单项队列的指针固定为 RTL 使用的零；其余输入保持全部取值，包括所有前台状态、接收条件与 32 位地址。

## 完整缓存结构测量

```sh
python scripts/fpga/open_fpga_synth.py \
  --cases reference_cache_d1 candidate_cache_d1 reference_cache_d4 candidate_cache_d4 \
  --case-config build/cache_match_timing/proof/synthesis_cases.json \
  --out build/cache_match_timing/synthesis
python test/cache_match_timing/paths.py \
  --case-dir build/cache_match_timing/synthesis/reference_cache_d1 \
  --case-dir build/cache_match_timing/synthesis/candidate_cache_d1 \
  --case-dir build/cache_match_timing/synthesis/reference_cache_d4 \
  --case-dir build/cache_match_timing/synthesis/candidate_cache_d4 \
  --out build/cache_match_timing/paths.json
```

综合使用 128 组、2 路、16 字节缓存行及 64 位 AXI 总线。完整缓存的存储数组、标签、请求队列、预取和 AXI 读取控制均参与测量。路径分析分别检查寄存器之间、`req_valid` 到匹配寄存器、`req_addr` 到匹配寄存器的实际组合连接。端口路径的起点位于缓存模块边界。

| 项目 | 单项队列原版本 | 单项队列当前版本 | 四项队列原版本 | 四项队列当前版本 |
|---|---:|---:|---:|---:|
| LUT 单元数 | 3,602 | 3,615 | 3,768 | 3,670 |
| 全缓存寄存器间最长组合单元数 | 12 | 12 | 13 | 12 |
| 到匹配寄存器的最长组合单元数 | 11 | 7 | 12 | 9 |
| `req_valid` 到匹配寄存器的组合单元数 | 7 | 2 | 6 | 3 |
| `req_addr` 到匹配寄存器的组合单元数 | 6 | 7 | 6 | 7 |

当前生产前端使用单项缓存需求队列。输入有效条件只选择需求匹配结果，工作匹配结果独立于 `req_valid`。地址比较路径增加一级，完整 SoC 测量同时检查地址与控制的实际来源。

## DMA 集成验证

```sh
python test/window_dma/run.py \
  --reference-ref 4dee27ffec4dc891daf2681379f8b3fd27fd41f2 \
  --out build/cache_match_timing/window_dma --verilator verilator --jobs 2 --fpga
```

此测试检查连续命中、并行窗口请求、普通读取并发、随机坐标与停顿、读取错误、重新配置、无效描述符和复位。驻留窗口流逐周期比较 AXI、窗口返回和忙状态。

`measurement.json` 保存正式源码摘要、组合证明、窗口 DMA 结果和完整缓存的资源与路径计数。150 MHz 时序使用完整 SoC 的器件延迟及布局布线结果判断。
