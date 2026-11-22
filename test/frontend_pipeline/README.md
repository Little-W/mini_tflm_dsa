# im2col 前端验证

前端由公开接口与主状态机、配置几何计算、描述符准备、数据流和预取五个模块组成。共享状态类型位于 `conv_im2col_frontend_pkg.sv`。模块职责、流水数组及定宽算术见 [前端设计说明](../../docs/im2col_frontend.md)。

## 完整数值与握手

在仓库根目录执行：

```bash
python3 test/frontend_pipeline/run_numeric.py \
  --target asic --size 16 --lanes 8 --bus-width 64 \
  --cache-sets 16 --cache-ways 2 --line-bytes 128 \
  --narrow-mode 2 --windowed --prefetch \
  --out build/frontend_pipeline/numeric8

python3 test/frontend_pipeline/run_numeric.py \
  --target asic --size 16 --lanes 16 --bus-width 64 \
  --cache-sets 16 --cache-ways 2 --line-bytes 128 \
  --narrow-mode 2 --windowed --prefetch \
  --out build/frontend_pipeline/numeric16

python3 test/frontend_pipeline/run_numeric.py \
  --target fpga --register-descriptor 0 --size 4 --lanes 2 --bus-width 32 \
  --cache-sets 4 --cache-ways 2 --line-bytes 16 --narrow-mode 2 --prefetch \
  --out build/frontend_pipeline/numeric_direct4
```

每种配置生成 42 项任务，并用直接卷积方程生成期望矩阵。输入和响应持续施加随机等待，输出随机暂停接收；测试逐项检查数据、槽位、行列位置、掩码、最后一拍及错误响应。描述符接收、提交、首次输出和完成分别计数，背压期间检查全部有效输出字段保持稳定。每种配置还执行 1024 组配置计算检查。

| 参数组合 | 任务数 | 周期数 | 描述符接收数 | 描述符正常完成数 | 提交与接收同周期次数 | 输出拍数 |
|---|---:|---:|---:|---:|---:|---:|
| 16×16、8 路、窗口与预取 | 42 | 176795 | 2160 | 2159 | 2118 | 26728 |
| 16×16、16 路、窗口与预取 | 42 | 153734 | 2160 | 2159 | 2118 | 21838 |
| 4×4、2 路、普通模式、直连描述符 | 42 | 1215387 | 11573 | 11572 | 11573 | 59128 |

每种配置分别包含一个预期 AXI 错误任务。八路和十六路配置的最小描述符接收间隔为一个周期。三种配置合计完成 126 项任务、1545916 个周期和 107694 个输出拍。

`--source-root` 指定独立源码目录。脚本在该目录补齐真实模块依赖，并优先使用该目录提供的测试模块和观察器。构建使用一个编译进程。`rtl_status.json` 记录实际输入文件摘要，并检查测试期间源码是否变化。

`--target` 选择工程编译宏。前端各目标的算术及寄存边界相同；此处使用通用缓存存储模型，ASIC SRAM 单元由完整 NPU 集成测试覆盖。

## 形式与四态检查

```bash
python3 test/frontend_pipeline/check_window_match.py \
  --out build/frontend_pipeline/window
python3 test/frontend_pipeline/check_critical_paths.py \
  --out build/frontend_pipeline/critical
python3 test/frontend_pipeline/check_shared.py \
  --out build/frontend_pipeline/shared
python3 test/frontend_pipeline/check_direct.py \
  --out build/frontend_pipeline/direct
python3 test/frontend_pipeline/check_arithmetic.py \
  --out build/frontend_pipeline/arithmetic
python3 test/frontend_pipeline/check_control.py \
  --out build/frontend_pipeline/control
python3 test/frontend_group_feedback/check.py \
  --out build/frontend_pipeline/group
python3 test/frontend_group_feedback/stream_control.py \
  --out build/frontend_pipeline/stream

python3 test/conv_frontend/tools/check_dma_arithmetic.py \
  --out build/frontend_pipeline/dma_arithmetic
python3 test/conv_frontend/tools/check_configuration_arithmetic.py \
  --out build/frontend_pipeline/configuration_arithmetic
python3 test/conv_frontend/tools/check_chunk_mask.py \
  --out build/frontend_pipeline/chunk_mask
python3 test/conv_frontend/tools/check_short_sums.py \
  --out build/frontend_pipeline/short_sums
python3 test/conv_frontend/tools/check_epoch_shared.py \
  --out build/frontend_pipeline/epoch_shared
```

| 入口 | 检查内容 |
|---|---|
| `check_window_match.py` | 全部三十二位位置、全部十六位组配置下的三种窗口关系；120000 组二态及 X/Z 输入，360000 次标志比较 |
| `check_critical_paths.py` | 三种坐标位宽、五路移动地址、七种字大小、预取模式保存；40000 组四态输入，360000 次组合结果比较 |
| `check_shared.py` | 配置与运行阶段的实际乘法操作数选择，以及窗口位置的归纳关系 |
| `check_direct.py` | 2 至 128 字节数据字、两种描述符参数的完整三十二位地址回绕 |
| `check_arithmetic.py` | 分组加法、描述符有效列数与组边界的定宽关系 |
| `check_control.py` | 字内范围选择、补零范围独立性和范围更新事件；720896 次配置因子数值比较 |
| `frontend_group_feedback/check.py` | 1 至 8 路的通道递增、选择资格与行末条件；400000 次四态比较 |
| `stream_control.py` | 两种行地址模式、字内范围选择、组范围保存条件 |
| `check_dma_arithmetic.py` | 预取跨行坐标和配置部分积累加 |
| `check_configuration_arithmetic.py` | 分组范围、末列条件、下一组位置；60000 组四态输入 |
| `check_chunk_mask.py` | 4 种尺寸与 5 种通道数的输出掩码及传输数量选择 |
| `check_short_sums.py` | 完整历史横坐标和值和使用期限行偏移 |
| `check_epoch_shared.py` | 分组偏移、通道位置和本次传输数量之和 |

这些入口合计执行 149 组形式检查。数学模型的输入范围、事件模型和必要范围条件分别写入各项 `summary.json`。提取脚本读取实际职责模块，将端口名映射为验证模型的局部输入名；模块之间的连接由完整数值测试检查。四态检查合计 1180000 次，配置因子数值检查另计。

## 结构与局部路径

```bash
python3 test/frontend_pipeline/measure_structure.py \
  --out build/frontend_pipeline/structure
```

结构统计按十六路、64 位总线、4096 字节缓存及 128 字节行展开，统计前端五个职责模块中的乘法位宽与寄存器位数。该步骤执行 RTL 展开和位宽优化。

窗口和关键算术检查同时生成带输入、输出寄存器的局部综合模块及 `cases.json`。局部测量用于判断具体算术表达式的组合深度；完整 SoC 的资源、时钟与路径结果由独立综合入口产生。

本次验证的源码摘要、数值统计、形式检查和局部测量结果位置汇总于 [validation.json](validation.json)。
