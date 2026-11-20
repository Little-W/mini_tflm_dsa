# 偏置控制判断与DMA故障后的配置接收

参考提交为 `b20921b3b1fc3351b1f6447dd688af12ac60ef19`。修改范围为 `npu_top.sv` 与 `axi_block_dma_arbiter.sv`，保持全部状态寄存器、公开输出、同周期事件优先级和接口周期。

## 当前实现

控制器仅使用偏置地址是否为零这一条件。顶层通过已有 `add_equal` 并行判断偏置基址与通道偏移的模加结果，将零或非零指示送入控制器；偏置加载器仍接收完整32位地址。比较宽度为 `min(REG_WIDTH,32)`，与32位执行地址进入控制器端口时的截断或扩展一致。帧模式中原有的基址非零条件仍检查完整 `REG_WIDTH`，全部模式、帧初始及帧结束条件保持一致。

仲裁器提前计算写响应资格和读写完成错误。读就绪、读有效、读错误码、写就绪、写响应资格以及完成错误进入末级六输入LUT。RREADY和BREADY直接参与最终错误判断。

配置接收分别产生系统就绪及配置开始事件。`calc_start` 和 `cfg_vector_enable` 直接进入配置开始的末级LUT，适用于上层由系统就绪形成开始请求的连接。通用分支保留相同布尔关系。

## 形式与数值验证

| 检查 | 范围与结果 |
| --- | --- |
| 偏置地址及零判断 | `REG_WIDTH=1、2、8、16、31、32、33、64`，通用与FPGA共16组全输入SAT；同时比较完整32位DMA地址和控制器可见的零关系。 |
| 完整控制器 | 7组位宽、阵列及总线配置；观察全部公开输出及全部24位状态，包括配置错误状态；未限制输入取值、配置、控制状态或复位顺序。 |
| 配置接收与总线错误 | 通用和官方FPGA原语各完成全输入SAT。数值检查穷举32,768种配置接收输入及4,096种总线错误输入。 |
| 完整仲裁器 | BUS32、BUS64、BUS128分别开关量化客户端，加ASIC配置，共7组、13,179个等价位；全部297位状态与全部DMA实例端口均参与比较。 |
| 控制器逐周期检查 | REG_WIDTH为16、32、64时各运行20,000周期，比较40,000次全部公开输出及24位状态；每组覆盖7个实际状态、178次IA触发、657次开始接收和40次复位。 |
| 完整FPGA DMA | BUS32与BUS64各21个场景、905次检查，覆盖15次描述符取消、5次同时释放、5次授予撤销和8次四个上下文占满；最小连续命令接收间隔为2周期。 |

控制器数值测试包含低位地址回绕、32位加法溢出，以及64位配置中只有高32位非零的情况。原控制器源码保持一致，测试副本只增加状态观察输出。仲裁器比较将DMA响应作为任意输入，同时比较所有发送至DMA的端口；组合中间线按各自实现解释。

## 实际连接映射

两组测量均使用相同 `physical-cost` LUT库，目标延迟6667 ps、连线延迟300 ps、最大八输入LUT，并通过ABC9等价检查。输入及输出两侧添加测量寄存器，资源统计包含这些寄存器；生产RTL未增加状态。

### 完整控制器与偏置地址

保留实际控制器、实际执行地址和顶层偏置判断，参数为REG_WIDTH=32、SIZE=16、BUS64。完整地址作为独立观察输出保留。

| 项目 | 参考版本 | 当前实现 |
| --- | ---: | ---: |
| 逻辑LUT | 202 | 232 |
| FF | 500 | 500 |
| 偏置基址 → IA发送触发 | 16级 | 9级 |
| 偏置基址 → 控制器状态 | 17级 | 10级 |
| 通道索引 → IA发送触发 | 16级 | 6级 |
| 通道索引 → 控制器状态 | 17级 | 7级 |
| 完整偏置地址输出 | 10级 | 10级 |
| 此测量范围全部寄存器间最长路径 | 17级 | 10级 |

### 写保护、返回缓冲与配置接收

保留实际写页保护器、SoC的R/B返回缓冲、五类读取授予、顶层故障判断、`kernel_request_idle`、AXI-Lite顶层开始表达式及NPU配置接收表达式。读就绪、未完成命令状态、完成条件及其它模块空闲状态作为测量输入。数据宽度为64位，地址宽度为32位，最多四个未完成写事务。

| 项目 | 参考版本 | 当前实现 |
| --- | ---: | ---: |
| 逻辑LUT | 206 | 208 |
| FF | 381 | 381 |
| 写保护状态 → 总线错误 | 4级 | 3级 |
| 写保护状态 → 任务中止 | 5级 | 4级 |
| 写保护状态 → 五类读取授予 | 6级 | 5级 |
| 写保护状态 → 权重预取空闲 | 7级 | 6级 |
| 写保护状态 → 系统就绪 | 8级 | 7级 |
| 写保护状态 → 配置开始 | 10级 | 9级 |
| RREADY → 总线错误 | 1级 | 1级 |
| 读写完成或错误 → 总线错误 | 2级 | 2级 |
| `abort_pending` → 读取授予 | 2级 | 2级 |

R/B缓冲状态、读就绪、读写完成与错误、已登记命令状态和中止状态至各观察输出的路径均未增加级数。该范围内写保护器地址寄存器到自身的18级算术路径保持一致；本测量没有使用整机740个DSP的算术分配。所有映射单元完成分类，完整连接图没有组合环。

资源数字对应上述独立范围。完整SoC的物理LUT位置与最长组合路径使用整合后的固定源码另行检查；150 MHz需完整厂商布局布线后的STA确认。

## 重现

```sh
source /workspace/scratch/92f7be750f11/toolchain/env.sh
python3 test/npu_admission_r22/run_formal.py --out build/npu_admission_r22/formal_complete
python3 test/npu_admission_r22/run_numeric.py --formal build/npu_admission_r22/formal_complete --out build/npu_admission_r22/controller_numeric
python3 test/dma_read_permission/run_numeric.py --verilator verilator-modern --out build/npu_admission_r22/dma_numeric
python3 test/npu_admission_r22/prepare_measurement.py --out build/npu_admission_r22/mapping_inputs --formal build/npu_admission_r22/formal_complete
python3 scripts/fpga/open_fpga_synth.py --case-config build/npu_admission_r22/mapping_inputs/cases.json --cases bias_reference bias_current return_reference return_current --out build/npu_admission_r22/pre --through pre_lut --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
for case in bias_reference bias_current return_reference return_current; do
    python3 scripts/fpga/remap_fpga_luts.py --source build/npu_admission_r22/pre/$case --out build/npu_admission_r22/cost/$case --mode physical-cost --delay-target-ps 6667 --wire-delay-ps 300 --max-lut-inputs 8 --lock-file /tmp/mini_tflm_dsa_76fc8a977a8f_small_synthesis.lock
done
python3 test/npu_admission_r22/measure_paths.py --mapped build/npu_admission_r22/cost --pre build/npu_admission_r22/pre --out build/npu_admission_r22/path_summary.json
python3 test/npu_admission_r22/collect_report.py
```

`collect_report.py` 核对实际源码、隔离参考、生成的输入、映射文件和验证摘要后生成 [measurement.json](measurement.json)。
