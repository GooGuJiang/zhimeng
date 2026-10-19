"use client";
/** 存档 (F8): all worlds on this server, continue / export / delete, and import a JSON save. */
import Link from "next/link";
import { useEffect, useState } from "react";
import { Download, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { WorldSummary } from "@/lib/types";
import { useCurrentWorld } from "@/hooks/useCurrentWorld";
import { ImportSave } from "@/components/ImportSave";
import { useToast } from "@/components/Toast";
import { downloadBlob } from "@/lib/video";

export function SavesView() {
  const toast = useToast();
  const [current, setCurrent] = useCurrentWorld();
  const [list, setList] = useState<WorldSummary[] | null>(null);
  const load = () =>
    api
      .listWorlds()
      .then(setList)
      .catch(() => setList([]));
  useEffect(() => {
    void load();
  }, []);
  const exportOne = async (w: WorldSummary) => {
    try {
      const s = await api.exportSave(w.id);
      downloadBlob(
        new Blob([JSON.stringify(s, null, 2)], { type: "application/json" }),
        `织梦存档-${w.title}.json`,
      );
    } catch (e) {
      toast(`导出失败：${(e as Error).message}`);
    }
  };
  const remove = async (w: WorldSummary) => {
    if (!confirm(`确定删除《${w.title}》？此操作不可恢复，建议先导出存档。`)) return;
    try {
      await api.deleteWorld(w.id);
      if (current === w.id) setCurrent(null);
      toast("已删除");
      void load();
    } catch (e) {
      toast(`删除失败：${(e as Error).message}`);
    }
  };
  return (
    <div className="stack">
      <div className="row">
        <div style={{ flex: 1 }}>
          <div className="eyebrow">存档与分享</div>
          <h1 className="h1">我的世界</h1>
          <p className="muted" style={{ margin: "6px 0 0" }}>
            世界进度自动保存在服务器；导出 JSON 存档可在任何设备上导入继续。
          </p>
        </div>
        <ImportSave label="导入 JSON 存档" />
      </div>
      {list === null ? <div className="skel" style={{ height: 160 }} /> : null}
      <div className="grid-3">
        {list?.map((w) => (
          <article key={w.id} className={`world-tile${current === w.id ? " on" : ""}`}>
            <strong>{w.title}</strong>
            <span className="faint" style={{ fontSize: 13 }}>
              {[w.mode === "education" ? "教育" : w.genre, w.tone].filter(Boolean).join(" · ")} · 第 {w.turn}{" "}
              回合 · {w.status === "draft" ? "草稿" : w.status === "ended" ? "已完结" : "进行中"}
            </span>
            <span className="faint" style={{ fontSize: 12 }}>
              更新于 {new Date(w.updated_at).toLocaleString("zh-CN", { hour12: false })}
            </span>
            <div className="row" style={{ marginTop: 6 }}>
              <Link
                className="btn sm"
                href={w.status === "draft" ? `/preview/${w.id}` : `/play/${w.id}`}
                onClick={() => setCurrent(w.id)}
              >
                {current === w.id ? "继续" : "进入"}
              </Link>
              <button type="button" className="btn sm ghost" onClick={() => void exportOne(w)}>
                <Download size={13} aria-hidden /> 导出
              </button>
              <button
                type="button"
                className="icon-btn"
                aria-label={`删除 ${w.title}`}
                onClick={() => void remove(w)}
              >
                <Trash2 size={14} />
              </button>
            </div>
          </article>
        ))}
      </div>
      {list && !list.length ? (
        <div className="empty">
          <p>还没有世界。</p>
          <Link className="btn" href="/">
            去造化一个
          </Link>
        </div>
      ) : null}
    </div>
  );
}
