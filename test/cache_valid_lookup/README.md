# 窗口缓存有效位读取

本文保存的资源与路径记录使用当次固定源码、RTL 算术属性选择和 740 个 DSP 的总预算，具体源码与配置见随文测量报告。文中的运行命令用于当前工作区，采用普通 RTL 自动映射并生成新的资源与路径报告。

`conv_windowed_cache` 并行读取请求队首、下一项、新输入请求和当前缺失请求对应的有效位。每个候选独立处理同周期写入转发，出队状态选择已经形成的一位结果。标签、有效位和请求上下文仍在同一个时钟边沿保存，接口接收和返回周期保持一致。

`DEMAND_DEPTH=1` 使用单请求读取结构。队列深度大于一时使用四个候选，综合工具根据实际消费者删除未使用的存储端口。所有存储和算术均采用行为级 RTL。

## 生产参数测量

参数为 `SETS=16`、`WAYS=2`、`LINE_BYTES=128`、`BUS_WIDTH=64`、`READ_WIDTH=64`、`DEMAND_DEPTH=2`、`CACHE_POLICY=3`、`p_defer_retire_shift=1`。资源和路径来自完整的独立缓存映射图，包含内部区间读取器。

| 项目 | 参考版本 | 当前版本 |
|---|---:|---:|
| 逻辑 LUT | 3,288 | 3,439 |
| LUT RAM 名义占用 | 420 | 420 |
| LUT 名义总数 | 3,708 | 3,859 |
| 触发器 | 2,461 | 2,461 |
| DSP | 21 | 21 |
| RAMB18 | 9 | 9 |
| 寄存器之间最长组合级数 | 11 | 10 |

参考源码提交为 `5ce30e267f4323cacab9427c686349658a225b41`。测量记录包含完整图检查结果；150 MHz 的器件实现时序使用 Vivado 布局布线后的时序报告确认。

## 功能检查

- 三组完整模块等价证明通过，共检查 56,416 位状态和输出。覆盖生产参数、32 位总线小缓存以及深度四、单路缓存，输入不施加限制。证明检查所有存储状态和实际消费者，异步读端口通过保存后的有效位及其消费者验证。
- 四组四态检查通过，共 54,400 次比较。测试从实际 RTL 提取查询地址选择、有效位存储及同周期写入转发表达式，覆盖二值、未知值和高阻值输入。
- 深度一和深度二分别通过 12 个独立缓存场景，共接收 363 个请求、完成 360 个请求，并检查复位取消的 3 个请求。稳定命中期间，请求接收间隔和返回间隔均为一个周期。
- 采用第九轮 SoC 固定源码及当前缓存的前端测试通过 84 个独立数值任务，覆盖窗口模式开关、连续描述符、两个在途请求、背压和错误恢复。

详细报告位于 `build/cache_valid_lookup/results`。`validation.json` 保存参数、总检查量、资源结果、完整报告位置及 SHA256。

## 重新运行

将参考提交的源码导出至独立目录，并将 `REFERENCE_ROOT` 指向该目录：

```bash
python3 test/windowed_cache_timing/run_formal.py \
  --reference-root "$REFERENCE_ROOT" \
  --profiles 2:2:16:2:32:32:0 16:2:128:2:64:64:1 4:1:32:4:64:32:0 \
  --out build/cache_valid_lookup/formal
python3 test/cache_valid_lookup/run_four_state.py \
  --reference-root "$REFERENCE_ROOT" \
  --out build/cache_valid_lookup/four_state
python3 test/cache_pipeline/run.py --fpga \
  --bus-width 64 --read-width 64 --line-bytes 128 --cache-bytes 4096 \
  --profiles 1:2 2:2 --jobs 1 --out build/cache_valid_lookup/numeric
python3 test/conv_frontend/tools/run_numeric.py --fpga --sizes 16 --continuous \
  --out build/cache_valid_lookup/frontend
python3 scripts/fpga/open_fpga_synth.py \
  --case-config test/cache_valid_lookup/synthesis_cases.json \
  --cases windowed_cache \
  --max-register-path-cells 10 --require-register-path-limit \
  --out build/cache_valid_lookup/synthesis
```
