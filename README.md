# DeepSeek 玩 Celeste

让大模型在《蔚蓝》（Celeste）里实际操作的实验项目。它不靠截屏识别像素，而是通过一个 Everest Mod 把游戏的**真实状态**读出来——亚像素坐标、碰撞矩形、实体、房间出口——再把**帧级输入**写回去。

目前已实机通关教学地图的 **6b**、**6c**、**7** 三个房间，当前停在房间 **8**。

```
┌──────────────────────────────┐
│  DeepSeek / Codex  （1 Hz）  │  看状态 → 出多帧动作计划
└──────────────┬───────────────┘
               │ JSON 计划
┌──────────────▼───────────────┐
│  Python Agent（本地）        │  schema 校验 / 防漂移 / 技能回放
└──────────────┬───────────────┘
               │ JSON-Line over TCP 127.0.0.1:32123
┌──────────────▼───────────────┐
│  CelesteAgentBridge（C#）    │  读状态 · 写按键 · 存档 · 截图
└──────────────┬───────────────┘
               │
        Celeste + Everest（60 fps）
```

核心判断是**分层**：大模型不适合逐帧操作，它的价值在于看到几何后用推理挑路线；真正的手感必须交给 60 fps 的本地执行器。所以本项目的实际形态是「LLM 出宏 / 本地跑宏 / 探针测量」，而不是「让模型一直按方向键」。

---

## 当前进度

| 项目 | 状态 |
| --- | --- |
| 桥接 Mod | `0.3.4`，实机加载，信息层 9 类探针全部通过；新增逐帧 `expect` 与位置回传 |
| 已通关房间 | 6b（→6c）、6c（→7）、7（→8），路线已固化为可复现宏 |
| LLM 闭环 | 已验证「规划→校验→执行→观测」单步与三步闭环（Codex 模式，落点均命中预测区间） |
| 双 Agent 协同 | `--collab` 实机验证：4 步零暂停、`rejected=0`；不稳定世界两条分支均按预期收敛 |
| 路线书 | `logs/routes.json` 跨会话存活；房间 7 三段宏随仓库带一份 `agent/agents/seed-routes.json`；实测从磁盘读回后重放 `latency 0.0`，模型零调用 |
| 逐帧预期 | 桥接在应用按键的那一帧比对预期位置，超差立即停并回报帧号；重放不再靠"整段发完再看落点" |
| 本地重算 | 失手后先在本站位附近换一条已验证路线，预算内不唤醒模型（`local_retries`） |
| 知识注入 | 移动常数常驻，机制说明按房间实体类型挑选（尖刺/弹簧/碎台…） |
| 测试 | `133 passed`，ruff clean |
| 未完成 | LLM 尚未自主通关整章；6b/6c/7 的路线是人机协作推出的宏，不是模型自己想的 |

**6b 通关**：房间 `Celeste/1-ForsakenCity`，终点 `6c` (2332,-1304)
**6c 通关**：竖井房间，终点房间 `7` (2600,-1465)
**7 通关**：两块落块与顶部竖井，终点房间 `8` (2719,-1704)

---

## 环境

Python **3.12**（3.13 下 `pydantic_core` 会报 `ArgsKwargs` 导入错误）。依赖 `pydantic` 与 `openai` SDK。

```shell
pip install -e ".[dev]"
# 或使用仓库内 vendored 依赖
PYTHONPATH=".deps;." python -m pytest -q
```

游戏侧需要已安装 **Everest**；`SpeedrunTool` 与 `CelesteTAS` 是可选依赖，存档/读档与 TAS 回放要用到。

### 编译并安装桥接

```powershell
$env:CELESTE_DIR = 'F:\steam\steamapps\common\Celeste'
./scripts/build_bridge.ps1
# 等价于：
dotnet build bridge/CelesteAgentBridge -c Release -p:CelesteDir=$env:CELESTE_DIR
```

把 `bin/Release/net8.0/CelesteAgentBridge.dll` 和 `everest.yaml` 复制到
`Celeste/Mods/CelesteAgentBridge/`，然后**完全退出游戏再启动**。

