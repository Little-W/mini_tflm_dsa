# 矩阵帧完成选择

矩阵引擎先计算当前帧的启动、计算结束及输出结束条件。`npu_frame_complete_select` 在末级合并已保存的部分和完成状态和本周期完成通知，输出当前任务的完成条件。模块采用普通可综合组合表达式，输入寄存器和结果寄存器的更新周期保持不变。

`run.py` 直接提取生产矩阵引擎中的表达式和实例连接，与固定远端版本比较。任意二值输入形式证明覆盖全部控制输入，四态仿真枚举十一位控制的 4,194,304 种组合。

```bash
python test/matrix_frame_complete/run.py --out build/matrix_frame_complete/validation
python test/matrix_frame_complete/measure.py \
  --validated-inputs build/matrix_frame_complete/validation \
  --out build/matrix_frame_complete/measurement
```

在相同的 Xilinx 7 系列映射设置下，部分和完成状态到结果寄存器的组合路径由 2 级变为 1 级，完整完成表达式使用 3 个逻辑 LUT。具体器件的 150 MHz 时序使用整机实现报告确认。
