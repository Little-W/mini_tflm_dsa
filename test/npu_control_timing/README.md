# NPU 配置与运行控制

## 当前设计

配置提交时保存 INT8 与 INT16 输出所需的有效预留数量。预留值限制到对应 FIFO 的实际银行数量，运行期只保留表示有效数量所需的位宽；零值继续使用 FIFO 的默认一个银行预留行为。

操作数缓存的清除事件在配置提交后保存一个周期。IA 和权重加载器使用同一清除事件，控制器在清除完成后发出加载初始化。容量准备、计算调度和加载器内部状态分别经过寄存器。

偏置组的当前位置、候选下一组及末组范围并行比较，完整保留地址模加、执行行数高位和尾组有效行数。容量计算使用普通定宽加减法和推断算术资源，配置提交之前保存各阶段结果。

任务中止由 `abort_pending` 驱动内部模块；DMA 在本地观察到总线错误时立即阻止接收新命令，已经接收的事务继续完成响应处理。公开错误、就绪和完成输出使用任务故障状态，后续任务由正常初始化流程开始。

## 已完成检查

- 13 组预留参数的无界归纳证明，覆盖 4 至 64 位配置字段、1 至 512 个银行、全部占用计数和部分写入编码。
- 4 组实际控制器的清除顺序证明，检查清除事件、加载初始化、输入发送和权重提交的相互关系。
- 偏置组步进和行数范围的全部输入组合证明；四态检查覆盖未知配置位。
- 8 组容量配置流水的无界归纳证明，以及 3 组各 20,000 周期的四态配置测试。
- 固定整合源码通过 38 项 NPU 测试和 11,118 次独立数值比较。
- CPU 运行同一真实固件的两种模式，每种比较 6,272 个输出，数值差异和保护区错误均为零。

`validation.json` 记录实际源码、参考源码、证明结果及整合测试摘要。参数与全部命令保存在对应测试记录中。

## 复现入口

```bash
python test/output_reservation/run.py --reference 415a70a --out build/output_reservation
python test/operand_flush_stage/run_formal.py --out build/operand_flush_stage
python test/is_bias_group_depth/run_step_formal.py --reference 415a70a --out build/bias_step
python test/is_bias_group_depth/run_formal.py --reference 415a70a --out build/bias_bounds
python test/is_bias_group_depth/check_four_state.py --reference 415a70a --out build/bias_four_state
python test/ps_capacity_limits/run_pipeline_formal.py --reference 415a70a --out build/capacity_pipeline
python test/ps_capacity_limits/run_pipeline_four_state.py --reference 415a70a --out build/capacity_four_state
python test/fpga_integration/run.py --source-root . --out build/npu_integration --jobs 1
```
