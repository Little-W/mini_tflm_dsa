# 窗口缓存接收与返回路径验证

本目录验证 `rtl/npu/dma/cache/conv_read_cache.sv` 中的窗口缓存。单项需求队列直接返回命中数据，各路标签比较与工作请求的接收条件并行计算；多项需求队列使用已有响应队列保存数据、有效位和错误位。两种配置保留各自的接口周期、返回顺序、回压行为和配置清理行为。

需求候选和预取候选分别比较元数据占用，再选择对应结果。替换快照的保持条件和替换完成条件并行计算，状态更新在最后合并两个结果。

单项需求队列将查询有效位与标签在同一边沿保存。查询有效位读取 `lookup_read_set`，同拍清除或填充写入通过写地址比较转发；返回判断使用已保存的有效位和 `lookup_snapshot_set`。

同一边沿还保存填充组号与查询快照组号的匹配结果 `lookup_fill_set_match_q`。组合逻辑按 `fill_set` 和 `lookup_snapshot_set` 的实际更新条件分别计算下一值，再保存比较结果。填充状态进入空闲、填充成功、配置接收和复位时，比较使用相应寄存器的更新或保持条件，因此时钟边沿后的匹配状态等于当前两个完整组号的比较结果。查询有效位屏蔽直接使用这一位状态，当前填充状态和路号继续控制替换行保护。

单项队列的预读取端口使用已保存的匹配状态；其余元数据读取端口和多项队列继续采用当前组号比较。标签及组合组号比较按三个比特分组并行计算。公开请求、返回、配置和错误处理的周期关系保持一致。

## 验证范围

`run.py` 从待测文件和参考源码中提取实际返回表达式，包含工作请求接收条件、工作请求与缺失请求的标签选择、旁路状态、各路优先顺序以及数据和错误返回。快照有效位、集合索引和地址匹配状态均作为自由输入，快照就绪条件使用两侧的实际表达式。组合 SAT 检查不增加输入假设，覆盖 1、2、3、4 路，32、64、128 位读取宽度，16、128 字节缓存行，以及 1、4、8 项需求队列。

替换选择检查同时比较 `select_launch`、`candidate_metadata_busy` 和 `select_stage_valid` 下一状态，覆盖组号宽度 1、7、9 位与路号宽度 1、2、3 位。该检查直接提取实际组合表达式和状态更新代码，不增加输入假设。

完整缓存证明在存储器展开后检查公开控制输出、请求描述、内部状态及全部有效位存储。响应数据在 `rsp_valid` 成立时比较，响应队列按实际写入条件比较保存的数据。参考提交为 `dde5e7c9836a71f0292d7c69040f8635840e6bad`；两侧使用同一组保存的公共模块依赖。

`lookup_check.py` 覆盖五种完整缓存配置：16 字节缓存行下的 2 组、1 路、1 项队列；2 组、2 路、1 项队列；4 组、2 路、4 项队列，以及 128 字节缓存行下的 2 组、2 路、1 项队列和实际 SoC 使用的 16 组、2 路、1 项队列。全部配置使用 64 位 AXI 和 64 位读取数据。证明比较复位、配置清除、读写同址、填充、替换、响应背压及错误处理产生的状态和输出，不增加输入假设。仅预读取端口采用独立的中间信号名称；展开后的全部有效位存储仍逐位比较。

`fill_match_check.py` 使用独立保存的 `fill_match_reference.sv`，完成 11 组响应表达式检查和以上五种完整配置证明。除了公开接口、全部共同状态和存储内容，证明还逐周期比较新增匹配状态与参考实现中的完整组号相等表达式。新增状态的关系由实际更新过程证明，输入保持无约束。当前源码摘要为 `d3f8d0ca9e9f1003c14cd879c710decd4584bab2ed45f23cf1b9f30d0ad87a7c`，参考摘要为 `8bf88304f14493fe183aedbeb56140794ef2e3b1f25ad38f0ba82e66a6bfc858`。

`test/cache_pipeline/run.py` 在 128 组、2 路、16 字节缓存行、64 位 AXI、32 位读取宽度下检查以下行为：

- 冷缓存请求排队、连续命中和响应回压。
- 同组地址冲突、范围错误和填充错误后的恢复。
- 预取接收、预取错误恢复和几何提示顺序。
- 配置等待已有请求完成、复位取消未完成请求和旁路边界读取。

单项队列命中延迟为 1 周期；四项队列命中延迟为 2 周期。连续命中时，两种配置的接收间隔和返回间隔均为 1 周期。测试同时检查停顿期间的响应稳定性、返回顺序和请求完成次数。

