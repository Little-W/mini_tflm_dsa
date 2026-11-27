# 缓存替换发送的并行资格

窗口缓存分别准备需求与预取的填充资格。已保存快照、容量、地址身份、替换冲突和提示占用先形成单比特结果，当前请求的接收、组号匹配及命中状态在末级决定是否发送。预取队列直接使用预取分支的发送结果更新退休状态。

预取命中有效位将已有查询资格与本周期替换发送分开计算。填充地址的上界采用完整无符号分组比较，三位局部比较经过树状归并后选择完整地址。所有寄存状态、复位行为、公开端口、队列容量及外部周期保持一致。

## 生产模块

| 模块 | 作用 |
| --- | --- |
| `conv_cache_select_launch_ready` | 并行计算需求和预取的早到资格 |
| `conv_cache_select_launch_merge` | 用五个控制输入归并两类发送结果 |
| `conv_cache_select_launch` | 输出填充发送及预取发送结果，保持未知控制的条件选择行为 |
| `conv_cache_prefetch_check_ready` | 合并预取快照与填充元数据冲突条件 |
| `conv_cache_prefetch_check` | 在末级处理替换发送及配置清除，生成下周期命中检查有效位 |

`conv_windowed_cache` 使用既有 `conv_cache_snapshot_equal` 归并完整预取标签比较，并为填充上界选择既有 `parallel_unsigned_compare` 的分组实现。全部生产文件使用 RTL 描述推断硬件资源。

## 正确性检查

```sh
python3 test/cache_select_launch/check.py \
  --out build/cache_select_launch/qualification
python3 test/cache_select_launch/check_fill_end.py \
  --out build/cache_select_launch/fill_end
python3 test/cache_queued_preview/check_parent.py \
  --reference 3b1c0c5b664d28397dcb257ad8b9cbadea730b6b --preview 1 --jobs 1 \
  --out build/cache_select_launch/parent
python3 test/cache_queued_preview/check_parent.py \
  --reference 3b1c0c5b664d28397dcb257ad8b9cbadea730b6b --preview 0 --jobs 1 \
  --out build/cache_select_launch/preview_off
```

发送及有效位测试从参考生产代码提取表达式，在 generic 和 FPGA 宏模式下检查全部控制组合，共完成 524,288 次四态比较。填充边界测试比较两类完整候选和最终地址，共 96 个输出位；五种缓存行和读取位宽组合分别运行两种宏模式，完成十项无约束 SAT 证明与 179,360 次四态比较。

完整缓存比较覆盖全部公开输出与共有寄存状态，输入不增加协议假设。请求深度包含 1、2、4，预读开启和关闭分别覆盖 generic 与 FPGA 模式，共十六组配置。实际 SoC 配置为 16 组、2 路、128 字节缓存行、64 位总线与两项请求队列。

## 协议与数值检查

```sh
python3 test/cache_pipeline/run_queued_preview.py --no-direct-response \
  --mode fpga --cache-sets 16 --depth 2 --read-width 64 --jobs 1 \
  --out build/cache_select_launch/protocol
python3 test/frontend_pipeline/run_numeric.py --target fpga \
  --cache-response-depth 2 --size 16 --lanes 8 --bus-width 64 \
  --cache-sets 16 --cache-ways 2 --line-bytes 128 --narrow-mode 2 \
  --windowed --prefetch --out build/cache_select_launch/numeric
```

Verilator 5.054 的二十六项缓存协议场景通过，包含连续预读、每周期接收及返回、随机反压、配置取消、同组冲突与响应顺序检查。四十二项独立方程数值任务及 1024 组配置通过，总周期数为 144428，与采用响应寄存的参考版本一致。

## 完整连接测量

```sh
python3 test/cache_select_launch/measure.py \
  --out build/cache_select_launch/cache_mapping
python3 test/cache_select_launch/measure.py --frontend --labels current \
  --out build/cache_select_launch/frontend_mapping
```

完整缓存的同配置比较为 2985 → 3014 个逻辑 LUT，触发器均为 1970 个，全部寄存器之间的最长组合路径保持 10 级。当前请求接收信号到发送结果为 1 级，到预取退休、命中有效位、替换决策有效位及填充状态为 2 级。

在包含完整前端的连接图中，请求索引到预取退休和命中有效位的路径从 13 级降到 8 级，到替换决策和填充状态的路径从 12 级降到 8 级。地址到填充上界寄存器为 6 级。该次前端测量还包含描述符准备路径，完整前端最长为 14 级；描述符与前端配置的后续优化需另行测量。

路径分析展开所有保留层次，完整图检查同时覆盖数据、使能和存储器端点。内部观察点仅用于统计指定信号之后的组合深度，资源数量取自原始生产网表。`validation.json` 记录源码和报告的 SHA-256 校验值。

映射使用 6667 ps 目标周期、300 ps 线延迟模型和 ABC9 功能验证。150 MHz 的实际建立时间由目标器件布局布线报告确认。
