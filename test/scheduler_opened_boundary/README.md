# 帧计数增量的组合边界

本文保存的资源与路径记录使用当次固定源码、RTL 算术属性选择和 740 个 DSP 的总预算，具体源码与配置见随文测量报告。文中的运行命令用于当前工作区，采用普通 RTL 自动映射并生成新的资源与路径报告。

`ps_window_scheduler` 对 `opened_after_init` 的完整结果保留组合边界。各位仍由现有并行低位归约和异或表达式计算，位宽、接口、状态更新和全部参数化表达式保持一致。

## 已完成检查

- `check_source.py` 核对两个版本的完整源代码，确认差异仅包含等宽声明分组和 `opened_after_init` 的 `keep` 属性。
- 4 组参数在 FPGA 与 ASIC 两种模式下共完成 666,384 次公开输出的严格逐周期比较，其中 228,992 个周期显式注入四态输入。测试同时检查候选存在性保存关系和执行期间描述符稳定性。
- 独立 C++ 调度模型完成 975 个用例、182,426 条命令，涵盖完整帧、切片帧、压力恢复、提前结束、编号复用、尾部尺寸与无效配置。启用断言和未定义行为检查。
- 生产参数 `SIZE=16`、`FRAME_COUNT=16`、`MAX_REUSE_TILES=32`，相同依赖及映射选项下，完整模块从 1,161 个 LUT 减少至 1,152 个 LUT。两个版本均使用 917 个 FF、13 个 DSP、2 个 RAMB36，最长寄存器间路径为 9 级。`opened` 到 `ready` 和 `phase` 的路径由 8 级减为 7 级；到元数据读取使能的最长路径仍为 8 级。

## 复现方法

在仓库根目录运行，`REFERENCE_ROOT` 指向提交 `8aa34632` 的源码目录：

```sh
python test/scheduler_opened_boundary/check_source.py \
  --source-root . --reference-root "$REFERENCE_ROOT" \
  --out build/scheduler_opened_boundary/source_identity.json
python test/scheduler_candidate_exists/run_four_state.py \
  --source-root . --reference-root "$REFERENCE_ROOT" \
  --out build/scheduler_opened_boundary/four_state
python test/ps_compression/run_window_scheduler.py \
  --source-root . --fpga --out build/scheduler_opened_boundary/numeric
python scripts/fpga/open_fpga_synth.py \
  --source-root . --case-config test/scheduler_candidate_exists/synthesis_cases.json \
  --cases scheduler \
  --max-register-path-cells 10 --require-register-path-limit \
  --out build/scheduler_opened_boundary/mapped
```

原始报告位置、参数及散列值记录在 `validation.json`。
