# 向量坐标范围

向量引擎对十六位图像尺寸执行坐标范围检查。低十六位加法与原坐标高十八位的零值、全一值条件并行计算，低位进位选择相应高位条件。该结构保留三十四位坐标的全部取值和回绕行为。

```sh
python3 test/vector_coordinate_bounds/run_formal.py --out build/vector_timing/coordinates
```

检查直接提取当前 RTL 的列坐标和行坐标有效条件，比较附件版本的完整三十四位算术表达式，覆盖全部坐标、膨胀系数和图像尺寸输入。完整向量状态、舍入、功能和综合结果见 [向量控制与分段算术](../vector_control_bounds/README.md)。
