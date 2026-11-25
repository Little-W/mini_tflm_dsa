# 输出行索引计算

`oa_writer` 在已有准备周期计算下一行索引。`COUNT_WIDTH` 大于 16 时，低 16 位计算结果和进位，高位分别计算进位为零和一时的结果，最后使用低段进位选择高段结果。较短计数器保留普通定宽加法。

实现复用 `parallel_prefix_add` 的进位选择结构。全部结果位参与计算，计数器宽度、寄存器数量、状态转换和公开接口保持一致。RTL 使用普通加法表达式，由综合工具选择硬件资源。

## 验证

完整控制器的形式验证比较全部公开输出和所有同名状态寄存器，输入配置和握手信号均不加数值约束。验证使用 `SYNTHESIS` 与 `XILINX_FPGA` 定义，并覆盖 4、8、16、32 个通道，以及 4、7、8、9、16、29、32 位计数器。

```bash
python test/oa_writer_row_count/run_formal.py --out build/oa_writer_row_count_formal
python test/oa_writer_geometry/run_four_state.py \
  --reference a2c61b53 --out build/oa_writer_row_count_four_state \
  --profiles 4:32:4 8:64:8 16:64:16 16:64:29 16:64:32 --scenarios 1024
```

四态仿真比较 21 个公开输出，覆盖未知配置位、配置重载、复位、读写暂停和完成事件。仿真分支保留普通算术的四态传播行为；综合分支通过完整控制器的时序等价证明。

综合测量使用 16 个通道、64 位总线、32 位地址和 29 位计数器。测量保留完整接口，并记录寄存器之间的实际组合单元路径。结果及源文件校验值见 `validation.json`。
