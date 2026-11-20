# 第20轮完整SoC综合、布局与功能验证

固定RTL源码提交为 `273496cf7a8598e796963f4102eab25da2c11f58`，顶层为 `soc_top`，器件为 `xc7a200tfbg484-3`。生产配置使用16×16阵列、8个向量PE、INT8/INT16/INT32、64位总线、4 KiB im2col缓存、7个8 KiB共享银行、16个部分和帧、原始INT32部分和及256 KiB CPU RAM。量化使用两个计算通道和512行整组缓存。

实际合法布局占用 **49,608个物理LUT位置**，满足50,000的面积要求。最长寄存器间组合路径为 **18级**。同一RTL版本通过86个NPU任务、216,348项INT32数值检查及全部容量检查。目标时钟周期为6.667 ns；布线后的150 MHz时序验证尚未完成。

## 资源与布局

| 资源 | 数量 |
| --- | ---: |
| 综合逻辑LUT原语 | 49,963 |
| RAM LUT位置 | 2,444 |
| SRL位置 | 24 |
| 布局前名义LUT总数 | 52,431 |
| 布局后的逻辑LUT位置 | 47,140 |
| 布局后的物理LUT位置合计 | 49,608 |
| FF | 42,860 |
| DSP48E1 | 740 |
| RAMB36E1 | 91 |
| RAMB18E1 | 45 |
| 综合CARRY4 | 1,851 |
| 布局后CARRY4 | 1,872 |
| 使用的Slice | 16,087 |

物理统计按实际BEL所在位置合并同一位置的5LUT与6LUT。58,522个LUT BEL实例使用49,608个物理位置，其中8,914个位置包含两个LUT输出。逻辑LUT、RAM LUT和SRL分别统计，三个类别互不重叠。独立统计重新检查106,179个单元，全部具有唯一BEL，未发现未放置单元或资源冲突。

实现采用种子1、两次HeAP分析布局和一次退火细化。布局耗时544.09秒，采样得到进程树内存峰值1,889,378,304字节。逐单元检查覆盖55,090个普通逻辑LUT的INIT、230,903个逻辑输入连接、55,090个输出网络，以及共享物理位置的输入一致性，全部通过。

工具版本、打包与布局程序摘要、配对阶段和完整资源结果见 [fpga_round20_placement.json](data/fpga_round20_placement.json)。

## 组合路径

分析分别按LUT每个输出的真值表建立依赖，并包含DSP内部寄存边界之间的组合运算。实际连接图的205,894个节点全部完成遍历，全部原语均已分类，没有组合环。

导出的200组不同路径包含1组18级、6组16级、35组15级、54组14级、79组13级和25组12级，其中7组超过15级。

| 起点与终点 | 级数 | 组数 |
| --- | ---: | ---: |
| IA请求坐标 → 读仲裁授予 | 18 | 1 |
| IA槽位 → 深度卷积在途计数 | 16 | 1 |
| 待处理卷积描述符 → 前端坐标与核索引 | 16 | 3 |
| 读响应错误 → IA缓存写数据 | 16 | 2 |

完整路径的每级原语、输入输出端口和寄存器来源保存在 [fpga_round20_measurement.json](data/fpga_round20_measurement.json)。

## 功能与容量

仿真启用 `XILINX_FPGA` 和 `SYNTHESIS`，使用官方LUT及DSP模型和生产配置。综合与仿真的共同源码逐项核对SHA-256。四类测试使用同一个仿真程序，86个任务的全部测量字段均与第19轮一致。

| 测试类别 | 任务数 | INT32检查数 | 任务执行周期 |
| --- | ---: | ---: | ---: |
| NPU功能 | 38 | 11,118 | 143,037 |
| 共享银行及部分和容量 | 21 | 173,642 | 663,521 |
| 输出模式 | 15 | 11,392 | 45,446 |
| 紧凑输入格式 | 12 | 20,196 | 109,869 |
| 合计 | 86 | 216,348 | 961,873 |

量化整组缓存处理742组、17,360行，最大组为512行，覆盖取消尚未产生数据的保留组。待处理配置累计保持163,340个周期，输入、发出和输出行数一致。

83项容量测试全部通过，通用RTL和FPGA配置的结构检查均通过。缓冲数组共994,508位，即124,313.5字节。生产结构包含256个阵列单元、8个向量PE、两个量化计算通道、57,344字节共享存储及49,152字节原始INT32部分和存储。512行量化队列每行513位，总计32,832字节，其中32,768字节为INT32数据。

完整结果见 [fpga_round20_npu.json](data/fpga_round20_npu.json) 和 [fpga_round20_capacity.json](data/fpga_round20_capacity.json)。

## 技术映射与重现

DSP预算为740，包含362个原有DSP及378个选中的算术单元。同一组合路径至多包含一个选中的组合DSP，并检查与原有未寄存DSP的组合依赖。实际选择对应100组位宽及符号参数，合计3,381个确定输入位，全部通过官方模型的全输入SAT证明，检查 `X`、`Y` 与所有 `CO` 位。ABC9网络等价检查通过。

综合与路径分析使用固定源码中的工具快照。布局程序递归检查相对位置组的连通性，并保留LUT原逻辑输入编号。原语级实现验证、完整SoC逻辑引脚检查以及运行方式见 [open_fpga_synthesis.md](open_fpga_synthesis.md)。

```sh
python3 scripts/fpga/open_fpga_synth.py \
  --source-root /path/to/round20_source \
  --cases soc_top --out build/soc_round20_pre --through pre_lut \
  --wide-alu-dsp-budget 740 --wide-alu-minimum-width 8 \
  --wide-alu-maximum-chain 1

python3 scripts/fpga/remap_fpga_luts.py \
  --source build/soc_round20_pre/soc_top \
  --out build/soc_round20_cost/soc_top \
  --mode physical-cost --delay-target-ps 6667 --wire-delay-ps 300 \
  --max-lut-inputs 8

python3 scripts/fpga/test_wide_alu_dsp.py \
  --selected-netlist build/soc_round20_pre/soc_top/pre_alu.json \
  --selection build/soc_round20_pre/soc_top/wide_alu_mapping.json \
  --top soc_top --out build/round20_selected_dsp_formal
```

映射网表SHA-256：`cbbc5b521250eac1b4c5ace25693a475d00714f3f6bf685cb69fd7e1fcf1eec4`。

已放置网表SHA-256：`aeeeac42600723aa1c1fc29cc09e8da09c0f6577b7c721da38727fd37ee9e2a3`。

仿真程序SHA-256：`0f9f2f4a7fc7c3c8637ed818bbc72ba8440245f8be30f4ffa48da1590c8a1d95`。

布局程序SHA-256：`10357cc430a78c45842554a01c0c6d0ec62d9cba3e656815aae0523560a035b3`。