> .NET 程序集只在进程启动时加载一次，退回主菜单不算。改完 Mod 不重启，游戏里跑的还是旧版本。

## 信息层

桥接的价值一半在读。以下探针全部只读，游戏运行中可随时调用：

```shell
python -m agent.inspect --what all --json            # 一次拉全
python -m agent.inspect --what player --internals    # 亚像素位置、命名状态、计时器、原始字段
python -m agent.inspect --what level                 # 章节、房间、tick、死亡数、冻结帧、风力、对话
python -m agent.inspect --what room                  # 四向邻接房间、出生点、触发区、过门坐标
python -m agent.inspect --what entities --fields     # 实体固定 ID、分类、碰撞箱、专有属性
python -m agent.inspect --what collision             # 实心地形矩形 + 所有可碰撞对象
python -m agent.inspect --what tiles                 # ASCII 字符地图，一格 8×8 像素
python -m agent.inspect --what menu,save             # 菜单结构、存档槽、章节进度
python -m agent.inspect --what capture --kind gameplay   # 离屏渲染 PNG（gameplay 320×180 / level 全窗）
```

`agent.room_map` 把地图、坐标标尺、对象包围盒和出口拼成一张可读的图，是回答「出口在哪」最快的方式：

```shell
python -m agent.room_map --objects
```

几个实现上的坑，踩过才知道：

- **地形不能读 tile 字符数组。** 那个数组按每关卡自己的坐标系索引，越界时静默返回 `'0'` 而不抛异常，于是满屋实心块的房间看起来是空的。现在地形从引擎真正参与碰撞的 `SolidTiles` 碰撞体栅格化而来，`coverage.source` 会标明走的哪条路。
- **`SolidTiles` 是 `Grid`**，逐格展开会有两万多个 8×8 矩形把调用方预算撑爆。现在按房间裁剪并贪心合并，6b 从 1440 格压到 41 个矩形。
- **`get_collision` 的 `complete` 是可信的**：地形或对象被截断时它返回 `false`，不会把「取到一半」伪装成「空房间」。
- **截图是两阶段的**（`capture` → `capture_result`），像素只能在渲染末尾读。
- **`trajectory_start` / `trajectory_stop`** 按 update tick 逐帧记录一行，用于校准物理常数。

---

## 操作与测量工具

这几个脚本是项目里真正干活的部分。它们的共同前提：**死亡会原地重生，试错比规划便宜**。

### `agent.step` — 分段执行器

一次调一段，跑完打印她在哪。支持等待条件，因为很多操作必须卡在正确的时机：

```shell
python -m agent.step --actions "right:24;right,jump:26" --trace
python -m agent.step --wait-mover-x-ge 0:2156 --wait-lift 8 --actions "jump:8;right,dash:9;right:3"
python -m agent.step --wait-mover-y-le 1:-1206 --actions "right,dash:10;right:8"
```

| 选项 | 作用 |
| --- | --- |
| `--wait-mover-x-ge/-le`、`--wait-mover-y-ge/-le` | 等某个移动平台到达指定坐标 |
| `--wait-lift` | 等 `lift_speed` 衰减到阈值以下（离开移动平台起跳时必须） |
| `--stable N` | 等第 N 个平台停稳 |
| `--trace` | 逐帧打印坐标/速度/状态 |

### `agent.sweep` — 候选批量对拍

从同一个 savestate 出发，用 `restore_and_execute` 跑多个候选动作序列，输出峰值高度、最远 x、落点。6c 一共试了 40 多个候选，手工比对是不现实的。

```shell
python -m agent.sweep --save \
  --actions "right:24;right,jump:21;right:15;right,dash:10;right:6;left:4;right:30" \
  --actions "right:24;right,jump:21;right:16;right,dash:10;right:45"
```

### 其他

