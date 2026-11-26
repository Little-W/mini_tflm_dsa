# 上传环境的 68 项性能比较

本入口将冻结源码与上传环境中实际重新编译的 `449e3fe4` 结果逐项比较。三组任务包括 36 项共同算子、26 项补充算子和 6 项读地址最小接收间隔为两个周期的任务。

## 运行要求

先用上传环境中的 `scripts/run_npu_performance.py` 实际编译并完成全部 68 项原版本任务。原版本结果必须标记为 `fresh_build_and_rtl_simulation`，并通过固定周期、输出校验值、源码和压缩文件检查。

当前源码必须为指定完整提交的干净目录。入口逐文件核对 Git 对象，编译前后再次核对源文件。每个集合开始时都核对编译输入和实际硬件参数，三个集合共用本次实际编译的仿真程序。

```bash
PYTHONHOME="$EXPERIMENT/tools/python" \
PYTHONPATH="$EXPERIMENT/tools/python/lib/python3.12/site-packages" \
PYTHONDONTWRITEBYTECODE=1 \
VERILATOR_ROOT="$EXPERIMENT/tools/verilator" \
PATH="$EXPERIMENT/tools/python/bin:$EXPERIMENT/tools/verilator/bin:$PATH" \
"$EXPERIMENT/tools/python/bin/python3" test/uploaded_performance/run.py \
  --environment "$EXPERIMENT" \
  --reference "$REFERENCE_RESULTS" \
  --repo "$FROZEN_SOURCE" \
  --commit "$FROZEN_COMMIT" \
  --out "$CURRENT_RESULTS"
```

两次实验使用相同的工具、输入、外部内存服务和资源参数：9 个 4 KiB 共享存储块、64 KiB 卷积缓存、16 个向量计算单元、16 路量化与窗口通道、16×16 矩阵阵列和 64 位 AXI。生产实例中的描述符寄存、行地址寄存、请求寄存和响应缓冲容量逐项读取并记录。

## 检查内容

每项任务检查全部 524,288 个系统内存字，实际输出与输入预期张量、完整预期内存和原版本实际输出逐字节比较。运行断言及 `SYNTHESIS`、`XILINX_FPGA` 条件保持启用。检查内容还包括外存响应全部结束、首个读取响应至少八个周期、读写方向分别至多四个未完成事务，以及每项任务指定的读地址最小接收间隔。

`cases.csv` 保存全部周期数、绝对差和变化百分比。`field_comparison.csv` 保存 DMA 字节数、请求数、读写节拍数、等待统计、利用率、前端状态时间和所有事件时间的逐字段比较。任何正的数值差均单独列出；新增和缺少的统计字段分别保存。程序完成全部数值检查后，以逐项周期是否增加决定性能返回状态，周期增加的容差为零。

`validation.json` 分别记录数值检查结果与 `all_case_cycles_not_increased`。`execution.json` 中的 `performance_passed` 给出性能比较结果。源码、工具、编译输入、仿真程序和压缩文件均保存 SHA-256。

比较函数检查可单独运行：

```bash
python test/uploaded_performance/test_compare.py
```

## 独立核对保存结果

`audit.py` 再次核对冻结源码与 Git 对象、实际编译输入、仿真程序和压缩记录。它从压缩记录中读取全部任务的内存图像摘要、配置、输出及运行日志，并重新计算 68 项周期差。性能状态与数值状态分别保存。

```bash
python test/uploaded_performance/audit.py \
  --source-root "$FROZEN_SOURCE" \
  --current "$CURRENT_RESULTS" \
  --reference "$REFERENCE_RESULTS" \
  --out "$CURRENT_RESULTS/audit.json"
```

`scripts/fpga/summarize_soc_checkpoint.py` 的 `--uploaded-performance` 和 `--uploaded-reference` 参数调用同一检查，提交记录同时保存生产配置资源、组合路径、数值回归和上传环境性能结果。
