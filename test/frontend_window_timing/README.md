# 窗口候选坐标选择验证

`conv_im2col_frontend` 根据描述符选择当前空间位置、相邻空间位置及前后卷积核位置。`check.py` 从参考版本与当前实际源码提取窗口候选选择区域，逐位比较 338 位结果，包括坐标、地址、核位置、填充标志及快速接收条件。

四组相邻核位置使用 33 位加法比较，空间分块起点使用 32 位模加比较。坐标保持完整 35 位有符号范围。SAT 检查覆盖 `SIZE=4/16/64` 和 `CACHE_POLICY=0/3`，包含空间起点相加发生 32 位溢出的情况。保存的核方向资格在证明中按寄存器的定义构造，事务测试在其有效周期检查对应关系。

```sh
python test/frontend_window_timing/check.py --out build/frontend_window_timing/proof
```

默认寄存请求配置将坐标操作数、填充候选、字命中候选及选择条件保存在描述符准备寄存器中。准备寄存器两侧的算术与选择由 `test/frontend_depth_timing/prepared_check.py` 检查；完整前端的请求时序、数值、资源和执行周期见 [图像前端的寄存分段与组合深度验证](../frontend_depth_timing/README.md)。

## 完整 SoC 路径分析

`paths.py` 读取完整 SoC 网表，检查描述符队列和图像前端的实际连接，并分别固定 q0 描述符 RAM 到 `demand_word_matches_q/D`、`work_word_matches_q/D` 的终点。`--reference-report` 接收同一脚本生成的参考版本结果，`--summary-out` 保存两版本的起点、终点及组合单元数。

```sh
python test/frontend_window_timing/paths.py \
  --top soc_top --mapped build/soc_depth14/soc_top/mapped.json \
  --pre-lut build/soc_depth14/soc_top/pre_lut.il \
  --out build/soc_depth14/frontend_paths.json
```

`--scope window-decode` 用于单独提取的窗口候选选择模块。完整 SoC 测量应使用默认分析范围，并检查固定终点以及整个前端范围，避免仅依赖全局最长路径列表。

结构组合单元数反映映射网表中的逻辑串接。150 MHz 的时序结果需要目标器件的布局布线报告。
