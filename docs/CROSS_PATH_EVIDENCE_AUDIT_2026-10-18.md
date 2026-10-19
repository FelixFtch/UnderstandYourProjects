# 跨路径 Evidence 与权限回归（横向收口验证）— 2026-10-18

真机回归，不改生产代码、不重启服务、不发群消息；:8790 探针全部为只读 `/query`。
原始 response JSON 全部存于 `docs/evidence-crosspath-20261018/`（见附录 A）。

## 0. 结论（先读这个）

| 问题 | 结论 |
|---|---|
| 三路径是否返回同一种 KnowledgeEvidence 语义 | **否**。只有路径 1（Studio/search 与 ask）产出冻结契约 KnowledgeEvidence；路径 3 群组层刻意不带 evidence（代码注释明说）；路径 2 语音层只有 `{score, source, brain, text}` 四字段裸块，六个冻结字段一个都没有 |
| 权限过滤是否都在检索前 | **否**。路径 1/3 检索前（fail-closed）；路径 2 brain 级授权在检索前，但 project_knowledge 内容是**先检索后遮蔽**（行为级证实，见 §4.2） |
| 越权负例（Q3）哪条泄漏 | **路径 2 泄漏**。无任何凭据的 loopback POST 自报 `member=felix` + `project/grant_epoch` 即可读到 jarvis-homehub 镜像内容；自报 `member=mom, role=owner` 可检索 mom 的个人 brain。路径 1/3 对 ly 全部 fail-closed（带一条 loopback box-context 保留意见，见 §3.4） |

## 1. 测试环境与身份获取

- Jetson `jetson-us-cf`（loopback 全部走机内 curl）：
  - 路径 1 入口 `companion-api :5120` → `_proxy` 转发 → `query_api :8787`
  - 路径 2 `knowledge-service :8790`（v3，2026-10-10 project-prefilter 补丁版，`KNOWLEDGE_PROJECT_BRAIN=1`，进程 23:59:32 起与磁盘文件一致）
  - 路径 3 `query_api :8787 /api/groups/{id}/search`（scoped_retrieval 群交集引擎）
  - project_knowledge brain 由 `gbrain-serve-project-knowledge :3142` 持有（serve_routes.json）
- 身份获取（零新增凭据，全部只读）：
  - felix Studio 会话 token：从 `~/.companion-api/data.db` tokens 表按 `device_name='Jarvis Studio'` 读既有 active token（仅在 ssh 管道内存中使用，未落盘）
  - `brain_grants` 现状（只读 sqlite）：`project_knowledge` 只授予 `member:felix`；**ly、mom、guest 均无** → Q3 越权身份选 ly（另测 guest、mom）
  - companion members：felix=owner，ly=member；ly **没有**任何 companion token
- source=jarvis-homehub 的三份事实基线：
  - `state/jarvis-homehub.json`：grant `g_1393b498`，ran_at 2026-10-11
  - 最新 mirror succeeded：grantEpoch **90**（sourceEpoch 3e5c171d…，2026-10-18T19:29Z）
  - query_api 请求时上下文 `access.grantEpoch="94"`（HomeHub 活跃 epoch，mirror 尚未跟上）

## 2. 三路径对比矩阵（同问同用户 felix）

