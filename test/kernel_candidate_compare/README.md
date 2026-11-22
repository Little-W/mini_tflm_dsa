# 权重描述符比较

本文保存的资源与路径记录使用当次固定源码、RTL 算术属性选择和 740 个 DSP 的总预算，具体源码与配置见随文测量报告。文中的运行命令用于当前工作区，采用普通 RTL 自动映射并生成新的资源与路径报告。

`kernel_candidate_equal` 先独立比较每组三位输入，再通过六路归并树形成完整相等结果。FPGA 综合保留每个叶比较结果，使归并层只处理单比特相等条件。候选稳定性与已保存描述符元数据使用相同结构，比较语义、预取资格、完成排空和所有接口周期保持一致。

## 已完成检查

完整 `kernel_loader` 状态和输出证明覆盖 `SIZE/COUNT_WIDTH/BUS_WIDTH` 为 `16/29/64` 与 `3/33/32` 的两组参数，`DATA_WIDTH=16`，共 24,261 个比较位，全部外部输入未约束。公开四态测试直接提取两个实际源文件的比较器，在 `p_use_lut=0/1` 下检查九种宽度，包含完整匹配、不同数据和每个输入位的 X/Z。

生产权重加载器的独立测量结果如下。

| 指标 | 参考实现 | 当前实现 |
| --- | ---: | ---: |
| 逻辑 LUT | 3,443 | 3,407 |
| 寄存器 | 2,333 | 2,333 |
| DSP | 24 | 24 |
| RAMB36 | 64 | 64 |
| 寄存器间最长组合单元数 | 12 | 12 |

完整模块减少 36 个 LUT。相同寄存输入输出的小型比较器中，160 位比较为 117→81 LUT，99 位比较为 70→47 LUT，最长组合级数均为 5→4。完整模块剩余最长路径来自预取状态到控制器更新，整机预测字段经过比较器后的实际路径使用 SoC 报告检查。

## 重复执行

参考源代码来自提交 `b9773a15`。

```bash
mkdir -p build/kernel_candidate_compare_reference
git archive b9773a15 rtl/common rtl/npu/loaders | tar -x -C build/kernel_candidate_compare_reference
python3 test/kernel_candidate_compare/run_formal.py --source-root . --reference-root build/kernel_candidate_compare_reference --module kernel_loader --profiles 16:29:64 3:33:32 --fpga --out build/kernel_candidate_compare/formal
python3 test/kernel_candidate_compare/run_four_state.py --source-root . --reference-root build/kernel_candidate_compare_reference --out build/kernel_candidate_compare/four_state
python3 scripts/fpga/open_fpga_synth.py --source-root . --case-config test/kernel_candidate_compare/synthesis_cases.json --cases kernel --out build/kernel_candidate_compare/synthesis --max-register-path-cells 10
```

`validation.json` 保存源码散列、参数、通过数量及原报告散列。正式资料只包含源代码、测试脚本和文本报告。
