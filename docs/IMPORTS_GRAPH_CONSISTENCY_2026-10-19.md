# imports 图谱一致性复核（B 线追加验收）

日期：2026-10-19（数据采集于 2026-10-18 22:08 EDT 之后，jetson 实机只读）
结论先行：**差异全部归因于"B 线验证跑是结构-only 重建（未喂 semantic enrichment 输入），不是数据丢失"；生产图已发布且 = 旧图 + 2508 条 imports 边，calls 零丢失、文件集零变化。不需要全量重跑。**

## 1. 对比的三份工件

| 工件 | 位置（jetson） | 产出时间 (local) | 节点/边 |
|---|---|---|---|
| 旧图（修复前最后发布版） | `~/dev/uyp/state/index-jobs/incr-d9de6dc7165e/rollback/ua/knowledge-graph.json`（即 `incr-7d9292bd7393` 的 staged 产物） | 10-18 21:54 | 24367 / 30917 |
| 旧图报告数字 24369/30919 | `incr-5152183d1660`(19:46)、`incr-251f0d1f8f46`(21:09)、`incr-2ca888d6dbdb`(21:38) 的 run-summary，逐字节吻合 | 10-18 19:46–21:38 | 24369 / 30919 |
| 新图（修复后已发布，live） | `~/dev/uyp/state/jarvis-homehub/ua/knowledge-graph.json`（`incr-d9de6dc7165e` staged → 22:08 提升） | 10-18 22:08 | 24370 / 33430 |
| B 线验证跑 19311/28182 | 未在 jetson/Mac 任何 run-summary 留痕（scratch state root）；本次已离线复现（见 §3） | 10-18 ~21:4x | 19311 / 28182 |

审计口径说明：24369/30919 与 rollback 实测 24367/30917 差 ±2，来自 21:38→21:54 两次增量之间 harness_contracts 等文件的正常轮换，同一血统。

## 2. 逐项分布对比（旧 rollback vs 新 live，jetson 实测）

| 维度 | 旧图 | 新图 | 差 |
|---|---|---|---|
| root / grant | jarvis-homehub / g_1393b498 | 相同 | 无 |
| stagedFiles | 3360 | 3359 | -1（文件轮换） |
| manifest total | 3362 | 3362 | 无 |
| scan files → results | 2166 → 2065 | 2166 → 2065 | 无 |
| file 节点 | 2065 | 2065 | **0** |
| function 节点 | 12193 | 12198 | +5 |
| class 节点 | 5051 | 5051 | 0 |
| concept 节点 | 5058 | 5056 | -2（17 出 15 进，见下） |
| contains 边 | 17244 | 17249 | +5（无丢失） |
| calls 边 | 8428 | 8428 | **0（逐条集合级零差异）** |
| related 边 | 5245 | 5245 | 总数持平（17 出 17 进） |
| imports 边 | **0** | **2508** | +2508（修复目标） |
| languages | 8 种 | 8 种 | 无 |
| layers / tour | 8 层 / 10 步 | 8 层 / 10 步（名字集合相同） | 无 |

集合级 diff（按 node id / (source,target,type) 多重集）：

- 节点消失 17 个：全部是 `concept:*`，集中于 `jetson/packages/harness_contracts/**` 两个变更文件——这些文件在 21:38→22:08 之间被重新富集，旧标签换新标签（新增 15 个 concept + 5 个 function 对应其内容变化）。
- 边消失 17 条：全部是对应的 `related` 边；新增 17 条 related + 5 条 contains + 2508 条 imports。
- **没有任何 file/class/function/calls 消失。**

imports 边质量：2508 条全部双端在图内（0 dangling）；720 个文件作为 import 源、845 个文件作为 import 目标；与修复 commit `651e799` 描述的实测（2166 文件 3.07s，10/10 抽样吻合真实 import 语句）一致。部署核实：jetson `~/dev/uyp/indexer/ua_bridge.py` md5 = 仓 `services/indexer/src/ua_bridge.py` md5（`fa54423b…`），修复版即当前生产版。

## 3. B 线 19311/28182 的归因（离线复现实证）

机制：`ua_bridge.run()` 只有在拿到 `--knowledge-root`（enrichment worker 的 `*.knowledge.json`）时才会组装 `semanticByPath`；`ua_graph_builder.mjs` 由 `semanticByPath` 派生 concept 节点与 related 边。B 线验证跑没有喂这个输入（scratch 环境），因此是"结构 + imports、无语义"的图。

复现（只读，jetson /tmp）：取已提升作业的 `intermediate/graph-input.json`（results 2065 / semanticByPath 3253 / importsByPath 2508 条目），仅清空 `semanticByPath` 后用生产 `ua_graph_builder.mjs` + UA dist 重建：

```
nodes 19314  edges 28185
function 12198 / class 5051 / file 2065 / concept 0
contains 17249 / calls 8428 / imports 2508
```

与 B 线报告的 19311/28182 同构，±3 来自快照时点差异（当晚 stagedFiles 在 3357–3361 间摆动，3 个符号级条目差异）。因此：

- **~5000 节点差 = 5056 个 concept 节点没进验证图**；
- **~2700 边差 = 5245 条 related 边没进验证图**；
- calls/contains/imports 与生产新图完全一致——**不是丢失，是验证跑的输入范围（scope）不含语义富集产物**。

生产图（22:08 提升）从来没有丢 concept：24370/33430 本身就是"旧图 + imports"。

## 4. 硬性验收判定

1. **calls/contains 无意外减少**：calls 8428→8428（集合级零消失）；contains 17244→17249（只增不减）。按文件数归一化（2065 个 file 节点两侧相同）：calls/file、contains/file 严格不降。
2. **不相关节点无大规模消失**：唯一消失项是 17 个 concept（对应 2 个真实变更文件的富集轮换，有 15 个新 concept 顶替）。file/class/function 零消失。
3. **覆盖范围没有缩窄**：root、grant、manifest total、scan 文件数、results 文件数、languages、layers、tour 全部相同。新图覆盖 = 旧图覆盖 ∪ imports。
4. **是否需要全量重跑**：不需要。已发布的 live 图就是全量结果；B 线的 19311 数字只是验证方法学造成的缩小视图。若日后再做同类验证，要么带上 `--knowledge-root`，要么在报告里明确标注"结构-only 验证图"，避免再次触发 5000 节点疑云。

## 5. 顺带发现（非本次回归，记录备查）

- **重复节点条目**：新旧图各有 432 条重复 id 条目（248 个 function id + 27 个 class id 有重复，如 Swift 同名重载/同文件同名符号），两侧数量一致，是 GraphBuilder 的 id 方案既有特性，不是 imports 修复引入的。将来可做去重卫生项。
- **scan→results 差 101 个文件**：两侧一致，均为非代码扩展名（.txt 46、.service 22、无扩展 9、.conf 7 等），extract-structure 不为它们产 results，属扫描器既定行为。
- **概念覆盖**：生产图 2065 个 results 文件中 2040 个有 semantic 条目（3253 条 semantic 记录），25 个代码文件无富集（skip/降级路径）。

## 6. 证据脚本

- 队列/图 diff、无语义重建：jetson `/tmp/uyp_imports-audit/`（graph-input-nosemantic.json + knowledge-graph-nosemantic.json）、`/tmp/uyp_audit_graph.py`、`/tmp/uyp_layers.py`（Mac 侧原件在 /tmp 同名）。
- 关键 job：`incr-7d9292bd7393`（旧图最后发布）、`incr-d9de6dc7165e`（imports 修复发布，events.jsonl 完整记录 discovered→authorized(grantEpoch 94)→staged→published）。
