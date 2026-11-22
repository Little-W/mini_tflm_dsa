# PS 帧资格并行选择

本文保存的资源与路径记录使用当次固定源码、RTL 算术属性选择和 740 个 DSP 的总预算，具体源码与配置见随文测量报告。文中的运行命令用于当前工作区，采用普通 RTL 自动映射并生成新的资源与路径报告。

每个帧目录项独立计算初始化资格或长度相等条件，`request_frame_match` 的 `keep` 属性保留独立的比较结果。`frame_id` 只选择最终的一位资格。行数范围、请求接收、压力通知、容量错误与数据回放保持原有逐周期行为。未知行数继续使用完整的四态关系表达式。

## 完成的检查

参考源来自 `9d75f75a`。实际请求资格表达式以 `MAX_FRAME_ROWS/FRAME_COUNT` 为 `1/1`、`3/3`、`47/16`、`512/16`、`1024/32` 的五组参数完成全部二值输入证明。每组同时检查严格四态结果，合计 249,994 次比较，其中 228,864 次包含逐位 X/Z 注入。请求资格区域以外的源代码逐字相同。

完整存储模块使用独立内存模型检查数值，并与参考版本逐周期比较所有公开输出。四帧、每帧上限 16 行及 256 行两种配置合计通过 833 条命令、120,368 个 INT32 数值和 22,491 个周期，编译和运行启用未定义行为检查。

生产请求资格参数为 16 帧、每帧最多 512 行。相同输入输出寄存器下，`frame_id` 到请求资格的最长路径由 6 级降至 3 级。完整资格电路仍为 6 级；nominal LUT 为 173，参考版本为 108；两者均为 224 个触发器，DSP 与 RAM 为零。整机路径由完整 SoC 映射测量。

## 重复执行

```bash
mkdir -p build/ps_frame_selection/reference
git archive 9d75f75a rtl/npu/ps_compact/ps_frame_store.sv rtl/common | tar -x -C build/ps_frame_selection/reference
python3 test/ps_request_ranges/run_formal.py --source-root . --reference-root build/ps_frame_selection/reference --out build/ps_frame_selection/formal
python3 test/ps_request_ranges/run_numeric.py --source-root . --reference 9d75f75a --jobs 1 --out build/ps_frame_selection/numeric
python3 test/ps_request_ranges/run_numeric.py --source-root . --reference 9d75f75a --jobs 1 --large --out build/ps_frame_selection/numeric_large
python3 scripts/fpga/open_fpga_synth.py --source-root build/ps_frame_selection/formal/current_source/512_16 --case-config test/ps_frame_selection/synthesis_cases.json --cases qualification --out build/ps_frame_selection/synthesis --max-register-path-cells 10
```

`validation.json` 记录参数、通过数量、源码及原始报告的 SHA256。生成的仿真与综合文件保存在指定输出目录。
