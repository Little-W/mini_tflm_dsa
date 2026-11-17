# 设备规划器检查

规划器使用输入格式与最大非末 K 前缀计算 S24 或 RAW32 上界。WS 与 IS 的部分和均不含 bias。长流按每帧分别计算各部分和存储体的最大占用，并允许配置覆盖实际列块数的最小二次幂 W；未使用的列块不占部分和容量。微命令使用同一格式上界保留一个保护帧，驻留数预测仅参与成本估算。

`literal_record_bytes` 表示已由调用方证明的记录上界。当前硬件的静态预约采用 48 或 64 字节；32 字节上界可归入 48 字节预约。`payload_bound_bytes` 记录实际列块数对应的 RAW32 容量，便于检查 RAW 可行性。`candidates_evaluated` 记录实际完成成本评分的候选数。图像几何字段仅参与工作量评分，部分和准入继续使用格式上界和实际存储容量。

快速搜索会跳过被较小 R 完整覆盖的配置以及 RAW 已覆盖所有 W 的压缩搜索。微命令评分先检查必要的操作数读取量、阵列工作量和命令成本。在图像缓存没有容量压力时，整 R 帧的读取量随窗口增大而单调下降，可以直接求出达到最少读取轮数的最小 W。IS 图像窗口可能超过图像缓存时，搜索保留会改变读取轮数的较小 W；相同读取轮数只保留工作集较小的配置。

## 本机检查

在仓库根目录运行：

```sh
python3 test/capacity/planner/run_checks.py --out build/planner/native
```

脚本以 C11、O1 和 UndefinedBehaviorSanitizer 编译并执行五组检查：

- 10,000 个请求比较快速搜索与通用 64 位搜索的 42 个决策和成本字段；候选计数检查大于零且不超过通用搜索。
- 随机形状与物理配置比较优化搜索和穷举搜索；RAW 读取量另用实际缓存槽访问顺序重放检查。
- 输入类型、偏移、K 边界、逐帧存储体取整、尾窗口、驻留预测及 RAW 退回方案。
- 10,000 组图像描述和 20,000 次独立整数公式检查，覆盖缓存容量、旁路读取、S8/S16 源格式和小窗口微命令。
- 1,200 个共享分配请求比较完整候选枚举，覆盖 6–9 个物理 bank、RAW 微命令、目录尾组和逐 bank 预约；对选中的 42 个决策与成本字段逐项检查。

`summary.json` 保存编译命令、源文件摘要、可执行程序摘要和各项计数。运行 `python3 test/capacity/run_memory_policy.py` 可检查两个公开驱动接口的共享容量选择、RAW32 策略切换与 Prepared 描述符。

## RV32 规划周期

先准备四模型目录，其中每个模型具有包含张量类型、量化参数和算子列表的 `manifest.json`。将 `--simulator` 指向已有的 `Vtb_model_benchmark` SoC 可执行程序：

```sh
python3 test/capacity/planner/run_latency.py \
  --prepared build/model_benchmark/prepared \
  --simulator build/model_benchmark/sim/obj/Vtb_model_benchmark \
  --pool-bytes 12288 --ia-bytes 2048 --frames 16 \
  --out build/planner/rv32
```

测试从 35 个算子的实际输入格式和偏移建立 RAW、adaptive 两组请求，共测量 70 次冷规划，包括图像字段准备和 `gempact_plan_device` 或 `gempact_plan_shared` 调用。Conv 的原始 S8 格式用于静态部分和证明，内部输入暂存按每元素两字节计入请求。每次调用在 PicoRV32 上读取周期计数器，并将全部 43 个结果字段与启用 UndefinedBehaviorSanitizer 的本机 C 程序逐项比较。该测试测量 CPU 规划时间。

可用 `--compare-include PATH` 指定另一份 `gempact_tiling.h` 的目录，以相同请求测量两个实现。报告分别保存结果和周期。增加 `--require-equivalent` 时，脚本要求两个实现共有的决策和成本字段相同，并检查优化实现的评分次数不增加。所有临时源码、ELF、存储器初始化文件和运行输出均在 `--out` 目录生成。

## 图像几何评分

