# Celeste × DeepSeek 项目架构与开发步骤

> 目标：让 DeepSeek 大模型自主游玩《Celeste》（蔚蓝），从 1A 第一屏开始，逐步推进到整章通关。

---

## 0. 核心设计判断（先想清楚再动手）

| 判断 | 原因 | 结论 |
|---|---|---|
| LLM 不能逐帧操作 | Celeste 是 60fps 精密平台跳跃，冲刺/凌波微步容错仅数帧；DeepSeek API 延迟为秒级 | **分层架构**：LLM 做规划（~0.5–2Hz），本地执行器做帧级执行（60fps） |
| 状态获取走内存而非截图 | 截图 + 多模态识别慢、误差大；游戏内状态（坐标/速度/体力/冲刺次数）是精确值 | 用 **Everest Mod（C#）** 直接读游戏对象，JSON 输出 |
| 输入注入走虚拟手柄而非模拟键鼠 | 键鼠模拟无法精确到帧，且受系统焦点影响 | Mod 内挂接 Celeste 输入管线，注入帧级虚拟输入 |
| 动作抽象为「宏」 | LLM 不擅长也不必要输出逐帧指令 | 预定义参数化动作原语（walk/jump/dash/climb…），LLM 只编排宏序列 |

### 技术路线对比

- **路线 A：模组直连（推荐）** — Everest/MonoMod 加载 C# Mod，读写游戏状态。精度高、可帧级控制。
- **路线 B：纯视觉（备用/展示用）** — 截屏 → DeepSeek-VL → 键鼠模拟。无侵入但慢且不准，仅作 demo。

本项目采用 **路线 A + 分层智能体**。

---

## 1. 总体架构（三层 + 一个反馈环）

```
┌─ Celeste 游戏进程 ──────────────────────────────┐
│  Everest Mod (C#)                                │
│   ├─ 感知模块：读 Player/Level/Session → 状态快照 JSON │
│   ├─ 虚拟输入模块：帧级按键注入（挂 Input 管线）       │
│   └─ WebSocket 服务：localhost:8765 双向通道          │
└──────────────┬───────────────────▲───────────────┘
           状态快照@10Hz        宏指令@60fps执行
┌──────────────▼───────────────────┴───────────────┐
│  Python 编排层                                    │
│   ├─ 状态桥接：归一化、房间图、实体摘要              │
│   ├─ 宏执行器：动作原语库 + 帧时序回放               │
│   └─ DeepSeek 规划器：prompt 构建 → JSON 计划 → 校验  │
└──────────────┬───────────────────────────────────┘
┌──────────────▼───────────────────────────────────┐
│  记忆与评估                                       │
│   ├─ 运行日志 + SQLite（每次决策、每次死亡）         │
│   ├─ 死亡分析：死因分类 → few-shot 回灌 prompt     │
│   └─ 指标：过屏数 / 死亡数 / 决策耗时 / token 成本   │
└───────────────────────────────────────────────────┘
```

**数据流闭环**：感知 → 桥接 → DeepSeek 规划 → 宏执行 → 游戏反馈 → 记录/分析 → 改进 prompt。

---

## 2. 技术选型

| 层 | 技术 | 说明 |
|---|---|---|
| 游戏侧 | Celeste (Steam) + **Everest**（MonoMod 加载器） | 官方 mod 生态标准 |
| Mod 开发 | C# / .NET，参考 CelesteTAS 的输入注入实现 | Everest mod 模板 + WebSocket 服务 |
| 编排层 | Python 3.11+，`websockets`、`pydantic`、`openai` SDK | DeepSeek 兼容 OpenAI 接口 |
| LLM | `deepseek-chat`（快、便宜，主用）；`deepseek-reasoner`（卡关时深度推理） | `base_url=https://api.deepseek.com` |
| 存储 | SQLite + JSONL 日志 | 决策/死亡/回放全记录 |

### 状态快照 Schema（感知输出，示例）

```json
{
  "room": "1a_01", "chapter": "1A", "timestamp_ms": 123456,
  "player": {"x": 120.5, "y": 88.0, "vx": 0, "vy": 0,
             "dashes": 1, "stamina": 110, "on_ground": true,
             "dead": false, "facing": "right"},
  "entities": [{"type": "spike", "x": 160, "y": 96, "w": 8, "h": 8}],
  "solids_grid_hash": "abc123"
}
```

### 动作原语库（宏，LLM 可编排的最小单位）

| 原语 | 参数 | 帧级语义 |
|---|---|---|
| `walk` | dir, frames | 持续方向键 |
| `jump` | hold_frames | 起跳并按帧松开（控制跳高） |
| `dash` | 8 向, frames | 冲刺（含蹲冲） |
| `climb` | dir, frames | 爬墙 |
| `walljump` | dir | 蹬墙跳 |
| `wait` | frames | 等待（等移动平台等） |
| 组合宏 | 如 `dash_up_right_then_climb` | 预调校的多原语序列 |

宏参数精确到帧，由执行器本地回放，LLM 只负责「选哪个宏、传什么参」。

---

## 3. 目录结构

