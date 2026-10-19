# ADR：gBrain mirror 队列的 grant-epoch 失配处置

日期：2026-10-19（实证数据全部来自 jetson 只读查询/只读模拟，见 §6）
状态：待业主审批（本文档只写决策，不改生产）

## 0. 决策摘要

**采纳选项 A**：`homehub_grant_epoch_mismatch` 阻塞的镜像记录转为新的终态
`terminal_expired`（保留审计、永不再试）；当前 epoch 的新任务由既有 IndexJob→mirror
队列机制自然产生（已实证在运行）。**否决选项 B**（放宽为"记录 epoch ≤ 当前且 grant
未撤销即可重放"）：真实数据推演下它要么几乎放行不了任何记录（严格读法 6/930），要么
把 930 条记录全部重放进"当前读者永远看不见的 slug 子树"，其中包括 5 条产生于**真正
被撤销窗口**的记录——直接破坏撤权语义。

## 1. 现状机制（实证）

### 1.1 epoch 是全局单例计数器，create 和 revoke 都会推它

- HomeHub（jetson companion-api，:5120）`uyp_access.py`：`uyp_access_epoch` 表只有
  `singleton_id=1` 一行；`create_grant`（`_bump_epoch`）和 `revoke_grant` 各 +1。
  AccessContext 里的 `grantEpoch` 永远是这个**全局**值，不是单条 grant 的值。
- 项目 grant TTL 上限 24h；`uyp-grant-renewal`（user-systemd timer，~4min 一跑）在
  剩余寿命 < 12h 时执行 **revoke(reason=`scheduled_renewal`) → create**。
  3 个在保项目（jarvis-memory-live / jarvis-homehub / LingoQA）× 每约 12h 轮换一次
  × 每次 2 个 bump ≈ 全局 epoch 每天前进 ~12–14。实测：镜像记录里的 epoch 从 52 走到
  94 用了约 3.1 天（10-16 00:34Z → 10-19 02:40Z）。
- 任何其它 grant 活动（组设备委托撤权、identity 操作）同样推全局 epoch——即便目标
  项目的 grant 原封不动。

### 1.2 mirror 队列怎么被卡死

- IndexJob 发布本地版本后在 `~/dev/uyp/state/gbrain-mirrors/` 排一条元数据记录，
  钉住**入队时刻的全局 epoch**；`gbrain_mirror_worker`（user-systemd
  `uyp-gbrain-mirror.timer`，每 2min，`--max-jobs 1`）在写入前用新鲜 AccessContext
  做 `_mirror_access_denial()`：`record.grantEpoch != context.grantEpoch` →
  `blocked(homehub_grant_epoch_mismatch)`。
- `blocked` 是终态：`run_pending_mirrors` 只挑 `queued/retry_wait`，
  `run_mirror_job` 对 `succeeded/blocked` 直接返回。所以任何没在轮换窗口内（约 12h，
  实际还要抢过 queue_capacity/write_pending 的背压）排空的同日记录，第二天起永久
  僵死。

### 1.3 队列现状（2026-10-19T02:4xZ 实测）

| 相位 | 条数 | 说明 |
|---|---|---|
| succeeded | 809 | 同窗口内排空的（按记录 epoch 分布 52…92） |
| blocked | 953 | **930 条 `homehub_grant_epoch_mismatch`** + 23 条配置类（无 URL/creds 等） |
| failed | 268 | queue_capacity / write_pending / 超时，耗尽 maxAttempts |
| queued / retry_wait | 17 / 2 | epoch 94 的在途新任务 |

任务书里的 882 是早前快照；该数字单调增长（882 → 930），因为每天的新增未排空记录
次日都会转为 epoch-mismatch blocked。blocked 记录年龄 p50 1.57 天、最大 3.08 天。

### 1.4 930 条 blocked 记录的授权 grant 现状（HomeHub DB 只读回溯）

把每条记录的入队时间映射回当刻有效的授权 grant，查其终态：

| 授权 grant 结局 | 条数 | 含义 |
|---|---|---|
| revoked，reason=`scheduled_renewal` | 918 | 纯 TTL 轮亡，授权本身从未被政策性撤销 |
| **仍然有效** | 6 | 该项目 grant 没动过，纯粹被**其它项目**的 grant 操作推了全局 epoch |
| revoked，reason=`production_acceptance` | 5 | **真撤销窗口**（jarvis-memory-live epoch 52 时期的验收撤权） |
| 无法匹配 grant 行 | 1 | 边界记录 |

