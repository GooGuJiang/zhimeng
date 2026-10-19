"use client";
/** F9 举报入口: POST /api/reports. */
import { useState } from "react";
import { api } from "@/lib/api";
import { Dialog } from "./Dialog";
import { useToast } from "./Toast";

const REASONS = ["违法违规", "色情低俗", "暴力血腥", "危害未成年人", "歧视仇恨", "虚假信息", "其他"];

export function ReportDialog({
  worldId,
  turnId,
  content,
  onClose,
}: {
  worldId?: string;
  turnId?: string;
  content: string;
  onClose: () => void;
}) {
  const toast = useToast();
  const [reason, setReason] = useState(REASONS[0]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      await api.report({
        world_id: worldId,
        turn_id: turnId,
        content: content.slice(0, 4000) || "(空)",
        reason: note.trim() ? `${reason}：${note.trim()}` : reason,
      });
      toast("举报已收到，感谢你的反馈");
      onClose();
    } catch (e) {
      toast(`举报提交失败：${(e as Error).message}`);
      setBusy(false);
    }
  };
  return (
    <Dialog title="举报内容" onClose={onClose} testId="report-dialog">
      <div className="stack">
        <blockquote className="report-quote">{content.slice(0, 220) || "（当前世界）"}</blockquote>
        <div className="chips" role="radiogroup" aria-label="举报原因">
          {REASONS.map((r) => (
            <button
              key={r}
              type="button"
              role="radio"
              aria-checked={reason === r}
              className={`chip${reason === r ? " on" : ""}`}
              onClick={() => setReason(r)}
            >
              {r}
            </button>
          ))}
        </div>
        <textarea
          className="textarea"
          placeholder="补充说明（可选）"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={500}
        />
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn ghost" onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            className="btn"
            data-testid="report-submit"
            disabled={busy}
            onClick={() => void submit()}
          >
            {busy ? "提交中…" : "提交举报"}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
