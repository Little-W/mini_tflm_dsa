# 计算核心验证

该测试验证脉动阵列、部分和缓存以及输出控制的协同工作。输入激活按对角线顺序送入阵列，测试平台检查部分和回放、最终输出向量与 `tile_calc_over` 的时序。

从仓库根目录运行固定输入测试：

```bash
make vcs-unit-compute_core
```

运行随机矩阵测试：

```bash
make vcs-random-compute COUNT=2 SEED=42
```

测试使用 `rtl/npu/` 中的实现，参考矩阵与输入文件由 `gen_mats.py` 生成。固定输入、随机数据和仿真结果分别保存在 `build/vcs/unit/compute_case/`、`build/vcs/unit/compute_random/` 和 `build/vcs/unit/compute_core/`。
