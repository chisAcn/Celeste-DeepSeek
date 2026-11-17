import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

const labels = {
  'single-skill': '单技能复用',
  'pair-tight-radius': '双技能 · 半径 3',
  'pair-moving-platform': '双技能 · 半径 10',
  without_skills: '普通搜索',
  with_skills: '技能辅助',
};
const point = (player) => player ? '(' + player.x + ', ' + player.y + ')' : '无玩家';

function Trajectory({ frames, frame, target, boundaries }) {
  const canvas = useRef(null);
  useEffect(() => {
    const element = canvas.current;
    function draw() {
      const { width, height } = element.getBoundingClientRect();
      const dpr = window.devicePixelRatio;
      element.width = width * dpr;
      element.height = height * dpr;
      const ctx = element.getContext('2d');
      ctx.scale(dpr, dpr);
      const points = [...frames.map((state) => state.player).filter(Boolean),
        { x: target[0], y: target[1] }];
      const xMin = Math.min(...points.map((p) => p.x));
      const yMin = Math.min(...points.map((p) => p.y));
      const spanX = Math.max(1, Math.max(...points.map((p) => p.x)) - xMin);
      const spanY = Math.max(1, Math.max(...points.map((p) => p.y)) - yMin);
      const scale = Math.min((width - 56) / spanX, (height - 56) / spanY);
      const xy = (p) => [(width - spanX * scale) / 2 + (p.x - xMin) * scale,
        (height - spanY * scale) / 2 + (p.y - yMin) * scale];
      function dot(p, color, radius) {
        if (!p) return;
        const [x, y] = xy(p);
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, 2 * Math.PI);
        ctx.fillStyle = color;
        ctx.fill();
      }
      ctx.lineWidth = 2;
      for (let i = 1; i < frames.length; i++) {
        const left = frames[i - 1].player;
        const right = frames[i].player;
        if (!left || !right) continue;
        ctx.beginPath();
        ctx.moveTo(...xy(left));
        ctx.lineTo(...xy(right));
        ctx.strokeStyle = i <= frame ? '#50d9c2' : '#52647a';
        ctx.stroke();
      }
      dot({ x: target[0], y: target[1] }, '#f5ac67', 6);
      boundaries.forEach(({ frame: boundary }) => dot(frames[boundary]?.player, '#bc9aff', 4));
      dot(frames[frame].player, '#fff', 5);
    }
    const observer = new ResizeObserver(draw);
    observer.observe(element);
    draw();
    return () => observer.disconnect();
  }, [frames, frame, target, boundaries]);
  return <canvas ref={canvas} aria-label="玩家位置轨迹，横轴为 X，纵轴为 Y" role="img" />;
}

function Details({ arm, target }) {
  const [frame, setFrame] = useState(0);
  const state = arm.trajectory[frame];
  const player = state.player;
  let last = 0;
  return <div className="details">
    <section className="panel">
      <div className="section-head"><h2>轨迹回看</h2><span className="mono">{frame} / {arm.trajectory.length - 1} 帧</span></div>
      <Trajectory frames={arm.trajectory} frame={frame} target={target} boundaries={arm.skill_boundaries} />
      <div className="legend"><span>● 当前帧</span><span>● 目标</span><span>● 技能结束帧</span></div>
      <input aria-label="轨迹帧" type="range" min="0" max={arm.trajectory.length - 1}
        value={frame} onChange={(event) => setFrame(Number(event.target.value))} />
      <div className="state">
        <div>房间 <strong>{state.room.name}</strong></div>
        <div>位置 <strong>{point(player)}</strong></div>
        <div>速度 <strong>{player ? player.vx.toFixed(1) + ' / ' + player.vy.toFixed(1) : '—'}</strong></div>
        <div>状态 <strong>{player ? player.dead ? '死亡' : player.on_ground ? '着地' : '空中' : '—'}</strong></div>
        <div>冲刺 <strong>{player?.dashes ?? '—'}</strong></div>
        <div>体力 <strong>{player?.stamina ?? '—'}</strong></div>
      </div>
      {arm.screenshot && <img className="screenshot" src={arm.screenshot} alt="录制截图" />}
    </section>
    <section className="panel">
      <h2>动作与验证</h2>
      <ol className="actions">{arm.actions.map((action, index) => {
        const first = last + 1;
        last += action.frames;
        const active = frame >= first && frame <= last;
        return <li key={index}><button className={active ? 'active' : ''}
          onClick={() => setFrame(Math.min(first, arm.trajectory.length - 1))}>
          <span>{action.buttons.join(' + ') || '无输入'}</span><span>{first}–{last} 帧</span>
        </button></li>;
      })}</ol>
      {arm.skill_boundaries.length > 0 && <div className="boundaries">
        {arm.skill_boundaries.map((boundary) => <button key={boundary.frame}
          onClick={() => setFrame(boundary.frame)}>
          {boundary.skill} · 帧 {boundary.frame}{boundary.failure && ' · ' + boundary.failure}
        </button>)}
      </div>}
      <ul className="replays">{arm.replays.map((replay, i) => <li key={i}>
        回放 {i + 1}<strong className={replay.matches ? 'ok' : 'warn'}>
          {replay.matches ? '一致' : '首次差异 ' + replay.first_difference}
        </strong>
      </li>)}</ul>
      <p className="muted">Token {arm.token_usage == null ? '未记录' : JSON.stringify(arm.token_usage)}
        {' · API 费用 '}{arm.api_cost ?? '未记录'}</p>
    </section>
  </div>;
}

