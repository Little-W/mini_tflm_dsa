# 配置接收与帧地址就绪

`npu_top` 使用并行状态分组检查配置接收条件，两个预取空闲信号直接进入最后一个 `LUT6_2`。同一原语输出 `sa_ready` 与 `cfg_start_event`，配置开始和向量模式参与后一个输出。通用RTL分支保留相同布尔表达式。

`frame_address_prepare` 的 `p_ready_mask_abort` 默认为1。设为0时，就绪输出表示内部状态为空闲；内部接受事件始终检查 `i_abort`。生产实例由 `frame_command_ready` 检查任务中止，配置接收使用调度器空闲条件。实际调度器的空闲状态没有有效帧命令，因此配置接收不会产生帧命令接受事件。

## 验证范围

- 实际配置接收表达式的通用与官方LUT模型分别完成15个输入位、2个输出位的全部取值SAT证明。
- 在完整 `ps_window_scheduler` 中添加只读观察输出，使用ABC PDR证明 `ready` 蕴含 `!command_valid`。覆盖阵列大小1、4、16，帧数1、3、16及有界和无界复用参数；原有状态在观察到复位前保持任意取值。另检查实际复位后空闲状态可达。
- 六组帧地址参数完成5,903位状态与输出等价检查，覆盖通用算术、官方DSP模型、默认就绪以及内部空闲就绪。中止、结果等待和所有地址输入均不受约束。
- 提取实际上层接收表达式，结合已证明的调度器性质，证明帧命令接受事件相同。
- 数值检查分别运行生产参数 `p_ready_mask_abort=0` 和默认值 `1`，每组同时比较通用实现与官方DSP模型。每组通过36,746次地址计算、4,286次中止、1,512次复位和185,328次结果等待检查，共运行672,662个周期，结果延迟保持10个周期。
- 每组在十个计算阶段及结果等待阶段分别施加中止和复位，并在同周期令 `start=1`。另检查空闲状态下的中止与开始同时有效，逐周期核对两种参数各自的就绪输出、中止后的恢复及结果有效信号。
- 共享银行配置提取器支持独立声明的 `cfg_start_event`；14组银行参数的完整状态比较通过。

## 局部映射

输入和输出均加寄存器，使用实际配置接收表达式进行映射。逻辑LUT从5个减少至4个，17个测量寄存器保持不变；最长组合路径为2级。预取空闲信号到输出为1级。整个SoC的组合级数由固定源码的整机映射另行测量。

全部结果、源码及映射文件SHA256见 [measurement.json](measurement.json)。

## 受测源码

`validation_scope.rtl_revision` 标识受测RTL提交，`source_sha256` 保存完整文件哈希。报告汇总逐项核对形式证明、数值测试及共享银行验证记录的全部源码和测试文件，包括调度器及其辅助模块。

`npu_top` 的测试范围包括配置接收表达式、帧命令接受与地址中止表达式，以及共享银行配置寄存器。配置接收证明把 `ia_prefetch_idle`、`kernel_prefetch_idle` 作为独立输入，偏置请求的内部实现不参与该提取模块。与整机固定提交 `524be9c3` 比较，配置接收提取内容、帧控制表达式、地址模块及调度器保持一致。报告同时记录配置接收提取内容的SHA256，便于与其他提交比较；整机面积与时序由固定整机源码另行测量。

## 重现

```sh
python3 test/npu_admission/run_formal.py --out build/admission/verified_formal
python3 test/npu_admission/run_numeric.py \
  --out build/admission/frame_numeric --verilator verilator-modern --jobs 2
python3 test/ps_allocation_registration/run_formal.py \
  --out build/admission/allocation_formal
python3 test/npu_admission/prepare_measurement.py --out build/admission/mapping
python3 scripts/fpga/open_fpga_synth.py \
  --case-config build/admission/mapping/cases.json \
  --cases admission_reference admission_current --out build/admission/mapping/results
python3 test/npu_admission/collect_report.py \
  --build build/admission --out test/npu_admission/measurement.json
```
