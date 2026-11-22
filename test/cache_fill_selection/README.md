# 缓存填充选择

`conv_windowed_cache` 分别计算填充容量、请求组号匹配、提示访问冲突和候选请求资格。需求接收事件 `req_fire` 在预取分支中统一检查两个条件：当前访问与候选填充使用相同缓存组，或者当前需求没有命中。普通填充分支检查同组访问。两种请求共用填充容量条件，并保持预取目标与当前需求命中位置的冲突检查。

该结构使用普通布尔运算，保留缓存接口、配置接收周期、填充状态转换、响应顺序和未知值传播行为。控制寄存器数量保持一致。

## 验证

参考源码为 `ef0dc75`。`run.py` 从两份实际 RTL 提取填充选择表达式，并检查其余缓存代码一致。组地址宽度为 1、3、7、8 位时，组合形式证明均通过，输入没有附加限制。Icarus 完成 589,824 次四态比较，覆盖控制选择、组号相同与不同、未知地址和填充状态。

逐周期比较检查全部 13 个公开输出，并观察预取队列的计数、优先顺序和活动描述。

| 配置 | 场景数 | 接收请求 | 完成请求 | 复位取消请求 | 预取队列最大项数 | 预取位置交换 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 64 位总线、64 位读取、2 项需求容量 | 13 | 250 | 248 | 2 | 8 | 14 |
| 64 位总线、32 位读取、4 项需求容量 | 13 | 264 | 260 | 4 | 8 | 14 |

两种配置均覆盖预取同时入队与出队，稳定命中时请求接收和响应返回的间隔均为 1 个周期。Verilator 编译未产生诊断信息。

## 独立模块综合

参数为 `SETS=128`、`WAYS=2`、`BUS_WIDTH=64`、`READ_WIDTH=64`、`LINE_BYTES=16`、`DEMAND_DEPTH=2`、`p_defer_retire_shift=1`。两份源码使用相同的 RTL DSP 属性处理和 740 个 DSP 的算术预算。

| 项目 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 3,345 | 3,295 |
| 分布式存储 LUT 位置 | 188 | 188 |
| 布局前 LUT 合计 | 3,533 | 3,483 |
| 触发器 | 2,023 | 2,023 |
| DSP | 21 | 21 |
| RAMB36 / RAMB18 | 1 / 26 | 1 / 26 |
| 最长寄存器间组合路径 | 10 级 | 10 级 |

表中的面积与级数来自独立缓存模块的完整连接图。SoC 总资源和器件时序使用完整设计的综合与布局布线结果。输入摘要、参数和验证统计保存在 [validation.json](validation.json)。

## 运行命令

在仓库根目录执行：

```bash
python3 test/cache_fill_selection/run.py --out build/cache_fill_selection/verification

python3 test/cache_storage/compare.py --reference-commit ef0dc75 \
  --cache-sets 128 --bus-widths 64 --read-width 64 --profiles 2x2 \
  --jobs 1 --out build/cache_fill_selection/production_compare

python3 test/cache_storage/compare.py --reference-commit ef0dc75 \
  --cache-sets 128 --bus-widths 64 --read-width 32 --profiles 4x2 \
  --jobs 1 --out build/cache_fill_selection/cycle_compare

python3 test/cache_fill_selection/measure.py --out build/cache_fill_selection/synthesis
```