| 维度 | 路径1 Studio `project.ask`/search | 路径2 语音 `brain.ask` | 路径3 群组 search |
|---|---|---|---|
| 入口端点 | `:5120 /api/studio/projects/{id}/ask` → `:8787 /api/projects/{id}/ask`；直连 `:8787 /api/knowledge/search` | `:8790 /query`（agent-runtime `knowledge.py::_knowledge_lookup` POST） | `:8787 /api/groups/{id}/search`（群内 agent.ask 的对端检索层；gateway `:8891 /ask` A2A 腿见 §5） |
| 身份来源 | **Header**：`Authorization: Bearer`（HomeHub 验证）；或 loopback `X-Agent-Member`（仅 loopback bind 生效）；无凭据 → 服务级 box 上下文 | **请求体**：`member`/`role` 全部自报，零验证 | **Header**：`X-Group-Context`（HomeHub 签发，严格校验）或 Bearer 绑定 member（`_bound_group_member`：错配 403）；loopback 无 Origin 的机器断言按 voice 同级信任 |
| 权限检查时机 | **检索前**：`scoped_items(context, projectId)` 先过滤再 `search_answer`；evidence gate 二次复核 | brain 级**检索前**（`get_accessible_brains` 先于搜索）；project_knowledge 块、跨成员医疗块**检索后**（`project_scope_filter`/`subject_scope_filter` 在 `multi_brain_search` 之后） | **检索前**：`scoped_retrieval` = 校验→成员→`intersect_views` 交集→`scoped_items`；答案后 `source_overlap` 兜底清擦 |
| 返回 evidence 结构 | 契约 KnowledgeEvidence：`schema_version/source_id/source_version/locator/content/permission_checked/retrieved_at` + 扩展 `index_as_of/freshness/fact_type/provider/model_id`（search 路径另有 `graph_version/node_ids/edge_ids`） | 裸块：`score/source(slug)/brain/text(≤600)`，无任何权限/版本/新鲜度/审计字段 | `answer/sources[{file,match|ts}]/confidence/index_as_of`，**无 evidence[] 无 citations[]**（代码注释：this tier answers without contract evidence records） |
| permission_checked | `true`（且只在真过 gate 的路径上出现；越权路径直接不产记录） | 不存在该概念 | 不存在该概念 |
| freshness | `fresh/stale/unknown`（48h 阈值，基于可证明 mtime）+ `index_as_of` | 无 | `sources[].ts` 时间戳（Q2 实测最诚实的新鲜度叙事）+ `index_as_of` |
| provider/model_id | `local` / `qwen3.5-route`（与实际合成模型一致） | 无 | 无 |
| graph refs | search 路径带 `node_ids/edge_ids/graph_version` | 无 | 无 |
| audit_ref | body `auditId` + 响应头 `X-UYP-Audit-Id` | **无任何 audit**（仅 latency_ms） | body `auditId` + `groupId/memberId` |
| 授权 scope 语义 | HomeHub AccessContext（projectScopes/sourceScopes，grantEpoch+过期） | brain_grants 表（brain 级）+ 请求体 project/epoch（project 级） | HomeHub group context ∩ 群注册视图（fail-closed 交集） |

## 3. Q1–Q3 逐路径结果

### Q1 "where is delegation signing implemented"（结构事实）

| 路径 | 结果 | 证据文件 |
|---|---|---|
| 1 ask | 正确答出 miku_bridge/delegation.py + delegation_sig.py + routes/delegations.py（HMAC-SHA256，10-10 审计的 "JWT" 幻觉已不复现）；6 条 evidence，confidence high，19.0s | p1-studio-ask-Q1.json |
| 1 search | 正确；3 evidence + 3 citations（AGENTFLOW 形状，`freshness:"current"`, `allowedToShare:false`, `producingJarvis:"yahboom-uyp"`）+ `access.grantEpoch=94`；9.0s | p1-search-Q1.json（含响应头） |
| 2 voice | **答不出**。10 块全是 municipal 新闻/日历噪声（0.81–0.86）；而 project serve 内该问的真实命中是 0.9031 —— 内容被检索到后被遮蔽（§4.2） | p2-voice-Q1-felix.json |
| 3 group | 正确答出 3 个文件，confidence high；无 evidence | p3-group-family-Q1Q2.json |

### Q2 "what changed in the homehub project recently"（freshness 敏感）

| 路径 | 结果 | 证据文件 |
|---|---|---|
| 1 ask | 诚实 miss（"I don't have enough information…"，evidence 空） | p1-studio-ask-Q2.json |
| 1 search | 从 harness_contracts 近期改动作答（medium），evidence `freshness:"fresh"`、`index_as_of=2026-10-18 21:41:46`、mtime 钉版 | p1-search-Q2.json |
| 2 voice | 纯噪声（卫星笔记/市政新闻/日历）；无任何新鲜度信号 | p2-voice-Q2-felix.json |
| 3 group | 诚实回答"未找到 homehub 变更叙事"，但 sources 带 `ts`（最新 22:46:28）——三路径中最好的 freshness 叙事 | p3-group-family-Q1Q2.json |

