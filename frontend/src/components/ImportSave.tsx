"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Upload } from "lucide-react";
import { api, errorText } from "@/lib/api";
import { setCurrentWorld } from "@/hooks/useCurrentWorld";
import { worldCache } from "@/lib/cache";
import { useToast } from "./Toast";

/** F8: import a `zhimeng-save` JSON file and continue playing it. */
export function ImportSave({ label = "导入存档" }: { label?: string }) {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const onFile = async (f: File | undefined) => {
    if (!f) return;
    setBusy(true);
    try {
      const save = JSON.parse(await f.text());
      if (save?.format !== "zhimeng-save") throw new Error("不是有效的织梦存档文件");
      const w = await api.importSave(save);
      worldCache.set(w);
      setCurrentWorld(w.id);
      toast(`已导入《${w.title}》`);
      router.push(`/play/${w.id}`);
    } catch (e) {
      toast(`导入失败：${errorText(e)}`);
    } finally {
      setBusy(false);
    }
  };
  return (
    <label className="upload" aria-busy={busy}>
      <Upload size={14} aria-hidden />
      {busy ? "导入中…" : label}
      <input
        type="file"
        accept="application/json,.json"
        data-testid="import-input"
        className="sr-only"
        onChange={(e) => {
          void onFile(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
    </label>
  );
}