| 工具 | 用途 |
| --- | --- |
| `agent.trace_run` | 带前置条件（`--pre`、`--wait-mover`）的逐帧轨迹探测 |
| `agent.replay` | 重放并比较多次执行的位置/速度偏差（确定性审计） |
| `agent.tas_play` | 按 `#lvl_<room>` 分节回放 `.tas` 文件 |
| `agent.restore_probe` | 存档/恢复的探针封装 |

---

## 已通关路线

完整记录在 `data/routes/6b.md`、`data/routes/6c.md` 和 `data/routes/7.md`，包含几何、失败方案和实测常数。

### 6b — 两块 ZipMover 与一道檐板

```
1) right:24 ; right,jump:26                      跳上 ZipMover#0
2) 等 mover0.x≥2156、lift_speed≤8，然后
   jump:8 ; right,dash:9 ; right:3               直跳 + 右冲越过尖刺，落 ZipMover#1
3) jump:14 ; up,dash:10 ; right:24               跳+上冲够到 -1264 平台
4) jump:12 ; up,right,dash:10 ; right:22          对角冲翻过檐板，登顶 -1304
5) right:14                                      切房间到 6c
```

三个关键发现：

- **ZipMover 不动，踩上去才动。** 盯了 350 帧零位移——所以第一跳完全不需要卡时机，比预想的简单。
- **跳离移动平台会继承载体速度。** 她自身 `speed.x=0`，但 `lift_speed.x=201`，起跳首帧就变 `vx=257.6`，三帧后一头撞进尖刺。必须等它衰减。
- **竖直那块两端都是墙。** 低位撞 x≈2272 的墙面，高位撞 2232 处头顶檐板；普通跳（27px）两头都过不去。唯一解是**跳 + 上冲刺**（27+36=63px）从头顶翻出去，再用对角冲刺横跨到出口平台。

### 6c — 两个弹簧与一次顶点冲刺

```
1) right:24 ; right,jump:21                       跳上弹簧①
2) right:15 ; right,dash:10 ; right:6 ; left:4    右冲 + 六帧刹车，落弹簧②右半
   right:30                                       （卡在 x2492，容错 6px）
3) 弹跳顶点 → up,right,dash:10 ; right:60          上 -1392 台阶
4) right,jump:22 ; right:16                       上 -1416 平台
5) jump:8 ; up,dash:10                            穿过顶部 16px 洞口 → 房间 7
```

四个测出来的数据：

1. **弹簧只给 52px，不是 78px。** `vy=-185` 从 -1318 弹起，顶点 -1370，反复弹跳只循环不加高。
2. **水平冲刺会把 vy 清零。** 所以冲刺是弹簧高度的**替代**而非叠加——早期所有尝试都因此矮了 20~30px。
3. **`Player.Position` 是碰撞箱的底部中心**，不是左下角。之前所有看着「还剩 4px」的判定，实际余量是 0。
4. **2408 那根柱子是上下双向尖刺**，中间只有 31px 通道，柱子下面封死。

第 2 段只有 **6px 窗口**：早一帧（14）落在 x2481 被弹簧②上方的下垂尖刺挡住，晚一帧（16）飞过弹簧掉进深坑。第 3 段不能数帧，只能实时轮询 `vy` 过零——弹跳周期约 52 帧且稳定。

### 7 — 两块落块与一次弹墙

```
1) right,jump:16 ; right:24 ; right,jump:20        上落块 e2（2697,-1512）
2) right:6 ; right,jump:20 ; up,dash:10            跳到块右侧、上冲、弹墙，
   left,jump:10 ; left:4 ; left,jump:8             折返落在 e3 顶面（2738,-1592）
3) left:6 ; jump:20 ; right:6 ; right,jump:8       竖井内左右交替蹬墙，
   left:6 ; left,jump:10 ; right:12 ; right,jump:10 穿过顶部出口 → 房间 8
```

这一关把「跳 32px」这个常识推翻了：

