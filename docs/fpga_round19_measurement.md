# 第19轮完整SoC综合、布局与功能验证

固定RTL源码提交为 `524be9c3ca2029543e00c27a2d9b4eb667ee4b3c`，顶层为 `soc_top`，器件为 `xc7a200tfbg484-3`。完整设计使用16×16阵列、8个向量PE、INT8/INT16/INT32、64位总线、4 KiB im2col缓存、7个8 KiB共享银行、16个部分和帧、原始INT32部分和与256 KiB CPU RAM。量化部分使用两个计算通道和512行整组缓存。

实际合法布局占用 **49,354个物理LUT位置**，满足50,000的面积要求。最长寄存器间组合路径为 **19级**。同一RTL版本通过86个NPU任务、216,348项INT32数值检查及全部容量检查。目标时钟周期为6.667 ns；布线后的150 MHz时序验证尚未完成。

## 资源与布局

| 资源 | 数量 |
| --- | ---: |
| 综合逻辑LUT原语 | 49,721 |
| RAM LUT位置 | 2,444 |
| SRL位置 | 24 |
| 布局前名义LUT总数 | 52,189 |
| 布局后的逻辑LUT位置 | 46,886 |
| 布局后的物理LUT位置合计 | 49,354 |
| FF | 42,856 |
| DSP48E1 | 740 |
| RAMB36E1 | 91 |
| RAMB18E1 | 45 |
| CARRY4 | 1,855 |
| 使用的Slice | 15,688 |

物理统计按实际BEL所在位置合并同一位置的5LUT与6LUT。58,305个LUT BEL实例使用49,354个物理位置，其中8,951个位置包含两个LUT输出。逻辑LUT、RAM LUT和SRL分别统计，三个类别互不重叠。独立统计程序重新检查105,880个单元，全部具有唯一BEL，未发现未放置单元或资源冲突。

实现采用种子1、两次HeAP分析布局和一次退火细化。布局耗时543.18秒，采样得到进程树内存峰值1,933,598,720字节。工具完成全部放置及位置合法性检查。工具版本、器件数据库摘要、配对阶段和完整资源结果见 [fpga_round19_placement.json](data/fpga_round19_placement.json)。

## 组合路径

组合分析分别按LUT每个输出的真值表建立依赖，并包含DSP内部寄存边界之间的组合运算。实际连接图的205,579个节点全部完成遍历，全部原语均已分类，没有组合环。

导出的200组不同路径包含2组19级、5组18级、20组17级、23组16级、75组15级和75组14级。

| 起点与终点 | 级数 |
| --- | ---: |
| DMA上下文计数 → 向量输入保留及状态 | 19 |
| DMA上下文计数 → 控制器就绪及状态 | 18 |
| DMA上下文计数 → 帧地址、阶段及控制寄存器 | 17 |
| 预测器配置阶段 → 前端坐标及换行控制 | 16 |
| 前端剩余通道 → 分组范围 | 16 |
| 前端状态 → IA缓存写数据 | 16 |

最长路径经过读响应就绪、总线错误处理、DMA授予及任务启动条件。完整路径的每级原语、输入输出端口和寄存器来源保存在 [fpga_round19_measurement.json](data/fpga_round19_measurement.json)。

## 功能与容量

仿真启用 `XILINX_FPGA` 和 `SYNTHESIS`，使用官方LUT及DSP模型和生产配置。综合与仿真的共同源码逐项核对SHA-256。四类测试使用同一个仿真程序，86个任务的全部测量字段均与第18轮一致。

| 测试类别 | 任务数 | INT32检查数 | 任务执行周期 |
| --- | ---: | ---: | ---: |
| NPU功能 | 38 | 11,118 | 143,037 |
| 共享银行及部分和容量 | 21 | 173,642 | 663,521 |
| 输出模式 | 15 | 11,392 | 45,446 |
| 紧凑输入格式 | 12 | 20,196 | 109,869 |
| 合计 | 86 | 216,348 | 961,873 |

量化整组缓存处理742组、17,360行，最大组为512行，覆盖取消尚未产生数据的保留组。待处理配置累计保持163,340个周期，输入、发出和输出行数一致。

83项容量测试全部通过，通用RTL和FPGA配置的结构检查均通过。缓冲数组共994,508位，即124,313.5字节。生产结构包含256个阵列单元、8个向量PE、两个量化计算通道、57,344字节共享存储及49,152字节原始INT32部分和存储。512行量化队列每行513位，总计32,832字节，其中32,768字节为INT32数据。

完整结果见 [fpga_round19_npu.json](data/fpga_round19_npu.json) 和 [fpga_round19_capacity.json](data/fpga_round19_capacity.json)。

## 技术映射与重现

DSP预算为740，包含362个原有DSP及378个选中的算术单元。同一组合路径至多包含一个选中的组合DSP，并检查与原有未寄存DSP的组合依赖。实际选择对应100组位宽及符号参数，合计3,381个确定输入位，全部通过官方模型的全输入SAT证明，检查 `X`、`Y` 与所有 `CO` 位。ABC9的网络等价检查通过。

分析程序固定为提交 `9c764be6b39c277055ee9502a60ea350672cd2ed` 的工具快照，物理实现使用独立输出输入连接补丁。各工具、原语模型和阶段文件的SHA-256均记录在结果中。使用包含这些工具的工作目录，将 `--source-root` 指向上述固定RTL提交，可执行：

```sh
python3 scripts/fpga/open_fpga_synth.py \
  --source-root /path/to/round19_source \
  --cases soc_top --out build/soc_round19_pre --through pre_lut \
  --wide-alu-dsp-budget 740 --wide-alu-minimum-width 8 \
  --wide-alu-maximum-chain 1

python3 scripts/fpga/remap_fpga_luts.py \
  --source build/soc_round19_pre/soc_top \
  --out build/soc_round19_cost/soc_top \
  --mode physical-cost --delay-target-ps 6667 --wire-delay-ps 300 \
  --max-lut-inputs 8

python3 scripts/fpga/test_wide_alu_dsp.py \
  --selected-netlist build/soc_round19_pre/soc_top/pre_alu.json \
  --selection build/soc_round19_pre/soc_top/wide_alu_mapping.json \
  --top soc_top --out build/round19_selected_dsp_formal
```

映射网表SHA-256：`f99d5a5b5819ecba86909beab39d055c09d115408acf224d5856b1171196daef`。

已放置网表SHA-256：`86adfe42f4ebbf24ce7f74a939e27dc0ad7fda238916989cc35f4fd40587ad05`。

仿真程序SHA-256：`26365da34bea5bbf64b1ea044ce08863434143dc9c668d889773d70467c65297`。

物理实现程序SHA-256：`2837deefa50ea794858ac8bb3788916e29283bb2490ec6e1d3b0a10a8eca992c`。
