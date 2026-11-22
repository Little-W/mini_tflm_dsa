# 配置接收资格与帧地址就绪

`npu_top` 用 `task_accept_conditions` 表示组合接收资格。该表达式检查向量执行状态、计算控制器、帧调度器、配置流水、操作数缓存、IA 与权重预取、卷积空闲状态以及当前故障和中止状态。`task_accept_ready` 在时钟边沿保存资格；任务接收或中止期间清除该寄存器。公开 `sa_ready` 由已保存的资格和当前故障、中止状态共同决定。

本目录的组合检查直接提取 `task_accept_conditions`，并使用 `accept_conditions` 作为测试输出名称。第二个测试输出 `matrix_start_candidate` 为 `calc_start && accept_conditions && !cfg_vector_enable`。生产 `cfg_start_event` 使用公开 `sa_ready`；本目录的组合结果不包含 `task_accept_ready` 的时序行为。

`frame_address_prepare` 的 `p_ready_mask_abort=1` 在公开就绪输出上屏蔽中止；参数为 0 时，公开就绪输出表示内部空闲状态。两种配置的内部接受事件都检查 `i_abort`。地址数据按三十二位模运算计算，准备完成后保持结果至接收。

## 检查范围

`run_formal.py --admission-only` 对实际组合表达式和独立条件描述执行 SAT 比较，覆盖 20 个任意输入位和 2 个输出位。所有输入均不附加约束。报告将检查范围记录为 `admission_only`。

`run_formal.py` 的完整局部检查还包含以下内容：

- 读取完整 `ps_window_scheduler` 及独立的 `ps_scheduler_any`、`ps_scheduler_priority`，使用 ABC PDR 检查复位后的 `ready` 蕴含 `!command_valid`。四组参数覆盖阵列大小 1、4、16，帧数 1、3、16，以及有界和无界复用；另检查复位后的空闲状态可达。
- 使用完整普通 RTL 比较 `frame_address_prepare` 的就绪参数。六组参数覆盖阵列大小 1、16、32，`p_pipeline_products=0/1` 和 `p_ready_mask_abort=0/1`。所有公开端口均连接，比较内部状态、结果数据和经过相同中止屏蔽的就绪输出。

[measurement.json](measurement.json) 记录实际已执行的检查、对应源码 SHA256 和检查范围。收集器支持组合检查报告；指定 `--require-complete` 时，还要求调度器和地址模块的完整局部形式检查均已通过。数值检查和映射结果只有在文件存在且摘要核对成功时才会加入报告。

## 运行

轻量组合检查：

```bash
export PYTHONDONTWRITEBYTECODE=1
ADMISSION_OUT=/tmp/npu_admission
python3 test/npu_admission/run_formal.py \
  --admission-only --out "$ADMISSION_OUT/verified_formal"
python3 test/npu_admission/collect_report.py \
  --build "$ADMISSION_OUT" --out "$ADMISSION_OUT/measurement.json"
```

完整局部形式检查：

```bash
python3 test/npu_admission/run_formal.py --out "$ADMISSION_OUT/verified_formal"
python3 test/npu_admission/collect_report.py --require-complete \
  --build "$ADMISSION_OUT" --out "$ADMISSION_OUT/measurement.json"
```

形式检查、映射输入生成和收集器支持 `--source-root`，可读取固定的另一份 RTL 源码；默认使用测试脚本所在仓库。

地址数值检查为两种就绪参数分别运行一个普通 RTL 实例，与独立的三十二位地址模型比较。各计算阶段、结果等待阶段和空闲阶段均检查中止、复位、同时开始以及恢复后的行为。默认 `p_pipeline_products=1` 时结果准备延迟为 11 拍；指定 `--pipeline-products 0` 时为 10 拍。

```bash
python3 test/npu_admission/run_numeric.py \
  --out "$ADMISSION_OUT/frame_numeric" --verilator verilator --jobs 1
```

## 局部映射

测量模块在组合资格的输入与输出处添加寄存器，用于统计这一段逻辑的面积和深度。该模块不包含生产 `task_accept_ready` 的清除和更新控制。路径报告分别保留 `kernel_prefetch_idle`、`conv_task_idle` 和 `task_fault` 到测量输出的路径。

```bash
python3 test/npu_admission/prepare_measurement.py --out "$ADMISSION_OUT/mapping"
python3 scripts/fpga/open_fpga_synth.py \
  --case-config "$ADMISSION_OUT/mapping/cases.json" \
  --cases admission_reference admission_current \
  --through pre_lut --out "$ADMISSION_OUT/mapping/pre"
for version in admission_reference admission_current; do
  python3 scripts/fpga/remap_fpga_luts.py \
    --source "$ADMISSION_OUT/mapping/pre/$version" \
    --out "$ADMISSION_OUT/mapping/results/$version" \
    --mode physical-cost --small-lut-area-cost 1 --max-lut-inputs 6 \
    --wire-delay-ps 500 --delay-target-ps 6667
done
python3 test/npu_admission/collect_report.py \
  --build "$ADMISSION_OUT" --out "$ADMISSION_OUT/measurement.json"
```

只生成映射源码时，报告记录 `executed=false`。整机资源和 150 MHz 时序使用完整设计的实际综合与时序报告确认。