1. **跳跃只有 27px，不是 32px。** `varJump` 把 `vy` 钳在 -105 整整十一帧，从 -1512 起跳最高只到 -1539。`e2` 到 `e3` 的 80px 无法一次跳上去。
2. **上冲刺只加 42px。** 十帧 `vy=-240` 然后减半，跳 + 冲刺合计 69px，仍差 11px。
3. **`e3` 的底面是天花板。** 从正下方向上冲，头顶在 -1560 撞停，`vy` 归零，人往右滑出去。
4. **竖井左半边被封死。** `e3` 占 2720..2736，`e6` 尖刺贴住 2717..2720，8px 宽的人只剩 5px 可过。唯一通道是 `e3` **右侧**的 2736..2776。
5. **冲刺结束贴墙时的下一跳会变成弹墙**（`vx=170, vy=-160`）——这是唯一够到 `e3` 顶面的动作，顶点 -1601，比块顶高 9px。

弹墙的代价是它把人甩到 x2754，而块顶只到 2736。`left:4` 先刹住水平速度，`left,jump:8` 再从同一面墙蹬回来——两步合起来才让落点收到 2738。没有刹车，弹墙留下的是一个悬在空处的 x2764，前面十来个变体都是这样掉出房间的。

第 3 段是 24px 竖井里的四次交替蹬墙，每次要留约 12 帧横移才能摸到对面墙——`right:12` 和 `left:6..8` 是跨越时间，不是余量。

---

## LLM 规划器

```powershell
# 模拟桥接（离线，不需要游戏）
python -m agent.main --mode deepseek --steps 1

# 真实游戏
$env:DEEPSEEK_API_KEY = '...'
python -m agent.main --real --mode deepseek --settle --exit-room 6b --success-room 6c --steps 12
```

可选环境变量：`DEEPSEEK_MODEL`（默认 `deepseek-chat`）、`DEEPSEEK_BASE_URL`（默认 `https://api.deepseek.com`）。也支持 `--mode codex`（复用 ChatGPT 登录，不消耗 API key）和 `--mode gpt`。

规划器收到的不只是坐标，还有逐帧物理参考（`agent/knowledge.py`，从 `kb/speedrun/` 蒸馏、与反编译代码核对过）、按房间检索的知识库原文（`agent/kb.py`，见「长尾检索」）、平台采样、房间几何、可选 TAS 动作提示，以及已验证技能。

### 双 Agent 协同（`--collab`）

单循环版本的三道闸（`--settle` / `--pause-planning` / stale 前置）都是同一个循环里的手工补救：模型思考期间世界照跑，规划用的快照注定追不上，只能靠冻结或事后拒绝兜底。`--collab` 换成另一种承诺：**只在世界确实静止时才让规划器看世界**。

- 执行器独占桥接；规划器是独立 task，只收数据（状态、房间几何、平台采样、上一步结局），拿不到 client，也不需要等锁。
- 只有**着地且连续两次采样都没位移**（`still_for`，默认 0.15 s）才发布锚点。空中是 `SETTLING`，死亡/失控是 `BLOCKED`，两者都不发布。
- 计划绑定它据以推理的锚点 id。计划到达时若锚点已不是当前锚点，**一帧不发直接丢弃**——不是"发出去再拒绝"，而是根本没发生过。
- 待命期间**不按键、不暂停**。`stop` 之后 mod 已经把输入交还，静止的 Madeline 本身就是"世界不动"。这就是落地不再冻结游戏的原因：等待期间游戏照常运行，只是没人按键。

| 事件 | 含义 |
| --- | --- |
| `ANCHOR` | 发布锚点，附 `still_for` |
| `SUPERSEDED` | 计划绑定的锚点已过期，丢弃 |
| `ANCHOR_LOST` | 等计划期间世界动了（平台带走 / 冰面 / 有人按键），重新锚定 |
| `STALE_PLAN` | 不该出现：锚点承诺被打破，执行器拒绝了已发出的计划 |
| `FREEZE` | 世界迟迟不静止，退化为暂停（仅 `--on-unstable freeze`） |
| `SESSION` | 收尾统计，`rejected` 就是 STALE_PLAN 计数，目标是 0 |

```powershell
python -m agent.main --real --mode deepseek --collab --exit-room 6b --success-room 6c --steps 12
```

