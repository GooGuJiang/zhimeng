"use client";
/** 教育模式 (F10): 课文 / 史料 / 非遗 → an explorable world with knowledge cards and a learning summary. */
import { useRouter } from "next/navigation";
import { useState } from "react";
import { BookOpen, FileText, Wand2 } from "lucide-react";
import { streamPath } from "@/lib/api";
import { useWorldGeneration } from "@/hooks/useWorldGeneration";
import { worldCache } from "@/lib/cache";
import { GenerationProgress } from "@/components/GenerationProgress";
import { SafetyNotice } from "@/components/SafetyNotice";
import { usePrefs } from "@/hooks/usePrefs";

const SUBJECTS = ["语文", "历史", "地理", "非遗", "科学", "思政"];
const GRADES = ["小学", "初中", "高中", "大学"];
const SAMPLES = [
  {
    title: "桃花源记",
    subject: "语文",
    text: "晋太元中，武陵人捕鱼为业。缘溪行，忘路之远近。忽逢桃花林，夹岸数百步，中无杂树，芳草鲜美，落英缤纷。渔人甚异之，复前行，欲穷其林。林尽水源，便得一山，山有小口，仿佛若有光。",
  },
  {
    title: "郑和下西洋",
    subject: "历史",
    text: "永乐三年（1405年），明成祖命郑和率领二百四十多艘海船、二万七千四百名船员的庞大船队远航，访问了三十多个西太平洋和印度洋的国家和地区。",
  },
  {
    title: "昆曲",
    subject: "非遗",
    text: "昆曲发源于元末明初的苏州昆山，被誉为“百戏之祖”，2001 年被联合国教科文组织列为“人类口述和非物质遗产代表作”。",
  },
];

export function EducationView() {
  const router = useRouter();
  const gen = useWorldGeneration();
  const [prefs] = usePrefs();
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [subject, setSubject] = useState("语文");
  const [grade, setGrade] = useState("初中");

  const go = async () => {
    if (!text.trim() || gen.running) return;
    const { world, worldId } = await gen.run(streamPath.education, {
      source_text: text.trim(),
      title: title.trim() || undefined,
      subject,
      grade,
      minor_mode: true,
    });
    if (world) worldCache.set(world);
    if (worldId) router.push(`/preview/${worldId}`);
  };
  const onFile = async (f?: File) => f && setText((await f.text()).slice(0, 20000));

  return (
    <div className="edu">
      <section className="hero edu-hero">
        <div className="hero-copy">
          <div className="eyebrow">文化 / 教育模式</div>
          <h1 className="h-display">
            把课文，
            <br />
            变成<em>可以走进</em>的世界
          </h1>
          <p className="lead">
            粘贴一段课文、史料或非遗介绍。织梦会依据原文与史实搭建场景与人物，你以亲历者的身份探索，沿途解锁知识卡片，最后获得学习小结与小测验。
          </p>
          <ul className="edu-feats">
            <li>📜 依原文建构，标注知识出处</li>
            <li>🃏 知识卡片随剧情解锁</li>
            <li>🧭 学习小结 · 时间线 · 小测验 · 反思</li>
            <li>🛡️ 默认开启未成年人模式</li>
          </ul>
        </div>
        <div className="composer card">
          <label className="field">
            <span>课文 / 史料原文</span>
            <textarea
              className="textarea big"
              data-testid="edu-source-input"
              placeholder="在此粘贴课文、史料或非遗原文…"
              value={text}
              onChange={(e) => setText(e.target.value)}
              style={{ minHeight: 180 }}
              disabled={gen.running}
            />
          </label>
          <div className="seed-list">
            {SAMPLES.map((s) => (
              <button
                key={s.title}
                type="button"
                className="seed"
                onClick={() => {
                  setText(s.text);
                  setTitle(s.title);
                  setSubject(s.subject);
                }}
              >
                示例：《{s.title}》
              </button>
            ))}
          </div>
          <div className="grid-2" style={{ marginTop: 14, gap: 12 }}>
            <label className="field">
              <span>标题（可选）</span>
              <input
                className="input"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="如：桃花源记"
              />
            </label>
            <label className="field">
              <span>学段</span>
              <select className="select" value={grade} onChange={(e) => setGrade(e.target.value)}>
                {GRADES.map((g) => (
                  <option key={g}>{g}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="opt-group">
            <span className="opt-label">学科</span>
            <div className="chips">
              {SUBJECTS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className={`chip${subject === s ? " on" : ""}`}
                  onClick={() => setSubject(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
          <div className="composer-foot">
            <label className="upload">
              <FileText size={14} aria-hidden /> 上传 .txt
              <input
                type="file"
                accept=".txt,.md,text/plain"
                className="sr-only"
                onChange={(e) => void onFile(e.target.files?.[0])}
              />
            </label>
            <span className="faint" style={{ fontSize: 12 }}>
              {text.length} 字{prefs.minorMode ? "" : " · 教育模式始终以全年龄分级生成"}
            </span>
            <span className="spacer" />
            <button
              type="button"
              className="btn lg"
              data-testid="edu-generate-btn"
              disabled={!text.trim() || gen.running}
              onClick={() => void go()}
            >
              <Wand2 size={18} aria-hidden /> 生成可走进的世界
            </button>
          </div>
          {gen.running ? <GenerationProgress gen={gen} title="化文为境" /> : null}
          {gen.safety?.blocked ? <SafetyNotice result={gen.safety} /> : null}
          {gen.error && !gen.running ? (
            <div className="notice warn row" role="alert" style={{ marginTop: 12 }}>
              <span style={{ flex: 1 }}>{gen.error}</span>
              <button type="button" className="btn sm ghost" onClick={() => void go()}>
                重试
              </button>
            </div>
          ) : null}
        </div>
      </section>
      <p className="faint center">
        <BookOpen size={14} aria-hidden style={{ verticalAlign: -2 }} /> 内容由 AI
        依据原文生成，可能存在偏差，请以教材与权威史料为准。
      </p>
    </div>
  );
}
