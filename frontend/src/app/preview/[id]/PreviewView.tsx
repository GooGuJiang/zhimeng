"use client";
/** 世界预览 (F1): map, characters, initial conflict; confirm → play, or regenerate in place (SSE). */
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { RefreshCw, DoorOpen } from "lucide-react";
import { api, streamPath, errorText } from "@/lib/api";
import type { World } from "@/lib/types";
import { worldCache } from "@/lib/cache";
import { setCurrentWorld } from "@/hooks/useCurrentWorld";
import { useWorldGeneration } from "@/hooks/useWorldGeneration";
import { AiLabel } from "@/components/AiLabel";
import { GenerationProgress } from "@/components/GenerationProgress";
import { SafetyNotice } from "@/components/SafetyNotice";
import { CharacterList, KnowledgeCards, WorldMapView } from "@/components/WorldBits";
import { useToast } from "@/components/Toast";

export function PreviewView({ id }: { id: string }) {
  const router = useRouter();
  const toast = useToast();
  const gen = useWorldGeneration();
  const [world, setWorld] = useState<World | null>(() => worldCache.get(id));
  const [err, setErr] = useState<string | null>(null);
  const [tweak, setTweak] = useState("");
  const [entering, setEntering] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .getWorld(id)
      .then((w) => {
        if (!live) return;
        worldCache.set(w);
        setWorld(w);
      })
      .catch((e) => live && setErr(errorText(e)));
    return () => {
      live = false;
    };
  }, [id]);

  // v1.2 two-step generation: the preview arrives first; details are merged in the background.
  // Poll GET /worlds/{id} while enriching (every ~2.5 s, capped at ~3 min).
  const detail = world?.detail_status;
  const enriching = detail === "enriching" && !gen.running;
  useEffect(() => {
    if (!enriching) return;
    let live = true;
    let n = 0;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      if (!live || ++n > 70) return;
      try {
        const w = await api.getWorld(id);
        if (!live) return;
        worldCache.set(w);
        setWorld(w);
        if (w.detail_status !== "enriching") {
          if (w.detail_status === "complete") toast("世界细节已补全");
          return;
        }
      } catch {
        /* transient: keep polling */
      }
      timer = setTimeout(tick, n < 20 ? 2500 : 5000);
    };
    timer = setTimeout(tick, 2000);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [enriching, id, toast]);

  // v1.2: the original request lives in World.gen_request (state.flags.gen_request is deprecated);
  // the tweak goes in `refine` (applied on top of the original prompt; omitted = keep the last one).
  const lastRefine = world?.gen_request?.refine?.trim() || "";
  const [clearRefine, setClearRefine] = useState(false);
  const regenerate = async () => {
    const t = tweak.trim();
    const body = t ? { refine: t } : clearRefine ? { refine: "" } : {};
    const { world: w } = await gen.run(streamPath.regenerate(id), body);
    if (w) {
      worldCache.set(w);
      setWorld(w);
      setTweak("");
      setClearRefine(false);
      toast("世界已重新织就");
    } else {
      api
        .getWorld(id)
        .then(setWorld)
        .catch(() => {});
    }
  };

  const enter = async () => {
    setEntering(true);
    try {
      const w = world?.status === "active" ? world : await api.confirmWorld(id);
      if (w) worldCache.set(w);
      setCurrentWorld(id);
      router.push(`/play/${id}`);
    } catch (e) {
      setEntering(false);
      toast(`进入失败：${errorText(e)}`);
    }
  };

  if (!world)
    return err ? (
      <div className="empty">
        <h1 className="h1">找不到这个世界</h1>
        <p>{err}</p>
      </div>
    ) : (
      <div className="stack" aria-busy>
        <div className="skel" style={{ height: 48, width: "40%" }} />
        <div className="skel" style={{ height: 320 }} />
      </div>
    );

  const npcs = world.characters;
  return (
    <div className="preview" data-testid="world-preview">
      <div className="preview-head">
        <div style={{ flex: 1, minWidth: 260 }}>
          <div className="eyebrow">{world.mode === "education" ? "教育模式 · 世界预览" : "世界预览"}</div>
          <h1 className="h1" style={{ fontSize: "clamp(28px,4vw,44px)" }}>
            {world.title}
          </h1>
          <div className="row" style={{ marginTop: 8 }}>
            {[world.era, world.genre, world.tone].filter(Boolean).map((t) => (
              <span key={t} className="tag gold">
                {t}
              </span>
            ))}
            <span className="tag">分级 {world.rating}</span>
            {world.minor_mode ? <span className="tag jade">未成年人模式</span> : null}
            {world.source === "fallback" ? (
              <span className="tag" title="模型不可用时使用的本地模板">
                本地兜底模板
              </span>
            ) : null}
            <AiLabel text={world.ai_label} />
          </div>
        </div>
      </div>
      <p className="lead serif" style={{ marginTop: 0 }}>
        {world.premise || world.setting}
      </p>

      {enriching ? (
        <div className="notice row detail-enriching" data-testid="world-detail-enriching" aria-live="polite">
          <span className="dots" aria-hidden>
            <i />
            <i />
            <i />
          </span>
          <span>细节补全中：人物经历、地点与暗线正在后台织入，可以先进入世界，补全后会自动更新。</span>
        </div>
      ) : detail === "local" ? (
        <p className="faint" style={{ fontSize: 12, margin: 0 }} data-testid="world-detail-local">
          细节由本地规则补全（模型暂不可用），世界完整可玩。
        </p>
      ) : null}
      {gen.running ? <GenerationProgress gen={gen} title="重新织就" /> : null}
      {gen.safety?.blocked ? <SafetyNotice result={gen.safety} /> : null}
      {gen.error && !gen.running ? <div className="notice warn">{gen.error}（原世界未改变）</div> : null}

      <div className="preview-grid" style={{ opacity: gen.running ? 0.45 : 1 }}>
        <div className="stack">
          <section className="card">
            <div className="card-h">
              <i className="knot" aria-hidden />
              <h2 className="h2">世界地图</h2>
              <span className="faint" style={{ fontSize: 12 }}>
                {world.locations.length} 处地点
              </span>
            </div>
            <WorldMapView world={world} />
          </section>
          <section className="card">
            <div className="card-h">
              <i className="knot" aria-hidden />
              <h2 className="h2">初始冲突</h2>
            </div>
            <p className="conflict" data-testid="initial-conflict">
              {world.initial_conflict}
            </p>
            {world.opening_scene ? (
              <p className="muted serif" style={{ marginTop: 16, whiteSpace: "pre-wrap" }}>
                {world.opening_scene}
              </p>
            ) : null}
          </section>
        </div>
        <div className="stack">
          <section className="card">
            <div className="card-h">
              <i className="knot" aria-hidden />
              <h2 className="h2">登场角色</h2>
              <span className="faint" style={{ fontSize: 12 }}>
                {npcs.length} 位
              </span>
            </div>
            <CharacterList characters={npcs} />
          </section>
          {world.setting ? (
            <section className="card">
              <div className="card-h">
                <i className="knot" aria-hidden />
                <h2 className="h2">时代与规则</h2>
              </div>
              <p className="muted" style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                {world.setting}
              </p>
            </section>
          ) : null}
          {world.mode === "education" && world.knowledge_cards?.length ? (
            <section className="card">
              <div className="card-h">
                <i className="knot" aria-hidden />
                <h2 className="h2">知识卡片</h2>
              </div>
              <KnowledgeCards cards={world.knowledge_cards} />
            </section>
          ) : null}
        </div>
      </div>

      <div className="sticky-actions">
        {lastRefine && !clearRefine && !tweak.trim() ? (
          <span className="tag" data-testid="refine-current" title="下次重新生成会沿用这条补充要求">
            沿用：{lastRefine.slice(0, 24)}
            <button
              type="button"
              className="tag-x"
              aria-label="清除补充要求"
              onClick={() => setClearRefine(true)}
            >
              ×
            </button>
          </span>
        ) : null}
        <input
          className="input tweak"
          data-testid="regenerate-refine"
          placeholder={lastRefine ? "新的补充要求（留空沿用上次）" : "想调整什么？（可选，如：多一点悬疑）"}
          value={tweak}
          onChange={(e) => setTweak(e.target.value)}
          disabled={gen.running}
          aria-label="重新生成的调整要求"
        />
        <button
          type="button"
          className="btn ghost"
          data-testid="regenerate-btn"
          onClick={() => void regenerate()}
          disabled={gen.running || entering}
        >
          <RefreshCw size={16} aria-hidden /> 重新生成
        </button>
        <button
          type="button"
          className="btn"
          data-testid="confirm-world-btn"
          onClick={() => void enter()}
          disabled={gen.running || entering}
        >
          <DoorOpen size={16} aria-hidden /> {entering ? "推门而入…" : "进入世界"}
        </button>
      </div>
    </div>
  );
}
