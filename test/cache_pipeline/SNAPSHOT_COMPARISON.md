# 缓存查询比较结果保存

`conv_cache_snapshot_fields` 在已有查询边沿保存请求字段、三组完整字地址比较结果和一组缓存集合比较结果。比较两侧使用同一周期的输入；状态条件与这些结果共同形成下一周期的访问资格。该设计维持公开输出的采样边沿、请求接收能力和响应周期。

## 完整前端测量

比较版本为 `83946820`，两侧使用相同的完整前端生产参数与 XC7 映射设置。ABC9 每批处理 64 个模块，并单独处理叶模块。LUT 合计包含分布式 RAM 的名义 LUT 位置，实际布局后的资源利用率需由器件实现报告确定。

| 项目 | 比较版本 | 当前设计 |
| --- | ---: | ---: |
| 逻辑 LUT | 16,677 | 16,672 |
| 分布式 RAM LUT | 68 | 68 |
| LUT 合计 | 16,745 | 16,740 |
| 触发器 | 6,241 | 6,181 |
| DSP | 18 | 18 |
| RAMB36 / RAMB18 | 1 / 22 | 1 / 22 |
| 最长寄存器路径 | 17 | 17 |
| 输入至寄存器路径 | 17 | 17 |
| 寄存器至输出路径 | 12 | 12 |
| 输入至输出路径 | 2 | 2 |
| 保存的查询字段至填充控制寄存器路径 | 15 | 11 |

上述深度按映射后网表中经过的组合单元逐一计数，计入进位单元和专用多路选择单元。测量使用完整前端连接，保留输入与输出边界路径。

## 功能验证

实际请求来源选择与范围采样检查覆盖 `p_set_width` 为 1、2、4、8、16 的五种配置，逐项完成有界时序比较与归纳证明。通用快照模块的另五种配置完成两周期时序比较；该模块所有比较状态均在一个采样边沿更新。两类检查均允许外部输入自由变化。

四态仿真共检查 33,904 个输入样本，覆盖单个位未知、高阻、全未知、全高阻、全零、全一和随机数据，逐位比较完整请求及四项公开访问资格输出。

```bash
python test/cache_pipeline/check_snapshot_range_capture.py \
  --reference-root /path/to/reference \
  --out build/snapshot_comparison_selected

python test/cache_pipeline/check_snapshot_functions.py \
  --reference-root /path/to/reference \
  --out build/snapshot_comparison_generic
```

完整参数、文件摘要和检查结果见 [snapshot_comparison_validation.json](snapshot_comparison_validation.json)。
