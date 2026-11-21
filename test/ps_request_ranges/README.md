# PS 帧请求范围检查

`ps_frame_store` 将请求的行数范围与目录状态分别计算。高于实际行数宽度的位独立检查为零，低位比较有效行数、配置步长与帧长度，最终请求资格只合并各项结果。包含未知位的行数使用完整关系表达式，保留四态传播。帧接收、压力通知、容量错误、数据写入与回放的周期保持一致。

## 已完成检查

组合证明直接提取参考实现和当前实现中的 `request_valid` 表达式。除该表达式及其组合中间信号外，两个完整源文件逐字一致。五组 `MAX_FRAME_ROWS/FRAME_COUNT` 参数为 `1/1`、`3/3`、`47/16`、`512/16` 和 `1024/32`，每组证明全部二值输入；四态测试合计执行 249,994 次比较，覆盖每个输入位的 X/Z、非法帧索引、零行数、上下界和未初始化目录值。

完整存储器功能检查比较每个周期的公开输出，使用独立内存模型检查结果。常规多帧测试与 256 行容量测试合计完成 833 条命令、120,368 个 INT32 数值和 22,491 个周期。

生产参数 `MAX_FRAME_ROWS=512, FRAME_COUNT=16` 的请求资格电路使用相同输入输出寄存器测量，逻辑 LUT 从 124 减少到 108，寄存器保持 224 个，DSP 和 RAM 均为零。该电路最长寄存器间组合路径仍为 6 级；行数高位的最长路径从 5 级减至 4 级。完整 SoC 的实际级数由整机映射报告确定。

## 重复执行

参考源代码来自提交 `108e8185`。

```bash
mkdir -p build/ps_request_ranges_reference
git archive 108e8185 rtl/npu/ps_compact/ps_frame_store.sv rtl/common | tar -x -C build/ps_request_ranges_reference
python3 test/ps_request_ranges/run_formal.py --source-root . --reference-root build/ps_request_ranges_reference --out build/ps_request_ranges/formal
python3 test/ps_request_ranges/run_numeric.py --source-root . --reference 108e8185 --jobs 1 --out build/ps_request_ranges/numeric
python3 test/ps_request_ranges/run_numeric.py --source-root . --reference 108e8185 --jobs 1 --large --out build/ps_request_ranges/numeric_large
python3 scripts/fpga/open_fpga_synth.py --source-root build/ps_request_ranges/formal/current_source/512_16 --case-config test/ps_request_ranges/synthesis_cases.json --cases qualification --out build/ps_request_ranges/synthesis --wide-alu-dsp-budget 740 --rtl-dsp-attributes --max-register-path-cells 10
```

`validation.json` 保存参数、检查数量、源文件散列和原报告散列。仿真可执行文件及综合中间文件保存在测试输出目录。