### Q3 越权（无 jarvis-homehub 权限的身份问同一问题）

越权身份基线：brain_grants 中 project_knowledge 仅 felix；companion 无 ly token。

| 路径 | 探针 | 结果 | 判定 | 证据文件 |
|---|---|---|---|---|
| 1 | `X-Agent-Member: ly`（loopback voice 层，search+ask） | **403 member_access_denied**（检索前拒绝，明确到人） | 过滤，不泄漏 | p1-Q3-negatives.json A/C |
| 1 | 伪造 Bearer | **503**（fail-closed，不回落 box 上下文） | 过滤 | p1-Q3-negatives.json B |
| 1 | 无凭据无头（loopback） | **200 + 全量内容**：落入服务级 box 上下文（felix/owner scope） | 见 §3.4 保留意见 | p1-Q3-negatives.json D |
| 2 | ly/member（真实身份） | brains=[family, personal_ly, public]，project_knowledge **未被搜索**，0 project 块 | brain 级过滤，不泄漏 | p2-Q3-ly-and-guest.json |
| 2 | guest/guest | brains=[public] | 过滤 | 同上 |
| 2 | **自报 member=felix+project/epoch（无凭据）** | **project_knowledge 内容返回**（delegation.py 页，0.9031） | **泄漏** | p2-sec-epoch68.json |
| 2 | 自报 member=mom role=owner（无凭据） | brains 含 **personal_mom**，返回 family/mom 内容 | **泄漏**（跨成员） | p2-sec-forged.json |
| 3 | ly（loopback 机器断言） | 200 + MISS_SENTENCE（"Not in the indexed projects."，sources 空）——membership 在 scoped_retrieval 内 fail-closed | 遮蔽为 miss，不泄漏 | p3-Q3-negatives.json a |
| 3 | Bearer felix + 伪造 member_id=ly | **403 member_mismatch** | 过滤 | p3-Q3-negatives.json b |
| 3 | 无凭据无 member_id | 200：绑定到 box 上下文 principal=felix | 见 §3.4 | p3-Q3-negatives.json c |

### 3.4 保留意见：:8787 的"无凭据 loopback = box 上下文"

`load_request_context` 分支 (c)：无 Bearer、无 X-Agent-Member 时回落**服务级 env/file 上下文**——本机部署配了 `UYP_HOMEHUB_ACCESS_CONTEXT_URL`+token 文件，于是任何 jetson 机内进程无凭据即可拿到 box（felix/owner）级 scope 的完整检索。这不是请求体信任（身份来自服务 env，不受调用方控制），且 :8787 只绑 loopback；但"无凭据 ≠ 拒绝"与路径 1/3 其余入口的 fail-closed 叙事不一致。归为加固项（§6-F）。

## 4. :8790 两个安全问题的行为取证

### 4.1 问题一：请求体身份信任 —— 证实（行为级）

代码：`handle_query` 直接 `member = body.get("member","guest")`、`role = body.get("role","guest")`，无任何凭据校验；`project`/`grant_epoch` 同样取自请求体。

行为证据（全部无 Authorization 头）：

1. **跨成员读取**：`{"member":"mom","role":"owner","question":"mom calendar and mom notes"}` → `brains_searched=[family, personal_mom, public]`，返回 `entities/mom`、family 日历等 mom 视角内容（latency 4871ms）。自报谁就是谁。
2. **冒充 felix 读项目知识**：`{"member":"felix","role":"member","project":"jarvis-homehub","grant_epoch":"68","question":Q1}` → 返回 `project_knowledge/jarvis-homehub/68/.../miku_bridge/delegation.py` 整页内容（score 0.9031，text 截 600 字符）。唯一"防线"是知道 project slug + epoch 编号——epoch 是 52..92 的两位递增整数，且镜像状态目录可读。
3. **role 自报同时绕过医疗隐私过滤**：`subject_scope_filter` 对 `role=="owner"` 直接原样返回全部块（owner 裁决 2026-09-29 的跨成员医疗遮蔽对自报 owner 无效）。行为演示不结论（当日查询未召回医疗块），代码路径明确（knowledge-service.py L376-377）。
4. 对照组：同样参数换成 `member=ly` → brains 不含 project_knowledge（grants 按 member 键控），0 project 块——说明 brain ACL 本身有效，问题纯粹在身份与 role 的可伪造性。

