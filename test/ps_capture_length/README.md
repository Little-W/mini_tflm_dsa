# 部分和接收行数比较

`ps_frame_store.sv` 分别计算当前接收行数和递增一次后的行数是否满足帧长度。`encoder_start` 选择已经生成的单比特比较结果，帧结束检查沿用现有接收周期。

递增比较使用公共模块 `add_equal`，并设置 `p_infer_dsp=0`。当 `LENGTH_BITS < 32` 时，比较宽度增加一位以保留加法进位；其他宽度按 `LENGTH_BITS` 位计算。该处理保持原始整数表达式的数值范围。四态输入使用完整的加法比较表达式，保留未知值传播。

## 验证范围

| 检查 | 范围 | 结果 |
| --- | --- | --- |
| 组合 SAT 证明 | `LENGTH_BITS=1,2,6,10,16,31,32,33`，输入自由 | 8 组通过 |
| 四态比较 | 随机 `0/1/X/Z`、全零、全一和逐位进位 | 40,425 次通过 |
| 完整存储数值比较 | 参考版本 `ef0dc75`，818 条命令 | 89,648 个 INT32 值、18,501 个周期通过 |

数值测试同时运行参考模块和当前模块，并使用独立软件存储模型检查结果。C++ 编译启用 UBSan。

## 局部组合结构

测量模型保存十位接收行数、十位帧长度和 `encoder_start`，并保存比较结果。两种实现使用相同输入与输出寄存器。下表仅统计该比较表达式及测量寄存器。

| 项目 | 参考表达式 | 当前表达式 |
| --- | ---: | ---: |
| LUT | 8 | 24 |
| 触发器 | 22 | 22 |
| DSP | 0 | 0 |
| 寄存器间最大组合级数 | 6 | 4 |

实现以少量并行比较逻辑缩短帧结束控制路径。实际生产模块没有新增寄存器。完整 SoC 的面积和时序由整机测量单独记录。

## 执行命令

在仓库根目录执行：

```bash
python3 test/ps_capture_length/run.py \
  --source-root . --out build/ps_capture_length/formal
python3 test/ps_request_ranges/run_numeric.py \
  --source-root . --reference ef0dc75 --jobs 1 \
  --out build/ps_capture_length/numeric
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/ps_capture_length/formal/synthesis_cases.json \
  --cases reference current --out build/ps_capture_length/synthesis
```

`validation.json` 保存源码摘要、检查数量和测量结果。
