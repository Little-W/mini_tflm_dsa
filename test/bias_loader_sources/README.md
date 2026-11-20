# 偏置加载器测试源码依赖

`run.py` 从偏置测试入口取得实际 `read_slang` 命令，保留源文件和参数，通过 Slang 展开、Yosys 层次检查及连线检查确认公共模块齐全。完整共享加载器和缓存控制模型分别使用对应测试脚本生成的实际模型；Makefile 使用其实际源文件列表执行 Verilator 展开检查。

检查覆盖 `bias_read_depth`、`bias_loader_range`、`bias_group_index`、`bias_residency_timing`、`bias_cache_data` 和 `bias_loader_reuse/Makefile`，共 9 项。另有 6 组缓冲区等价和 5 组实际控制器关系、完整加载器等价检查。结果和脚本摘要保存于 [measurement.json](measurement.json)。

```bash
export PYTHONDONTWRITEBYTECODE=1
BIAS_SOURCE_OUT=/tmp/bias_loader_sources
python3 test/bias_read_depth/prove.py --out "$BIAS_SOURCE_OUT/read_proof"
python3 test/bias_read_depth/prove_shared.py --out "$BIAS_SOURCE_OUT/shared_proof"
python3 test/bias_loader_sources/run.py --out "$BIAS_SOURCE_OUT" --formal-results "$BIAS_SOURCE_OUT"
```

`bias_read_depth` 使用当前控制器和公共加法器，在两侧分别接入参考与当前的缓冲区和包装层。其比较范围包含全部公开输出、状态和存储操作，控制器消费共享索引时的关系使用实际控制状态独立证明。