世界一直不静止（比如站在移动平台上）时两种处理：`--on-unstable wait`（默认，等满 `--anchor-timeout` 秒后放弃，全程不冻结）或 `--on-unstable freeze`（退化成暂停一次模型调用，给移动平台房间用，代价是那几秒画面是冻的）。`--think-timeout` 约束单次模型调用，`--max-retries` 约束连续未落地次数。

单循环路径（不带 `--collab`）保留原有的 `--settle`、`--pause-planning` 和 stale 前置；`--collab` 与 `--pause-planning` 互斥。

### 路线重放

模型最贵也最不可靠的地方是**即兴**：一个没走过的房间，它只能猜。而「从这里、这套按键、落回那里」已经在同一台机器上跑通过一次，那句承诺比任何提示词都强。所以每次落地都会留下一条路线：起点、动作、落点。

下一个锚点如果**正好站在某条路线的起点上**（同房间、着地、冲刺数够、两轴都在 2px 内），就直接重放，不问模型——零延迟、零漂移，同一个问题不会有第二个答案。

```
step1  LANDED  latency 1.0   hop in place
step2  LANDED  latency 0.0   replay learned-1
step3  LANDED  latency 0.0   replay learned-1
model calls 1  replays 2  routes 1
```

这是房间 7 的实机输出：模型只回答了一次，后两步是重放。匹配容差故意卡在 2px——路线是对物理的承诺，放宽就等于在一条已经不合适的檐板上重放旧弧线。

路线有两个来源。`--skills` 从技能库读进来的是**回放验证过**的（`verified_start`/`verified_end` + 成功次数），可以直接重放；本局内新学的是「落地过一次」，证据更弱，所以**连续失手两次就退出轮换**，不会第三次还硬放。命中与失手都记在 `SkillBook` 里，`--no-replay` 可以整体关掉、退回纯模型规划。

书现在**跨进程存活**：一个房间清过一次，模型就不该再被问第二次。会话结束时 `SkillBook` 原子落盘到 `logs/routes.json`（临时文件 + 替换，跑到一半被杀不会把书截断），下次启动直接读回来——起点、按键、落点，连同命中/失手次数。

```
step1  LANDED  replay verify-live  latency 0.0  settled [2719.0, -1704.0]
session {"anchors": 1, "steps": 1, "landed": 1, "planner_replays": 1,
         "routes": 1, "routes_book": "learned", "routes_dropped": 0}
```

这是从磁盘读回来的路线被重放：`latency 0.0` 说明模型没被调用，落点与记录一致，落盘后该条 `hits` 由 1 变 2——结账时最后一步的结局也被收了进去。

随仓库带一份 `agent/agents/seed-routes.json`：房间 7 的三段宏，坐标抄自 `data/routes/7.md` 的实机通关记录（起点 `(2600,-1480)` 上 spawn，经 `e2 (2697,-1512)`、`e3 (2738,-1592)` 出到房间 8）。它只在 `logs/routes.json` 还不存在时作为起点读入，**不是第二本书**：一旦本机保存过，就以本机的书为准——合并会把已经降级的路线重新复活。`--route-book PATH` 换路径，`--no-route-book` 退回纯内存、不落盘。

读不动的行只损失那一条路线，不会让整本书报废：解析失败的行计数后跳过（`routes_dropped`），已经降级的路线（`streak` 到上限）加载时也不回轮换。

重放的计划仍然走完整契约：前置钉在锚点上，成功带是「上次落点 ±6px」，超时是「本条动作帧数 + slack」。落点偏出带就是 `MISSED`——不是要藏起来的事故，而是降级该路线的依据。

配套的还有结局回执的加厚：`StepReport` 现在自带 `actions`，规划器拿到的不再只是「成了/没成」，而是 `status`（`ABORTED` 还是 `UNSATISFIED`）、`reason`（`timeout`/`stalled`/`x_out_of_band`）、`at_frame`（第几帧断的）、以及一条抽稀到 6 个点的轨迹。这三者指向完全不同的下一个计划：`ABORTED` 是世界在计划执行期间变了，`UNSATISFIED` 是计划本身判断错了。

