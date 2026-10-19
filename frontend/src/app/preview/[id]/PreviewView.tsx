"use client";
/** 世界预览 (F1): map, characters, initial conflict; confirm → play, or regenerate in place (SSE). */
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { RefreshCw, DoorOpen } from "lucide-react";
import { api, streamPath } from "@/lib/api";
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
      .catch((e) => live && setErr((e as Error).message));
    return () => {
      live = false;
    };
  }, [id]);

  const regenerate = async () => {
    const body = tweak.trim() ? { prompt: tweak.trim() } : {};
    const { world: w } = await gen.run(streamPath.regenerate(id), body);
    if (w) {
      worldCache.set(w);
      setWorld(w);
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
      toast(`进入失败：${(e as Error).message}`);
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
        <input
          className="input tweak"
          placeholder="想调整什么？（可选）"
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
