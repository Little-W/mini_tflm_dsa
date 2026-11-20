# 配置接收与帧地址就绪

`npu_top` 使用普通 RTL 检查配置接收条件。向量和矩阵执行状态、配置流水、操作数缓存、IA 预取以及权重加载状态共同决定 `sa_ready`。任务故障和中止状态阻止配置接收；`cfg_start_event` 同时要求 `calc_start`、`sa_ready` 和矩阵模式。

FPGA 分支以权重加载器的静止状态、后台请求和仲裁资格检查可接收条件。通用分支使用 `kernel_prefetch_idle`。检查分别覆盖各分支的全部输入，不对这两组输入附加相等假设。

`frame_address_prepare` 的 `p_ready_mask_abort` 默认为 1。设为 0 时，就绪输出表示内部状态为空闲；内部接受事件始终检查 `i_abort`。生产实例的帧命令接收条件包含任务故障和中止状态。实际调度器的空闲状态没有有效帧命令，因此配置接收不会同时接受帧命令。

## 形式检查

- 从当前实际源码提取配置接收逻辑，分别对 FPGA 和通用分支完成 19 个输入位、2 个输出位的全部取值 SAT 证明。
- 在完整 `ps_window_scheduler` 中增加只读观察输出，使用 ABC PDR 证明 `ready` 蕴含 `!command_valid`。参数覆盖阵列大小 1、4、16，帧数 1、3、16，以及有界和无界复用。所有外部输入保持任意取值，原有状态在观察到复位前保持任意值。另检查复位后的空闲状态可达。
- 使用当前完整 `frame_address_prepare` 比较就绪参数。6 组配置覆盖阵列大小 1、16、32，通用算术、官方 DSP48E1 功能模型及 `p_ready_mask_abort=0/1`。全部公开端口均连接，包括 `input wire logic` 声明的输入。内部状态、接受事件和中止屏蔽后的公开就绪逐周期相等。
- 从当前顶层提取帧命令接收和地址中止表达式，结合实际调度器已证明的空闲性质，证明帧命令接受事件保持一致。

报告保存于 [measurement.json](measurement.json)。源码与测试脚本的 SHA256 标识实际受测内容。收集器要求完整形式检查通过，并核对所收集的数值检查、兼容性检查和映射结果各自的源码摘要。

## 运行

```bash
export PYTHONDONTWRITEBYTECODE=1
ADMISSION_OUT=/tmp/npu_admission
python3 test/npu_admission/run_formal.py --out "$ADMISSION_OUT/verified_formal"
python3 test/npu_registered_fault/run_formal.py --out "$ADMISSION_OUT/registered_fault"
python3 test/npu_admission/collect_report.py \
  --build "$ADMISSION_OUT" --out "$ADMISSION_OUT/measurement.json"
```

形式检查和收集器支持 `--source-root`，可在固定的另一份源码上运行。默认使用测试脚本所在仓库。

地址数值检查分别运行默认和生产就绪参数，并比较通用实现与官方 DSP 模型。各计算阶段、结果等待阶段和空闲阶段均检查中止、复位、同时开始以及恢复后的行为：

```bash
python3 test/npu_admission/run_numeric.py \
  --out "$ADMISSION_OUT/frame_numeric" --verilator verilator --jobs 1
```

局部映射使用实际配置接收表达式及完整接收条件参考，在输入和输出处添加相同寄存器。原始条件中的全部状态输入仍保留在测量接口中，未使用的输入由综合工具处理：

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

局部映射用于检查这一段组合逻辑。整机资源和 150 MHz 时序由固定源码的实际 Vivado 报告确认。
