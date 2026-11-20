# 预取标签的同步读取端口共享

每路缓存的标签存储使用五个同步读取端口，分别服务需求查询、活动预取、当前预取候选、下一段预取候选和提示更新。新描述接收时，两个候选端口选择输入地址；描述保持期间，选择已保存的地址。读取选择发生在存储读取的时钟边沿之前。

## 读取周期

`offer_capture` 同时控制描述符接收和候选标签的读取地址。原有 `offer_fresh_q` 在同一边沿保存该事件，并继续控制快照有效性检查。

| 读取边沿的条件 | 当前候选读取地址 | 下一段候选读取地址 |
|---|---|---|
| 接收新预取描述 | `initial_pf_set` | `next_pf_set` |
| 保持已有描述 | `offer_set_q` | `offer_next_set_q` |

读取结果仍在该边沿之后提供。描述接收与消费同时发生、描述暂停、同地址标签写入和读取、配置以及复位都沿用原有周期和资格条件。`REGFILE` 在同周期同地址读写时返回写入前的数据。

## 存储组成与资源

比较版本为 `f178178b839e5e4019e42fd52bdfece6526ebe96`。独立综合使用 128 组、两路、16 字节缓存行、64 位 AXI 和四个在途请求。数据存储继续提供 4,096 字节，八项预取队列和需求队列保持原容量。

| 项目 | 七个标签读端口 | 五个标签读端口 |
|---|---:|---:|
| 逻辑 LUT | 5,116 | 5,026 |
| 触发器 | 2,424 | 2,410 |
| 分布式 RAM 占用的 LUT | 340 | 340 |
| RAMB18E1 | 24 | 20 |
| CARRY4 | 117 | 117 |
| 模块内部最长组合单元数 | 14 | 14 |
| 到响应数据、错误及有效输出的最长组合单元数 | 1 | 1 |
| 到请求就绪输出的最长组合单元数 | 3 | 3 |

24 个 RAMB18E1 的组成是数据存储 4 个、标签读取复制 14 个和替换顺序存储 6 个。共享读取端口后，标签部分使用 10 个 RAMB18E1。存储资源由 `REGFILE` 的普通同步读写语义推断。

本项独立节省 90 个逻辑 LUT、14 个触发器和 4 个 RAMB18E1；与替换来源写入选择合计节省 226 个逻辑 LUT。实际频率由完整器件布局布线报告检查。

## 形式验证

证明脚本从实际 RTL 提取读取地址、标签输出和 `offer_fresh_q` 更新，并使用公共 `REGFILE` 的同步读取语句。所有存储内容、读取地址、描述接收事件及复位后的配置事件均不限制取值。时间归纳比较五个标签输出，覆盖以下参数：

| SETS | LINE_BYTES | 比较的标签输出位数 |
|---:|---:|---:|
| 2 | 8 | 145 |
| 8 | 16 | 140 |
| 32 | 16 | 140 |
| 128 | 16 | 140 |
| 128 | 256 | 120 |

复位使 `configured` 清零，全部标签消费者均要求经过该状态限定的有效缓存行。证明检查该资格关系，并从复位开始证明所有可被消费的标签结果相同。标签写入连接、存储写入行为及其余模块内容保持相同。

接口比较覆盖 32 位和 64 位 AXI、缓存路数一和二、需求深度一和四，包含八项预取全部占用、循环复用、同时入队与移除、背压、错误恢复及复位。生产容量测试通过实际前端请求检查预取开启和关闭的访问顺序与返回值。

六组接口比较共通过 78 项场景，四组流水配置通过 48 项检查，几何提示检查完成 39 个请求。策略 3 开启和关闭预取的 18 项生产任务累计 711,918 个周期，各项结果与比较版本相同。策略 0 至 2 的模块源码逐字相同，其 27 项生产任务记录保存在替换来源验证报告中。

机器可读结果、源码哈希、存储组成及路径摘要见 [`cache_tag_ports_validation.json`](../../docs/data/cache_tag_ports_validation.json)。

## 复现

```sh
python3 test/cache_storage/tag_port_equivalence.py --out build/cache_tag_ports/formal
python3 test/cache_storage/compare.py --reference-commit f178178b839e5e4019e42fd52bdfece6526ebe96 --out build/cache_tag_ports/compare
python3 test/cache_pipeline/run.py --out build/cache_tag_ports/pipeline --jobs 2
python3 test/conv_replacement/run_cache_policy.py --out build/cache_tag_ports/policy
python3 test/windowed_cache/run.py --cache-sets 128 --cache-policy 3
python3 test/windowed_cache/run.py --cache-sets 128 --cache-policy 3 --no-prefetch
python3 test/cache_storage/synthesis.py --out build/cache_tag_ports/synthesis
```

布局前的逻辑 LUT 与组合单元数量用于比较该模块结构。两个版本的实际映射网表均保留存储原语和全部寄存器消费端。
