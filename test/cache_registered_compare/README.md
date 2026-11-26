# 缓存查询比较寄存

`conv_cache_snapshot_fields` 在同一个查询边沿保存请求字段与三位分组相等结果。`conv_cache_registered_equal` 在采样后归并分组结果，完整字地址和组号匹配与所保存的请求字段对应。

该结构保持公开输出的周期、请求范围选择以及 X/Z 输入的传播规则。模块使用普通比较、归约与寄存器描述。

## 验证

`run.py` 直接读取提交 `8b3728c0` 的完整字段模块和当前实现，比较全部公开输出。形式验证覆盖组号位宽 1、4、7、8，以及两种范围保存模式，共 8 个配置；各周期输入均可独立变化。两种范围模式各完成 18,082 次四态采样检查，共 36,164 次。

```bash
python3 test/cache_registered_compare/run.py --out build/cache_registered_compare
python3 test/cache_pipeline/run.py --fpga --bus-width 64 --read-width 128 \
  --line-bytes 16 --cache-bytes 4096 --profiles 1:2 4:2 --jobs 1 \
  --out build/cache_registered_pipeline
```

完整缓存回归覆盖两路、4096 字节数据容量、64 位总线和 128 位返回端口，分别检查一个与四个在途请求。每个配置包含 12 个事务场景，涵盖填充、预取、反压、配置切换、复位和错误返回。

## 综合测量

组号位宽为 7，范围直接随请求保存。Yosys/ABC9 使用 `physical-cost`，延迟目标 6667 ps，连接延迟参数 300 ps。路径统计同时检查输入到寄存器和寄存器到输出，保留完整连接关系。

| 项目 | 检查点 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 56 | 44 |
| 触发器 | 144 | 173 |
| 输入到寄存器组合级数 | 4 | 1 |
| 寄存器到输出组合级数 | 2 | 4 |

采样后的归并逻辑需要与缓存响应控制一起检查。整机组合级数以完整 SoC 映射结果为准。接口验证和局部测量记录分别见 `validation.json` 与 `measurement.json`。
