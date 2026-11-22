# PS 帧长度分组比较

`ps_frame_store` 将每个帧的长度相等条件分成至多三位的片段并行计算，再与帧有效状态和初始化条件共同生成一位请求资格。帧编号选择这一位资格；全部命令接收、错误通知、清除与数据返回周期保持原有行为。

## 实现与资源

长度比较使用普通相等运算和归约逻辑，片段结果保留组合边界。16 帧、每帧最多 512 行的实际请求资格表达式经相同流程映射后使用 127 个逻辑 LUT、224 个 FF，最长寄存器间路径为 5 级。参考版本使用 173 个 LUT、224 个 FF，最长路径为 6 级。两者均不使用 DSP 或块存储。

按输入字段筛选后的最长路径如下。完整图统计包含所有组合单元和寄存器控制端。

| 输入字段 | 参考版本 | 当前实现 |
|---|---:|---:|
| `frame_rows` | 6 | 5 |
| `frame_id` | 3 | 3 |
| `frame_init` | 6 | 4 |
| `frame_lengths` | 6 | 5 |

## 已完成检查

- 通过 `test/ps_request_ranges/run_formal.py` 提取两个版本实际请求资格表达式，确认此范围以外的源代码完全相同。5 组参数均通过不限制输入的 SAT 等价证明。
- 参数 `(MAX_FRAME_ROWS, FRAME_COUNT)` 为 `(1,1)`、`(3,3)`、`(47,16)`、`(512,16)` 和 `(1024,32)`。共完成 249,994 次严格四态比较，其中 228,864 次显式注入 `X` 或 `Z`。
- 使用 `test/ps_request_ranges/run_numeric.py` 的独立存储模型，逐周期比较参考提交 `8aa34632` 的全部公开输出。两组参数共完成 833 条命令、120,368 个 INT32 数据检查及 22,491 个周期；启用断言与未定义行为检查。
- 独立映射统计的图遍历完整，源文件散列值和原始报告散列值见 `validation.json`。

## 复现方法

在仓库根目录运行，`REFERENCE_ROOT` 指向提交 `8aa34632` 的完整源码目录：

```sh
python test/ps_request_ranges/run_formal.py \
  --source-root . --reference-root "$REFERENCE_ROOT" \
  --out build/ps_length_comparison/formal
python test/ps_request_ranges/run_numeric.py \
  --source-root . --reference 8aa34632 --jobs 1 \
  --out build/ps_length_comparison/numeric
python test/ps_request_ranges/run_numeric.py \
  --source-root . --reference 8aa34632 --jobs 1 --large \
  --out build/ps_length_comparison/numeric_large
python scripts/fpga/open_fpga_synth.py \
  --source-root build/ps_length_comparison/formal/current_source/512_16 \
  --case-config test/ps_frame_selection/synthesis_cases.json \
  --cases qualification --max-register-path-cells 10 \
  --require-register-path-limit --out build/ps_length_comparison/mapped
```

替换最后一条命令中的 `current_source` 为 `reference_source`，即可测量相同输入输出寄存器下的参考表达式。