```
Celeste-Deepseekplay/
├── PROJECT_PLAN.md                ← 本文档
├── mod/                           # Everest C# Mod
│   └── CelesteDeepseekBridge/
│       ├── everest.yaml
│       ├── CelesteDeepseekBridgeModule.cs
│       ├── Perception/StateDumper.cs
│       ├── Input/VirtualController.cs
│       └── Net/WsServer.cs
├── agent/                         # Python 编排层
│   ├── bridge/    ws_client.py  state.py  room_graph.py
│   ├── planner/   deepseek_client.py  prompts.py  plan_schema.py
│   ├── executor/  macros.py  frame_runner.py
│   ├── memory/    db.py  death_analysis.py
│   └── eval/      metrics.py
├── configs/       default.yaml  deepseek.env
├── logs/          runs/*.jsonl  runs.sqlite
└── tests/         test_state.py  test_macros.py  test_planner.py
```

---

## 4. 分阶段开发步骤（P0–P6）

### P0 · 环境搭建（0.5–1 天）
- [ ] Steam 版 Celeste + 安装 Everest（Olympus 安装器最省事）
- [ ] 跑通 Everest Mod 模板：进入游戏输出一行日志
- [ ] 注册 DeepSeek API Key，Python 调通 `deepseek-chat` 一轮对话
- **过关标准**：Mod 能加载打日志；`python -c` 调 DeepSeek 返回正常。

### P1 · 感知层（1–2 天）
- [ ] Mod 内读 `Player` / `Level` / `Session`，序列化为状态 JSON
- [ ] 内嵌 WebSocket 服务，≥10Hz 推送快照
- [ ] Python 端接收并落盘 JSONL，画一条玩家轨迹验证数据正确
- **过关标准**：手玩 1A 第一屏，日志中的坐标轨迹与实际走位一致，无丢包。

### P2 · 输入注入（1–2 天）
- [ ] 参考 CelesteTAS 实现虚拟输入（挂 `Input` 更新钩子，喂入帧级按键）
- [ ] Python → WS → Mod 的宏指令通道，逐帧回放
- [ ] 手写一个固定宏序列：走出 1A 第一屏
- **过关标准**：脚本不联网、纯本地宏，稳定复现通过第一屏（10/10 次）。

### P3 · 执行器与宏库（2–3 天）
- [ ] 实现并单测 10+ 动作原语与组合宏（帧时序正确性）
- [ ] 死亡检测 + 失败后安全回退（回出生点、重置状态）
- [ ] 规则脚本（无 LLM）连过 1A 前 3–5 屏，验证宏表达力足够
- **过关标准**：纯规则脚本能过 1A 前 5 屏；每个宏有帧级单元测试。

### P4 · DeepSeek 规划器接入（2–4 天）
- [ ] Prompt 设计：房间状态摘要 + 可用宏清单 + 最近 3 次死亡教训 → 输出 JSON 计划
- [ ] 计划校验：pydantic schema + 宏白名单 + 参数边界检查，非法则重试
- [ ] 闭环：感知 → 规划 → 执行 → 结果回传，~1Hz 决策节拍
- **过关标准**：DeepSeek 在未见过的 1A 新房间内，5 次尝试内自主找到并通过至少 1 屏。

### P5 · 记忆与评估（2–3 天）
- [ ] SQLite 记录每次决策/死亡/重试；死亡自动分类（撞刺/摔死/力竭…）
- [ ] 死亡案例自动提炼为 few-shot 注入后续 prompt（自改进环）
- [ ] 指标报表：过屏数、死亡数、平均决策耗时、token 成本
- **过关标准**：同一房间第二次尝试的死亡数显著低于第一次；每轮 run 有完整复盘数据。

### P6 · 优化与扩展（持续）
- [ ] 卡关自动切换 `deepseek-reasoner` 深度推理；简单房间走规则缓存省 token
- [ ] 房间图记忆：已通过房间的宏序列直接复用，不再问 LLM
- [ ] 挑战整章 1A 通关，录制通关视频
- **过关标准**：1A 全章通关，产出可复盘的完整 run 数据 + 视频。

---

## 5. 关键风险与对策

| 风险 | 对策 |
|---|---|
| LLM 延迟导致错过时机 | 分层已解决：LLM 不碰帧级操作，时序全在宏执行器内 |
| LLM 输出幻觉/非法指令 | JSON schema 强校验 + 宏白名单 + 失败重试 ≤3 次后回退规则策略 |
| 死亡死循环烧 token | 死亡计数熔断：同房连死 N 次 → 切换 reasoner / 请求人工标注 |
| 宏表达力不够（某屏过不去） | P3 的规则脚本先行验证；不足则补充组合宏而非指望 LLM 微操 |
| 成本控制 | 默认 deepseek-chat；状态摘要做压缩；已通过房间走记忆复用 |

---

## 6. 里程碑 Checklist

- [ ] M1（P0–P2）：游戏可被程序「看见」且可被程序「操作」
- [ ] M2（P3）：规则脚本过 1A 前 5 屏
- [ ] M3（P4）：DeepSeek 自主过新房间
- [ ] M4（P5）：自改进闭环跑通，数据可复盘
- [ ] M5（P6）：1A 整章通关 + 视频