#### 逐帧预期：路线从"终点承诺"变成"轨迹承诺"

重放原来的判据只有落点：整段发完、等她落地、看 x 在不在 ±6px 里。问题是**发完就晚了**——一条 40 帧的宏在第 12 帧就已经偏离，剩下 28 帧是开进尖刺的，而回执要等到最后才说"没落回原处"。

桥接 0.3.4 把比对挪进了应用按键的那一帧：

- `execute_frames` 接受 `expect`（每帧一个 `[x, y]`，`null` 表示这一帧不查）和 `tolerance`（默认 1px，上限 64）。行数可以少于总帧数，尾部就是"不查"。
- 每帧 `orig(level)` 之后立刻比对；超差就以 `deviated` 结束任务，并回报 `deviation{frame, index, expected, actual, offset, tolerance}`。`frame` 是 1 基的，直接和 `executed_frames`、轨迹对齐。
- 同一帧也可以要求 `capture_positions`，回传 `positions`（每帧一个坐标，比 `checkpoints` 轻得多）。

于是"逐帧预期"有了数据来源：每次执行都顺手记下这 40 帧她实际在哪，落地就把这串坐标写进路线（`Replay.trace`）。下次重放时按起点差平移整条轨迹再发——匹配容差是 2px，不平移的话第 1 帧就会误报。平移而不是重算，是因为在这 2px 尺度上物理是平移不变的；房间不是（旁边一条檐板差 1px）时，几帧后就会以 `deviated` 说出来，代价是几帧而不是一条命。

`deviated` 在客户端归为 `ABORTED`（`reason="deviated"`），因为它说的是"这条弧线不再描述这个房间"，而不是"这次的落点错了"——这两句话对应两种不同的下一步。

#### 本地重算：先换一条，再问模型

失手不一定说明计划错了：可能只是起步差 1px，也可能是转场把人打断了。这两种都有比一次模型调用更便宜的答案。

`LocalRetry` 只做一件事——从书里再挑一条路线，所以它**不可能编出一条没跑过的弧线**：

- 只在"上一手没落地"时出手，预算是每次失败连发最多 2 次（一落地就重置，探索本身付出的失手不被惩罚）。
- 候选必须同房间、冲刺数够、`streak` 未到上限、且**不是刚刚失败的那一条**（按动作序列比对，不是按坐标——回执的起点可能差 1px）。
- 带轨迹的路线可以放宽到 8px 起点差（有弧线兜底，几帧就能发现不对）；没有轨迹的仍卡 2px。
- 挑不出来就返回 `None`，回到模型——这条退路是刻意的，否则"便宜路径"会变成一个反复撞同一堵墙的闭环。
- 计数进 `SESSION.local_retries`，和模型调用次数分开看。

#### 知识注入：常数常驻，机制按房间给

模型最常犯的错不是不会规划，而是把常数记错：房间 7 曾经按"跳跃 32px"排了一套三段宏，实测只有 27px，整套重来。

现在 `agent/knowledge.py` 分两块：

- `MOVEMENT_REFERENCE`（常驻）：跑/跳/冲刺/墙跳/弹墙/平台加速的弧线数字，全部对齐 `kb/speedrun/` 里标了"代码已核实"的条目。
- `mechanisms_reference(types)`（按房间）：锚点带上房间的实体类型（`get_entities` 按房间缓存），只注入这个房间真有的机制——尖刺的 3px 判定与"朝离开方向运动可穿过"、弹簧的 `(0,-185)`、碎台的 13–37 帧、交通块往返节奏、冲刺砖反弹量。

一条规则只在它生效的房间里出现，既省 token，也不会让模型拿某个房间的机制去解释另一个房间。

#### 长尾检索：从 `kb/` 原样引一段

