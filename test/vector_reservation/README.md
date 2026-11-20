# 向量输入槽位的并行更新

四个输入槽位分别生成请求选择和返回完成条件，综合时保留各槽位的前置译码节点。请求选择直接检查该槽位的编号与就绪状态；已有占用位与新请求通过逻辑或合并。返回完成优先清除对应槽位，任务启动、通道分组初始化和错误恢复同时清除四个槽位。公开请求信号和所有寄存器更新周期保持相同。

## 验证与测量

```sh
python3 test/vector_acc_read/run.py --reference-rev 2f06471c --bus-width 64 --out build/vector_reservation/full_state
python3 scripts/fpga/open_fpga_synth.py --cases vector_engine --out build/vector_reservation/synthesis
python3 test/vector_reservation/measure_boundary.py \
  --netlist build/vector_reservation/synthesis/vector_engine/mapped.json \
  --pre-lut build/vector_reservation/synthesis/vector_engine/pre_lut.il \
  --out build/vector_reservation/boundary.json
```

完整状态比较直接对附件版本执行，覆盖 13,446 位寄存状态、共享标量乘法器的操作数和 35 个公开输出。控制条件由实际控制状态归纳检查；全部状态和公开输出比较通过。

在坐标、分段算术和 DMA 地址共享组合上进行同配置比较：

| 项目 | 并行更新前 | 按槽位并行更新 | 保留前置译码节点 |
| --- | ---: | ---: | ---: |
| 逻辑 LUT | 11,805 | 11,738 | 11,629 |
| 分布式 RAM LUT | 248 | 248 | 248 |
| 触发器 | 5,976 | 5,976 | 5,976 |
| DSP48E1 | 16 | 16 | 16 |
| 最长寄存器间组合单元数 | 15 | 14 | 15 |
| `win_req_ready` 至 `input_reserved` 组合单元数 | 2 | 2 | 1 |

配置为 `TILE=16、PE_COUNT=8、BUS_WIDTH=64`。输入端口路径测量以现有端口为起点，终点为综合网表中真实占用寄存器的数据与控制引脚。`measurement.json` 保存按槽位并行更新的检查结果，`keep_measurement.json` 保存保留前置译码节点后的完整状态证明、资源和连通路径。后者只增加综合属性，全部 RTL 运算与状态表达式保持相同；当前就绪输入至四个占用寄存器分别经过一个 LUT。
