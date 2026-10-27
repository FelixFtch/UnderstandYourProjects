# Pi 原生家庭 App：已批准方向与本仓库迁移边界

日期：2026-10-27。状态：**用户已批准，进入实施；尚未部署**。

本页取代旧 UYP 目标文档对本轮工作的方向约束，保留历史实现及验收证据。
完整目标只有一个权威版本，位于 HomeHub 仓库：

- [完整架构](https://github.com/FelixFtch/jarvis-homehub/blob/codex/pi-native-app-foundation/docs/plan/PI_NATIVE_HOME_ARCHITECTURE_V1.md)
- [执行计划](https://github.com/FelixFtch/jarvis-homehub/blob/codex/pi-native-app-foundation/docs/plan/PI_NATIVE_HOME_EXECUTION_PLAN.md)
- 本机对应目录：`/Users/felixfang/projects/jarvis-homehub/docs/plan/`。

## 已冻结的产品链路

```text
原生 iPhone / macOS Jarvis App
                 │
           HomeHub 身份与 API
       ┌─────────┼──────────┐
   数据/媒体读取   OpenClaw    显式按钮
                 │           │
          gBrain / 受控工具    │
                 └─────┬─────┘
               HomeHub Policy / Command / Receipt
                       │
                单一设备执行器 → read-back
```

HomeHub 唯一负责身份、设备归属、授权、撤销、审计与执行回执；OpenClaw
唯一负责对话运行和实际定时调度；gBrain 唯一负责长期知识、确认记忆与检索。
普通数据读取不经过模型。Agent、按钮、定时任务共用同一副作用边界。
每个设备只有一个写入执行器；不把原来的 Agent、Langflow、Hermes、
全局 RAG Router 再叠加到 OpenClaw 后面。

HA Pi 5 负责协议、采集与媒体转发；Pi500 负责家庭核心、索引、历史与
NVMe 录像。Mac 与 iPhone 是原生客户端。4090 是可选共享推理服务，
不得重复加载同一模型权重。Qwen API 与 Pi 本地模型可替换，云端切换须
显式配置。远程目标是一个 VPS 的 HTTPS/WireGuard/TURN 链路；该资源
尚未部署，Cloudflare 并不给 Pi500 特殊中心身份。

## 本仓库资产如何处理

| 资产 | 目标用途 | 本轮动作 |
|---|---|---|
| Studio 隐私、事件、证据、群组、图表语义 | 迁入原生 App 的领域模型与交互 | 保留源码作为参考；不把整个网页再嵌套成永久产品 |
| Mac Connector 的源授权、manifest、变更与读取 | 原生 macOS App 内受限 helper | 后续逐接口迁移；不新增独立安装入口 |
| gBrain 检索与证据 | 家庭知识工具内部检索 | 保留来源、版本、授权、新鲜度、撤销传播 |
| UA 分析循环、项目图谱、全局语义路由 | 不进入新 Pi 产品主链 | 历史源码暂留；本轮不新增依赖，也不直接删掉运行数据 |
| NandaTown | 可选的 external_agent.ask 传输 | 不成为权限来源或家庭调度器 |
| Jetson / XVF3800 | 现有独立现场 | 本轮不连接变更、不部署、不调整语音 |

原始文件仍在授权源上；gBrain 保存受限索引和证据，不能默认复制整个
私密文件夹。撤销必须影响后续检索与缓存。视频、文件、指标、总结和
日程最终汇入同一 App；新媒体能力属于 Pi 产品，不修改旧 Jetson MVP。

## 实施顺序与责任

1. P0：记录批准架构、职责和冲突文档的替代关系。
2. P1：共享 Swift 核心、原生 macOS 入口、iOS 同一鉴权链、真实空状态。
3. P2：新鲜在线设备、实时视频、录像回看、参数历史与证据关联。
4. P3：OpenClaw 对话、澄清、审批、取消、后台任务和三种模型配置。
5. P4：家庭/个人日程、提醒与主动总结，唯一调度器和去重。
6. P5：逐设备切换唯一执行器，现场验证后退掉对应 HA 依赖。

Integrator 负责整合及所有现场变更；并行工作限已分配代码与文档。
本轮从 P1 的连接与真实状态切片开始；不是把所有阶段标记完成。

## 不可跳过的验收

双端读到同一家庭及配置；未连接/空数据/失败/陈旧明确区分。视频须在
真实 App 上验证局域网与远程播放、seek、时间轴和缺口，不能以服务存在
或 ffprobe 成功替代。动作须查 policy、command、receipt、read-back；
取消对话不代表撤回已执行设备动作。定时任务、重连、重启不得造成重复
副作用。传感器未在线和媒体没有新帧的设备不迁移。

P1 代码测试和构建证据记录在 HomeHub 执行计划；旧报告仅用于历史参考。
生产完成必须有部署元数据、真实入口和设备证据，不能从文档推断。