## 资源与路径测量

`measure.py` 对参考源码和当前源码分别综合完整窗口缓存。当前匹配状态测量采用 16 组、2 路、128 字节缓存行、64 位 AXI、64 位读取宽度和 `DEMAND_DEPTH=1`。综合命令使用 `synth_xilinx -family xc7 -noiopad -noclkbuf -flatten`，器件记录为 `xc7a200tfbg484-3`，两侧公共前缀模块均为 `746fd83d9dc5c704f6536b9521ab65ea825fa62065e1217e7758fddf92867280`。

| 独立完整缓存 | 参考实现 | 保存匹配状态 |
| --- | ---: | ---: |
| 逻辑 LUT | 3,567 | 3,615 |
| 寄存器 | 2,374 | 2,371 |
| 分布式存储的标称 LUT | 376 | 376 |
| RAMB18E1 | 9 | 9 |
| 最长寄存器间组合级数 | 12 | 12 |

保存匹配状态后，`lookup_snapshot_set` 到 `rsp_data` 的组合依赖消失，新增匹配位到 `rsp_data` 为 4 级、到 `rsp_valid` 为 5 级。匹配位自身的数据输入最长为 10 级。完整返回路径还包含标签比较，当前独立模块的 `rsp_data` 和 `rsp_valid` 最长分别为 6 级和 7 级。

报告包括逻辑 LUT、分布式存储占用的标称 LUT、寄存器、进位单元、BRAM 和 DSP 数量，以及映射网表中的实际连接路径。`boundary_paths.json` 保存请求地址到描述寄存器、预取输入到保存状态，以及寄存器到返回接口的逐级路径。

接口路径统计在内存中的网表分析对象上增加起终点标记；综合网表保持原样，端点标记不计入组合逻辑级数。报告中的逻辑 LUT 数量来自映射结果，布局后的物理 LUT 数量和传播延迟由实现工具报告。完整 SoC 路径还包含模块外部的控制与算术逻辑。

与图像前端和窗口队列相连时，完整 DMA 测量采用 8 个数据通道，并分别检查 128 组、16 字节缓存行以及 16 组、128 字节缓存行。复现命令及完整 DMA 参数见 `test/frontend_depth_timing/README.md`。每次结果均记录所用源码摘要，独立缓存和完整 DMA 的资源及路径分别报告。

## 复现命令

在仓库根目录执行：

```bash
python test/cache_receive_timing/run.py --payload-when-valid \
  --out build/cache_receive_timing/formal

python test/cache_receive_timing/lookup_check.py \
  --out build/cache_receive_timing/lookup_formal

python test/cache_receive_timing/fill_match_check.py \
  --out build/cache_receive_timing/fill_match_formal

python test/cache_receive_timing/measure.py \
  --reference test/cache_receive_timing/fill_match_reference.sv \
  --candidate rtl/npu/dma/cache/conv_read_cache.sv \
  --sets 16 --read-width 64 --line-bytes 128 --depths 1 \
  --out build/cache_receive_timing/measurement

python test/cache_receive_timing/fill_match_collect.py \
  --formal build/cache_receive_timing/fill_match_formal/summary.json \
  --reference-mapping build/cache_receive_timing/measurement/synthesis/reference_d1 \
  --candidate-mapping build/cache_receive_timing/measurement/synthesis/current_d1 \
  --out build/cache_receive_timing/verification.json

python test/cache_pipeline/run.py \
  --bus-width 64 --read-width 32 --line-bytes 16 --cache-bytes 4096 \
  --profiles 1:2 4:2 --jobs 2 \
  --out build/cache_receive_timing/pipeline
```

形式验证和综合使用安装了 `pyosys` 及 `read_slang` 的 Python 环境；流水测试使用 Verilator。证明和综合入口均支持 `--reference` 与 `--candidate`，参考源码可以指定提交或本地文件，候选源码可以指定本地文件。`run.py` 和 `measure.py` 还支持 `--read-width` 和 `--line-bytes`；`run.py --profiles` 指定组数、路数和队列深度，`lookup_check.py` 与 `fill_match_check.py` 使用 `SETS:WAYS:DEMAND_DEPTH:LINE_BYTES` 指定完整配置。`measure.py --sets` 和 `--depths` 指定组数与需要综合的队列深度。综合入口支持 `--lock-file`，可与其他大型综合任务共用文件锁。

每次运行在指定输出目录保存实际输入文件、SHA256、工具脚本、日志及摘要，并检查运行期间源码是否发生变化。
