# 缓存释放行号的并行解码

`conv_cache_retire_decode` 分别计算正式输入请求和已保存请求的释放行号，再选择完整的 32 位结果。每组行号使用两个四选一固定位移级，分别处理移位量的低两位和高两位。末级同时选择来源并处理禁止释放标志。

来源选择保留过程 `if` 的四态语义；移位量含有未知位时保留完整 32 位逻辑右移的语言语义。元数据存储格式、需求请求次序和响应周期保持。

## 验证

```sh
python3 test/cache_retire_decode/check.py --out build/cache_retire_decode/helper
python3 test/cache_retire_decode/check_parent.py --reference e4415016 --preview 0 --jobs 1 --out build/cache_retire_decode/plain
python3 test/cache_retire_decode/check_parent.py --reference e4415016 --preview 1 --jobs 1 --out build/cache_retire_decode/preview
python3 test/cache_retire_decode/measure.py --out build/cache_retire_decode/mapping
```

独立解码的形式比较使用全部 65 位自由输入，检查全部 32 位输出。通用条件和 FPGA 综合条件各执行 279,568 次四态比较，每个输入位均覆盖 `0`、`1`、`X`、`Z`。

完整缓存比较覆盖五组参数、预读开启与关闭、通用和 FPGA 综合条件，共 20 组。比较范围包含全部公开输出及共同寄存状态，每周期比较且不添加输入约束。最大配置为 256 组、两路、128 字节缓存行、64 位 AXI、128 位读取、两项需求队列。

上传性能环境中的 16 PE、64 KiB 缓存配置运行 `dw3x3_s1_48_c8` 和 `conv3x3_32_c16_o16`，全部数值通过独立输出参考检查；60,996 个前端周期的请求、返回和描述符记录逐项相同，两个算子的执行周期分别保持 32,882 和 28,092。

## 完整前端映射

在 16 行、8 通道、64 位读取、16 组、两路、128 字节缓存行、两项需求及响应队列的完整前端中，只替换释放行号计算后的结果如下。

| 项目 | 参考实现 | 并行解码 |
|---|---:|---:|
| `request_y_q` 到 `demand_retire` 的最长寄存器路径 | 11 级 | 9 级 |
| 完整前端最长寄存器路径 | 14 级 | 13 级 |
| 逻辑 LUT | 16,067 | 16,128 |
| 名义 LUT 总数 | 16,203 | 16,264 |
| 触发器 | 7,422 | 7,422 |

完整连接图已检查，未发现组合环；映射前后的逻辑等价检查通过。以上级数来自综合映射后的完整寄存器连接图，物理建立时间需要实现工具的时序报告确认。源文件哈希、参数、证明结果和报告位置保存在 `validation.json`。