攻击面评估：:8790 绑 127.0.0.1，攻击者=jetson 机内任意进程/用户（含被攻陷的卫星链、其它服务的 SSRF、共享 loopback 的任何容器）。

### 4.2 问题二：检索后遮蔽 —— 证实（行为级）+ 侧信道评估

代码路径：`multi_brain_search` 对**每个** accessible brain 并发检索（含 project serve :3142）→ `_reserve_project_slots` 在排序层把 unscoped 请求的 project 块切掉 → `project_scope_filter` 在**响应前**再丢一次。

行为证据：

1. **同管线参数开关实验**（最硬的证据）：同一问题、同一 brains 集合，unscoped felix → 0 project 块；body 加 `project=jarvis-homehub&grant_epoch=68` → 同一 0.9031 块立即出现。块在两次运行中都被检索到，差异只在响应过滤——即"先全检索后遮蔽"。
2. **时延侧信道**：同问下 felix（4 brains，含 project serve）4822/10012ms vs ly（3 brains）2107ms vs guest 1959ms。project serve 腿给 felix 的每次语音查询多付 ~2.7–8s——换来的内容随后被丢弃。镜像高峰期该 serve 更慢（直连 probe 曾 30s 超时）。时延差异可区分"该用户是否有 project brain"。
3. **brains_searched 字段**：响应直接披露检索了哪些 brain（对自报身份者即 ACL oracle）。
4. **日志侧信道**：`log_message` 为 no-op，HTTP 无请求日志；journalctl（knowledge-service、gbrain-serve-project-knowledge）30 分钟窗口 0 条 query 记录；`knowledge-service.log` 仅一段补丁前旧二进制的 BrokenPipe traceback（行号与现文件不符）。**未发现内容经日志外泄**；侧信道=时延+brains_searched。
5. fail-closed 验证：epoch 89（错）与 90（对但未进 top-5）不可区分（都 0 块、无差异报错）——遮蔽不可当存在性 oracle，符合设计。

### 4.3 顺带发现：epoch 堆积 → 当前 epoch 饿死 + 旧内容永读

serve 内 top-20 命中的 epoch 分布：`{52,68,70,74,76,80,82,84,86,90,92}` 全在——**旧 epoch 从不清理**，同文件的历代副本同场竞技。后果（行为证实）：

- **freshness 违例**：今天 Q1 的最高分是 epoch 68（2026-10-17 00:10 发布）的 0.9031；
- **可用性**：scoped 到当前 published epoch 90 → 0 块（`search_brain` limit=5 被旧 epoch 占满，F1 slot 预留救不回"从未检索到"的块）——felix 的合法 scoped 语音读基本取不到当前内容；
- **安全**：历史上任何 epoch 永远可读（supersede 不删除，只有显式 revoke 才写墓碑）。

## 5. 路径 3 的 gateway 腿（代码取证，未发真实消息）

群内 agent.ask 全链 = gateway `:8891 /ask`（`ask_flow.ask_single_target` → `contracts_client.ask_via_contracts`，目标 URN 来自 Directory：felix.aurora、felix.miku、town 联系人等）+ NandaTown 群消息（query_api 侧 `poll_nandatown_groups` 收件）。A2A 发送会写任务/town 状态，属写操作，本轮只读回归未执行；对端的"scoped 群交集检索"正是本轮实测的 `/api/groups/{id}/search`（scoped_retrieval），其行为与矩阵 §2 一致。

## 6. 修复建议（只建议，未改任何生产代码）

**A. :8790 身份改凭据解析（问题一根因）**：`/query`、`/synthesize` 要求 `Authorization: Bearer`（companion token），member/role 由 HomeHub 解析（复用 query_api 的 `load_request_context` 三层模式：Bearer → 校验失败的 member → 无凭据拒绝）；请求体 member 仅作一致性提示，错配 403。过渡期最低限度：拒绝线上 `role=="owner"`（role 从 members 表推导）。