上面两块是手写的摘要，代价是 `kb/speedrun/` 里真正值钱的东西——帧窗口、变体前置、可抄的输入例、规则的例外——从来没进过提示词。房间 8 的口袋就是例子：`mechanisms_reference` 只说了"尖刺致死看运动方向"，而"冲刺 F5–F20 还能 wallbounce、贴带刺墙时容差从 4px 降到 2px"在 `techniques.md §4.3` 里。

`agent/kb.py` 补的就是这一段：

- **按标题切段**（叶子段），共 251 段 / 14.6 万字，索引一次约 5ms，单次检索约 2ms。有子标题的父段不单独成段，避免同一内容进两次。
- **整段才引**：预算 3600 字符、最多 4 段。放不下的段直接跳过换下一名，**不截断**——截半张表等于给模型一个没有前提的数字。
- **查询词来自房间和姿态**：实体类型走一张词表（`Spikes → 尖刺/spike/方向性`，没收录的类型返回空，不猜），再加落地/空中的动作族（落地给跳跃·冲刺·walljump，空中给冲刺·wallbounce·攀爬）。
- **排序**：标题命中 ×3 + 正文命中（上限 4），同分时 `techniques.md` 优先于 `player_physics.md`/`entities.md`（后者大多是在复述已经蒸馏过的规则），再取段更短的。同样的输入永远给同样的输出。
- **只读 `kb/speedrun/`**：`kb/explore/` 按设计就是探索不该看到的资料；`kb/shared/tools/` 写的是另一套 harness 的调用形状，抄进计划里是跑不起来的代码。本机生成的 `kb/reference/`（社区原文）也不进，量太大且与已核实的文件重复。
- **引用可回溯**：每段带 `[techniques.md §4.3 Wallbounce variants]`，`【代码已核实】` 与 `（未核实）` 原样保留，`knowledge_guidance` 里写明"引用不是指令，弧线数字仍以 `movement_reference` 为准"。

参数：`--kb-root`（默认 `kb/`）、`--kb-budget`（默认 3600）、`--no-kb`。实际引了几段进 `SESSION.kb_sections`；房间 8 站位 2719,-1704 的一次检索是 §5.4 尖刺与 spike jump、§6.5 换房 tech、§4.3 wallbounce 变体、§7.3 冲刺贴地，共 3597 字符。

想看不调模型、不起游戏时会引什么：

```bash
python -m agent.kb --types Spikes,Spring,JumpThru     # 只列命中的段
python -m agent.kb --types Spikes --air --show        # 空中姿态，连正文一起打
```

### 单循环路径的防漂移

- **`--settle`** — 规划前等最多 3 秒到「落地且稳定」的观测。
- **`--pause-planning`** — 思考时冻结游戏，执行前恢复（需要桥接 0.2.4+）。
- **stale-plan guard** — 若计划落地状态、冲刺数或位置与执行时观测不符，直接跳过该计划，一帧输入都不发。

`--success-room` 用来收窄 `--exit-room`：只认前进方向的房间，避免「走回上一个房间也算成功」的假成功。

### 执行契约

执行不是「把帧灌进去然后看结果」。每一步都带一份契约，由执行器拿实时状态核：

| 结局 | 含义 | 下一步 |
| --- | --- | --- |
| `REJECTED` | 前置条件不成立（房间/落地/冲刺数/位置带） | **零帧发出**，直接重规划 |
| `ABORTED` | 执行中触发硬限（停滞 / 超时 / 越界） | 已 `stop`，报告在哪一帧偏的 |
| `UNSATISFIED` | 帧全跑完，但没落到成功带 | 计划对世界的判断错了 |
| `SUCCEEDED` | 帧全跑完且落在带内 | 推进下一步 |
| `DIED` | 死亡 | 等自动重生（**不 `reset_room`**，会崩） |

`ABORTED` 与 `UNSATISFIED` 的区别是整个拆分的意义所在：前者说明世界在计划执行期间变了，后者说明计划本身判断错了，两者需要完全不同的下一个计划。