这张表是本 ADR 的核心事实：epoch 失配 ≠ 撤权。99.4%（924/930：918 轮换 + 6 仍在
期）的"失配"是轮换/跨项目噪声，但队列语义把它们和真撤权混在同一枚 `blocked` 里。

## 2. 两个选项的模拟推演（离线脚本对真实记录只读模拟）

### 选项 A：`terminal_expired`（+ 当前 epoch 自然建新任务）

- 930 条 → `terminal_expired`：审计链保留（记录文件、events、lastError 原样），
  队列工作集从 2049 降到 1119，`--status` 计数不再被僵尸淹没。
- "当前 epoch 创建新任务"**不需要新建机制**：最新记录已经是 epoch 94 排队中
  （jarvis-homehub `b3ce4777` @02:08:59Z、jarvis-memory-live `aba426bc` @02:45:24Z，
  均为 queued）。每次 IndexJob 增量发布都会用当刻 epoch 排新镜像任务。
- 内容无净损失：镜像粒度是 KnowledgeVersion（内容哈希）；旧版本的文件集合被最新
  版本覆盖，gBrain 侧只要最新版本排空即得到全量投影。真正要治的是**当天排空率**
  （268 条 failed 的 queue_capacity 背压），不是复活旧记录。
- 撤权语义：完全不变。epoch 不等 → 永不写入；真撤权窗口的 5 条记录同样终态化，
  它们的派生知识永远不进脑。

### 选项 B：放宽为"记录 epoch ≤ 当前 且 grant 未撤销即可重放"

两种读法、两种死法：

- **B-严格**（"该记录的授权 grant 本身未被撤销"）：930 条里只有 6 条通过——因为
  918 条的授权 grant 已被 scheduled_renewal 撤销、5 条被 production_acceptance
  撤销。B-严格 ≈ 什么都没解决，还引入了"撤销=轮换不分的反向混淆"。
- **B-宽松**（"该项目现在有有效 grant 即可重放"）：930/930 全部放行，但：
  1. **930/930 全部写进读者永远看不见的子树。** slug 是
     `project_knowledge/<project>/<记录epoch>/<relpath>`，读侧
     `project_scope_filter`/`_scoped_project_block` 要求请求携带的 `grant_epoch`
     与 slug 里的 epoch **精确相等**才放行（fail-closed）。读者只会拿当前 epoch
     （94+）发请求，旧 epoch 子树全部被过滤。B-宽松 = 写 930 个死页面 + 占用
     queue_capacity + 烧 writer 配额，阅读价值为零。
  2. **撤权语义被实质破坏**：5 条 `production_acceptance` 真撤销窗口的记录（及其
     所代表的整类未来场景——业主政策性撤销后重新授权）会在"grant 现在有效"的
     判定下重放进脑。虽然落点是旧 epoch 子树（暂时读不到），但它们从此躺在
     gBrain 里，任何携带旧 epoch 参数的请求、或未来任何放宽读侧 epoch 匹配的
     改动，都会让**已撤销时期的派生知识**变得可读。撤权的审计承诺（"revoked
     epoch 的内容不再入脑"）被打破且不可逆（远端删除需要显式 revoke 操作，
     而没人会为 B 误写的页面逐一补 revoke）。
  3. 若再补一刀"重放时把 slug 重打到当前 epoch"（B-变体），那是把旧授权时期的
     内容直接塞进当前授权名下——撤权语义破坏得更直白，明确不做。

**结论**：B 在两种读法下要么无效（6/930）要么有害（930 个不可读页面 + 5 条真撤权
窗口内容入脑）。A 以零语义代价换取队列可运维性，且新任务路径已在跑。

## 3. 推荐

采纳 **A**，并附两个非目标声明：

- 不改 `_mirror_access_denial` 的判据本身（epoch 不等仍拒绝）；只是把这类拒绝从
  `blocked`（语义含糊、和真问题混住）改名为 `terminal_expired`（明确：轮换失配、
  预期内、不可重试）。
- `homehub_scope_denied` / `homehub_source_scope_denied` / `grant_epoch_missing`
  **保持 `blocked`**：它们是真实政策信号（作用域被收窄/从未授权），需要操作员看，
  不能被批量终态化淹没。