**B. project scope 不认请求体 epoch**：`grant_epoch` 改由服务端按解析出的 caller 查 grant ledger 得出（query_api AccessContext 模式），body 只允许缩小不允许定义授权。

**C. project 决策前移（问题二根因）**：无有效 project scope 的请求**不提交** project_knowledge 检索（跳过 future 而非过滤结果）——同时消掉 2.7–8s 无效时延与"先检索后遮蔽"。若保留 slot 预留，聚合计数记 masked-drop（不记内容）供观测。

**D. epoch 清理**：publisher 在新 epoch published 后删除旧 epoch 页（或 serve 查询按 scoped 前缀过滤），否则当前内容永远被旧内容遮蔽、旧 epoch 永远可读。

**E. 减少ACLE oracle**：`brains_searched` 改为数量或删除。

**F. :8787 服务级上下文收窄**：无凭据 loopback 请求不再回落 box 上下文（要求 X-Agent-Member 或 connector token；或把机内调用迁 unix socket + peer cred）。路径 3 的 loopback 机器断言（无 Origin 即可信 member_id）同属此信任家族，宜一并收敛。

**G. 跨路径证据语义统一（收口方向）**：路径 3 的 group search 接 evidence 生产者（其 allowed_items 已过 gate，`permission_checked=true` 是"挣来的"）；路径 2 若保留，至少给块补 `source_version + permission_checked + audit` 三字段，或明确文档化"语音层无证据契约"。

## 7. 回归测试

新增 `services/indexer/tests/test_cross_path_regression.py`（16 用例，离线 mock 三路径公共部分）：

- Scope 等价：同 view 下 Studio 层 `scoped_items` 与群组层 `scoped_retrieval` 召回完全一致；`*` 上下文被注册视图钳制；
- fail-closed 负例（对应今日真机 Q3）：非成员/过期/revoked/未知群/无上下文 → `[]`；
- 证据诚实性：越权引用不产记录（drop 而非 `permission_checked=false`）；群组层检索结果过同一生产者得到同一记录；
- 群组清擦：view 外/不可解析引用 `clean=false`；
- 语音形状分岔 tripwire：:8790 实测块形状不满足冻结契约（`KnowledgeEvidence.model_validate` 必须失败）——若 :8790 将来采纳契约，此测试即失效提示更新。

运行：`python3 -m unittest tests.test_cross_path_regression` → 16/16 OK。全仓 discover 528 例中仅 `test_mcp_server` 1 例失败——**预存在失败**（worktree 有未提交的 manifest_source_epoch 在途改动，该测试单跑亦败，与本轮无关）。另注：worktree 的未提交改动属于在途工作，本轮未触碰；部署机代码与 HEAD `a28cd03` 一致。

## 附录 A：证据文件清单（docs/evidence-crosspath-20261018/）

| 文件 | 内容 |
|---|---|
| p1-studio-ask-Q1/Q2.json(+.timing.txt) | 路径1 真 Studio 入口（:5120 project.ask）Q1/Q2 完整响应 |
| p1-search-Q1/Q2.json(+.timing.txt) | 路径1 :8787 /api/knowledge/search（Bearer，含响应头与 X-UYP-Audit-Id/X-UYP-Slow-Hint） |
| p1-Q3-negatives.json | 路径1 四负例（ly voice 层 / 伪造 Bearer / ly ask / 无凭据） |
| p2-voice-Q1/Q2-felix.json | 路径2 felix 合法语音查询（unscoped，被遮蔽） |
| p2-Q3-ly-and-guest.json | 路径2 ly/guest 负例 |
| p2-sec-forged.json | 路径2 越权取证：自报 mom/owner；自报 felix+epoch90/89 |
| p2-sec-epoch68.json | 路径2 越权取证：自报 felix+epoch68 **读出项目内容**；ly+同参数对照 |
| p2-sec-subjectfilter.json | 路径2 role 升格对照（当日未召回医疗块，不结论） |
| p3-group-family-Q1Q2.json | 路径3 family 群 Q1/Q2（Bearer felix） |
| p3-Q3-negatives.json | 路径3 三负例（ly 非成员 / 伪造 member_id / 无凭据） |

（全部文件已扫描，无 token 材料落盘。）