在 `--collab` 下 `REJECTED` 应该是**结构上不可能**的：锚点承诺保证计划据以推理的状态就是第一条输入落到的状态，而锚点在发送前还会再核一次。它一旦出现，说明承诺本身破了，日志会把它当作缺陷记成 `STALE_PLAN` 并计入 `SESSION.rejected`——目标值是 0。

执行是实时的（每 `Level.Update` 应用一次输入），所以中止能做到帧级——不必把动作切段，切段会在间隙松开按键，毁掉跳跃弧线。

实测（房间 7）：`right:60` + `timeout_frames=8` 在 0.22 秒内停在 `at_frame=9`，报告 `executed_frames=10`。多出来的一帧是停止请求本身——它要等下一个 `Engine.Update` 才被取出，所以中止帧之后总有一帧会落地。判据写成 `executed = at + 1`，不要指望零开销的瞬时刹车。

`at_frame` 偶尔会比预算多一帧，这不是计数不准，而是采样问题：每轮巡检要发 `get_state` 和 `get_execution` 两次调用，两次都要排在帧边界上，所以实际只能看到隔帧，中止决策落在**第一个 ≥ 预算的采样点**。经验范围是 `at ≤ 预算 + 2`。

同一轮实测还暴露了一个桩测试测不出的坑：`get_execution` 在任务运行期间**不报** `executed_frames`（该字段由 `Finish` 写入），看门狗若读它就会永远看到 0，超时与停滞条款全成死条款。桥接 0.3.3 起改为每帧回写，`get_execution` 在运行中就能读到 9 → 14 → 19 这样的活计数；客户端优先用这个自报值，房间帧计数（`get_state().frame - 起始帧`）只作为旧版桥接的兜底——实测那个兜底会高估：起始观测在 frame 1014，任务受理已是 1017，中间三次调用的帧全算进去了。

---

`live_search` 在 SpeedrunTool 存档槽上做有界束搜索，`--compare-skills` 并行跑「有技能提示」与「纯搜索」两组，输出候选数、命中率和回放验证结果。6b 入口段的实测：普通搜索用了 7 次评估，有技能提示只用 2 次，两组都落在 (2055,-1128) 且通过 3 次独立回放。

技能是**版本绑定**的（`game_version` + 房间 + 落地状态 + 冲刺数），游戏更新后自动失效而不是错用。

---

## TAS 数据训练

```shell
git clone https://github.com/VampireFlower/CelesteTAS.git data/tas-source
python -m agent.tas_training data/tas-source
python -m agent.main --real --mode deepseek --tas-prior data/tas-training/action-prior.json
```

训练器只学「上一个按键组合之后常跟什么组合」，属于动作先验，不是状态模仿。度量的是留出集上的动作预测准确率，**不等于能过关**。

> **注意**：`data/` 里那份 `1A-through-6b.tas` 的 `#lvl_6b` 段是**原版 1A** 的（与 `data/tas-source/1A.tas` 对应段逐字节相同），而本机跑的是教学地图——房间名撞了，几何完全不同。回放它会把人从左门带出房间。TAS 数据对当前关卡无效，只能自己解。

PICO-8 版 Celeste Classic 用独立的输入格式，单独训练：`python -m agent.classic_training <路径>`。

---

## 文档

- `docs/protocols.md` — 协议 1.0、方法表、错误码、信息层 schema
- `docs/acceptance.md` — 逐项验收清单与实机记录
- `docs/phase4-7-status.md` — 各阶段实现到哪、哪些只是脚手架
- `data/routes/6b.md`、`data/routes/6c.md`、`data/routes/7.md` — 通关路线的完整推导
- `agent/agents/seed-routes.json` — 房间 7 三段宏的机器可读版本（路线书的起点，见「路线重放」）
- `agent/agents/retry.py` — 失败后不唤醒模型的换路逻辑（见「本地重算」）
- `agent/knowledge.py` — 常驻移动常数 + 按房间挑选的机制说明
- `agent/kb.py` — 从 `kb/speedrun/` 按段检索并原样引用的长尾知识（见「长尾检索」）

源码：https://github.com/chisAcn/Celeste-Deepseek
