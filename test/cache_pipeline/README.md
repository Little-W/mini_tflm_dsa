# 缓存请求与响应流水

`conv_windowed_cache` 使用 `req_valid`、`req_ready` 接收有序字请求。`cfg_windowed=1` 时，`DEMAND_DEPTH` 限制已经接收且尚未返回完成的请求数，默认值为四。请求描述与已完成响应分别存放在两个队列中，统一计数器同时覆盖队列和正在处理的请求。

## 返回时序

`DEMAND_DEPTH` 大于一时，缓存完成结果先写入已有响应队列，数据、错误状态和有效状态经过同一时钟边界。首次命中响应在请求接收后两个周期完成；连续命中请求仍可每周期接收一个字并返回一个字。`DEMAND_DEPTH=1` 时，保留同步 RAM 读出后的直接返回，命中延迟为一个周期。

响应队列仅在 `rsp_valid && rsp_ready` 时移除队首内容。下游暂停时，`rsp_valid`、数据和错误状态保持稳定。`rsp_data` 与 `rsp_error` 在 `rsp_valid=1` 时有效。响应顺序始终与请求接收顺序相同。

数据 RAM 的容量和同步读写方式保持不变。`cfg_windowed=0` 的几何提示模式每次只接收一个请求，使提示信息始终属于当前请求。

## 读写宽度与容量

`BUS_WIDTH` 决定 AXI 读取与缓存填充宽度，`READ_WIDTH` 决定缓存返回的数据宽度，默认均为 32 位。验证程序支持 32/64 位 AXI 和 32/64/128 位缓存读取。二者可独立配置，缓存总数据容量始终为 `SETS * WAYS * LINE_BYTES` 字节。

`conv_sdp_ram` 的读写地址均以 32 位字为单位。一次读取返回包含该地址的自然地址分组，每个 32 位输出字分别选择对应存储块。存储块数量由较大的读写宽度决定，每块深度相应减小。各存储块使用同步读取、单写端口和逐字节写入掩码；扩大读取宽度不复制数据 RAM。

例如，双路、32 组、128 字节缓存行为 8 KiB 数据，使用 AXI64 填充和 128 位读取时，每路包含四个 32 位同步存储块，每块深度为 256。填充与需求读取访问同一物理存储位置时，冲突周期暂停该次数据预读，随后重新建立有效读取结果。

`cfg_ready` 要求全部已接收请求、响应、填充及预取工作完成。持续设置 `cfg_valid` 会阻止新请求，已接收工作继续执行。复位清空请求和响应计数，取消尚未完成的请求。正常运行期间，每个已接收请求恰好生成一个响应，包括地址范围错误与 AXI 读取错误。

## 统计定义

- `stat_hits` 和 `stat_misses` 按外部请求接收时的驻留状态计数。
- 测试中的 `stat_lookup_hits` 和 `stat_lookup_misses` 按队列请求进入查询阶段时的驻留状态计数。
- `stat_peak_outstanding` 记录当前配置下已经接收且尚未消费响应的请求峰值。

范围外请求返回错误，不参与命中及未命中统计。新配置接收时清零统计。

## 验证方法

```sh
python3 test/cache_pipeline/run.py --verilator /path/to/verilator --jobs 2
python3 test/conv_replacement/run_cache_policy.py --verilator /path/to/verilator
python3 test/windowed_cache/run.py --cache-sets 128 --cache-policy 3
python3 test/cache_storage/synthesis.py --out build/cache_response_synthesis

python3 test/cache_pipeline/run.py --bus-width 64 --read-width 32 \
  --line-bytes 16 --cache-bytes 4096 --profiles 1:2 4:2 \
  --out build/cache_axi64_read32
python3 test/cache_pipeline/run.py --bus-width 64 --read-width 128 \
  --line-bytes 128 --cache-bytes 8192 --profiles 1:2 \
  --out build/cache_axi64_read128
```

默认队列测试包含四组参数：深度四、二、一且双路缓存，以及深度四且单路缓存。每组检查十二项情形：冷请求排队、连续命中、响应暂停、同组冲突、范围错误顺序、填充错误恢复、预取期间接收请求、预取错误恢复、配置等待完成、执行期间复位、分配区间边缘的旁路读取及几何提示顺序。

连续命中测试对十六个不同的驻留字地址循环发出六十四个请求，检查每次接收与返回的周期、每个数据字节以及外部读取次数。独立计数检查队列容量和请求所有权。AXI 模型改变地址接收和数据返回的等待时间，同时检查分配区间与 4 KiB 事务边界。

结果保存在指定目录的 `summary.json` 中，包括各项测试、延迟、连续传输间隔、源文件散列和可执行文件散列。

预取队列的循环优先选择及其独立验证见 [PREFETCH_SELECTION.md](PREFETCH_SELECTION.md)。

## FPGA 测量

128 组、双路、64 位 AXI 数据总线的独立测量结果如下。比较版本为 `4df62f2`。

| 项目 | 比较版本 | 寄存响应版本 |
|---|---:|---:|
| 逻辑 LUT | 5,337 | 5,447 |
| 触发器 | 2,424 | 2,424 |
| RAMB18E1 | 24 | 24 |
| CARRY4 | 118 | 118 |
| 到 `rsp_data`、`rsp_error` 的最长组合单元数 | 12 | 1 |
| 到 `rsp_valid` 的最长组合单元数 | 8 | 1 |
| 到 `req_ready` 的最长组合单元数 | 9 | 3 |
| 模块内部最长组合单元数 | 14 | 14 |

响应寄存边界切断标签查询、命中选择与下游消费者之间的组合传播。实际频率仍需完整器件布局布线时序报告。测量数据及测试摘要保存在 `docs/data/cache_response_validation.json`。