请求末尾增加五个字段：源元素字节数、一个 K16 块内的有效通道数、每个空间位置的图像工作集字节数、输入图像与 im2col 元素字节数之比的 Q8 值，以及图像缓存字节数。`gempact_set_im2col_geometry` 从输入张量形状、卷积核形状、水平步长和源类型计算这些字段；矩阵乘法与 Dense 保持这些字段为零。

图像基础工作量由访问元素数和像素通道段数构成。对每个候选，空间窗口为 WS 的 `16R` 或 IS 的 `16W`，并限制到实际输出空间位置数。微命令的 IS 窗口还受预计驻留帧数限制。一个 K16 阶段的图像工作集超过缓存容量时，评分增加估计的重复读取成本。公式采用整数 Q8 运算，不读取激活值或未来部分和。

当前两个公开驱动头均以 `DSA_IM2COL_CACHE_BYTES=4096` 描述图像缓存，对应 128 个集合、每集合两个 16 字节缓存行。这是编译期硬件配置，驱动不通过现有 MMIO 获取该值。启用 `bypass_cache` 时传入零缓存容量。1×1 卷积或所有候选工作集均可容纳时，评分继续使用单调搜索。几何权重表示服务工作量估计；最终性能由实际 RTL 和 SoC 周期测量确定。

RAW 与 adaptive 使用同一组几何字段、同一评分公式和相同排序规则。快速实现与通用 64 位实现逐字段比较，另对完整候选集合检查最终配置。规划结果缓存也比较全部五个几何字段，防止形状相同、图像访问方式不同的卷积复用另一份计划。

## 共享 IA 与部分和容量

共享接口由硬件能力寄存器给出总字节数、每个 bank 的字节数、合法 IA bank 数掩码和目录行数。当前实现接受 6–9 个 2 KiB bank。默认七个 bank 的合法 IA 分配为 1、2、4 个 bank，对应 IA 2/4/8 KiB 与部分和 12/10/6 KiB。`gempact_plan_shared` 对 RAW 和 adaptive 使用同一分配集合与成本排序。

紧凑 IA 每行使用一个 128 位字，宽 IA 每行使用两个字，因此宽 IA 至少需要两个物理 bank。IA 格式按 WS 或 IS 的流动操作数确定。跨 K 的 RAW32 部分和需要至少四个 PS bank，已证明 S24 上界时可以使用三个；单个 K16 块的任务没有部分和存储访问。每个 PS bank 深度为 128 字，长流为每帧预约 `ceil(rows * record_words / ps_bank_count)` 字，再乘实际驻留帧数。微命令要求一帧能够预约，并由硬件保留各帧 K 进度处理容量压力。

目录步长在一个任务中固定为最大帧行数。目录容量限制为 `min(frame_count, directory_rows / stride)`，尾行组沿用同一个步长。RAW 微命令可以使用 16 行、32 行或整个 R 行组的帧；其合法性不要求整个窗口同时以 RAW32 驻留。

规划结果包含选中的 `ia_bank_count`、`ia_bytes` 与 `pool_bytes`。`raw_safe` 同时携带 WS/IS、PS_CONTROL、切片行数以及 RAW 方案自己的分配，可直接构造完整任务。驱动在任务启动前写入 IA bank 数；一次任务执行期间保持分配不变。共享能力、量化偏移、图像几何、数据类型和完整形状均参与规划缓存查询。冷调用与缓存命中调用均在原有规划计时区间内完成。

共享分配的 RV32 检查示例：

```sh
python3 test/capacity/planner/run_latency.py \
  --prepared build/model_benchmark/prepared \
  --simulator build/model_benchmark/sim/obj/Vtb_model_benchmark \
  --shared-total-bytes 14336 --bank-bytes 2048 \
  --ia-bank-mask 0x16 --directory-rows 1024 \
  --out build/planner/shared_rv32
python3 test/capacity/planner/test_bridge.py \
  --rv32-report build/planner/shared_rv32/summary.json \
  --out build/planner/shared_bridge.json
```

Python 容量工具调用 `device_planner.plan(request, shared_memory, im2col_geometry)`，通过固定宽度整数数组调用同一个生产 C 规划函数。测试对 70 个实际模型请求检查 C、RV32 和 Python 返回的完整配置与成本。