function ArmSummary({ scenario, selected, onSelect }) {
  return <div className="arms">{Object.entries(scenario.arms).map(([key, arm]) =>
    <button key={key} className={'panel arm ' + (selected === key ? 'selected' : '')}
      aria-pressed={selected === key} onClick={() => onSelect(key)}>
      <span className="section-head"><strong>{labels[key]}</strong>
        <span className={arm.success ? 'ok' : 'warn'}>{arm.success ? '达到目标' : '未达到目标'}</span></span>
      <span className="arm-count"><strong>{arm.evaluations}</strong> / {scenario.candidate_budget} 次试跑</span>
      <span className="muted">观测死亡 {arm.deaths_observed} · 候选重试 {arm.candidate_retries}</span>
      <span className="muted">试跑 {arm.candidate_frames} 帧 · 回放 {arm.verification_frames} 帧</span>
    </button>)}</div>;
}

function App() {
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState('with_skills');
  useEffect(() => {
    fetch('/api/evaluation').then(async (response) => {
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail);
      return body;
    }).then(setReport).catch((failure) => setError(failure.message));
  }, []);
  const scenario = report?.cases[index];
  return <main>
    <header className="section-head">
      <div><p className="muted">Celeste Agent / 离线记录</p><h1>轨迹评估</h1></div>
      {report && <a className="download" href="/api/evaluation/download">导出 JSON</a>}
    </header>
    {error && <p role="alert" className="panel warn">{error}</p>}
    {!error && !report && <p role="status">正在读取评估报告…</p>}
    {scenario && <>
      <nav aria-label="评估案例">{report.cases.map((item, i) => <button
        key={item.id} aria-pressed={index === i} onClick={() => setIndex(i)}>{labels[item.id]}</button>)}</nav>
      <div className="section-head objective">
        <p>目标 <strong>({scenario.target.join(', ')})</strong> · 半径 {scenario.radius} 像素 · 连续着地 {scenario.grounded_frames} 帧</p>
        <p className={scenario.passed ? 'ok' : 'warn'}>{scenario.passed ? '离线复核通过' : '离线复核失败'}</p>
      </div>
      <ArmSummary scenario={scenario} selected={selected} onSelect={setSelected} />
      <Details key={scenario.id + selected} arm={scenario.arms[selected]} target={scenario.target} />
      <section className="panel training">
        <h2>技能录制成本</h2>
        <div>{Object.entries(report.training).map(([key, cost]) => <p key={key}>
          <strong>{key === 'entrance' ? '入口' : '续段'}</strong> · {cost.candidate_runs} 次试跑 · {cost.verification_runs} 次回放 · 共 {cost.executed_frames} 帧
        </p>)}</div>
      </section>
    </>}
  </main>;
}

createRoot(document.getElementById('root')).render(<App />);
