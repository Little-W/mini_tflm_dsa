# 权重加载器列尾比较归并

`kernel_loader_ctrl` 使用已保存的完整列位置判断列尾。相邻位对的加一关系先分别计算，每五项比较结果形成一组，再合并分组结果。计数器位宽、更新边沿、描述符内容和装载请求时序保持不变。

直接比较覆盖 1、2、3、5、16、29、32、47、64 位，逐种参数执行任意输入形式证明和 8,196 次四态检查。完整控制器另在四组参数与两种编译模式下比较全部公开输出和共有状态。

```bash
python test/kernel_column_reduce/run.py --out build/kernel_column_reduce/arithmetic
python test/kernel_completion/run.py \
  --reference 9e3e5d6a6f47befe6c86aceacad7999923206458 \
  --out build/kernel_column_reduce/control
python test/kernel_port_selection/measure.py \
  --reference 9e3e5d6a6f47befe6c86aceacad7999923206458 \
  --out build/kernel_column_reduce/measurement
```

在 `SIZE=16`、`COUNT_WIDTH=29`、`BUS_WIDTH=64` 的完整加载器测量中，逻辑 LUT 数量保持 2,932，列位置寄存器到描述符比较寄存器的组合路径由 9 级变为 8 级，完整加载器最长寄存器路径为 10 级。