## 4. 实施清单（审批后执行；本次未动任何生产代码）

1. **改 `services/indexer/src/gbrain_publisher.py`**（jetson 生产路径
   `~/dev/uyp/indexer/gbrain_publisher.py` 同步）：
   - `MIRROR_PHASES` 增加 `"terminal_expired"`（~L103）。
   - `run_mirror_job` 的终态早退集合 `{"succeeded","blocked"}` 加入
     `terminal_expired`（~L775）。
   - `_mirror_access_denial` 的调用点（`run_mirror_job` ~L780 与
     `run_pending_mirrors` ~L874）：denial == `homehub_grant_epoch_mismatch` 时
     `store.event(id, "terminal_expired", {"lastError": …, "blockedBy": "homehub",
     "expiredBy": "grant_epoch_rotation"})`；其余 denial 维持 `blocked`。
   - `mirror_projection`/`queue_status` 无需结构改动（按 phase 计数自动带上新态）。
2. **存量清洗（一次性、幂等）**：小脚本扫 `gbrain-mirrors/*.json`，把
   `phase=="blocked" && lastError=="homehub_grant_epoch_mismatch"` 的 930 条改标
   `terminal_expired`（保留 lastError/events 原文，append 一条 event 说明迁移）。
   先 `--status` 留档前后计数。
3. **测试**：`services/indexer/tests/test_gbrain_publisher.py`
   `test_mirror_worker_blocks_after_homehub_grant_epoch_changes`（L287，现断言
   `blocked`）改为断言 `terminal_expired`；新增：scope-denied 仍为 `blocked`、
   `terminal_expired` 不再被 run_pending 选中、迁移脚本幂等。
4. **重启**：不需要。worker 是 user-systemd timer 每 2min 的 oneshot，下一次 tick
   自动加载新代码；正在跑的 pass 自然退出。companion-api/HomeHub 零改动。
5. **验收标准**：
   - `--status` 中 epoch-mismatch 记录全部呈现为 `terminal_expired`，总数与迁移前
     blocked 数一致（930，允许 thereafter 增长——新轮换产生的也会即时终态化）；
   - `queued/retry_wait` 记录（当前 epoch）在 2min tick 内正常 consumed；
   - `succeeded` 809 条与 HomeHub 审计链无任何变化（终端化是纯本地状态迁移）；
   - 单元测试全绿。
6. **后续观察项（不在本 ADR 范围）**：
   - 当天排空率：268 条 failed 的 queue_capacity/write_pending 背压才是镜像覆盖
     率的真瓶颈；
   - 已入脑的 809 条旧 epoch 页面对当前读者同样不可见（对称问题），如需清理走
     显式 `gbrain_publisher.py revoke`，不要顺手做。

## 5. 风险与边界

- `terminal_expired` 是本地队列状态，不触碰远端 gBrain、不触碰 HomeHub；
- 若未来 HomeHub 把 grant epoch 改成 per-grant 单调（消除跨项目串扰），本决策依然
  成立——轮换失配仍会 daily 发生，只是量变小；
- 若未来想让 gBrain 保留"历史版本投影"，正确路径是让 publisher 在**当前 epoch**
  下重发最新版本（等价于 A 的新任务路径），而不是放宽旧记录校验。

## 6. 证据与可复现

- 队列统计与 grant 回溯：jetson `/tmp/uyp_sim_epoch.py`（只读：queue JSON +
  `sqlite3 file:~/.companion-api/data.db?mode=ro` 查 `uyp_grants`/`uyp_access_epoch`）；
- 队列计数：`python3 ~/dev/uyp/indexer/gbrain_mirror_worker.py --state-root
  ~/dev/uyp/state --status`；
- 关键代码锚点：`uyp_access.py` `_epoch`/`_bump_epoch`（singleton 行）、
  `uyp_grant_renewal.py`（revoke+create 轮换）、`gbrain_publisher.py`
  `_mirror_access_denial` L739 / `run_mirror_job` L775 / `run_pending_mirrors` L864；
- 读侧 epoch 精确匹配：`patches/knowledge-service-project-prefilter.patch`
  （`_scoped_project_block`：`parts[2] != epoch` 即排除，fail-closed）。
