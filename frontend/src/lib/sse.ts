import { API_BASE, ApiError } from "./api";

export type SSEHandler = (event: string, data: unknown) => void;

/**
 * POST + Server-Sent Events reader (EventSource cannot POST).
 * Resolves when the stream closes; rejects on network/HTTP errors or abort.
 */
export async function streamSSE(
  path: string,
  body: unknown,
  onEvent: SSEHandler,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body ?? {}),
    signal,
  });
  if (!res.ok || !res.body) {
    let msg = `请求失败 (${res.status})`;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : msg;
    } catch {
      /* ignore */
    }
    throw new ApiError(msg, res.status);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  const flush = (block: string) => {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (!line || line.startsWith(":")) continue;
      const idx = line.indexOf(":");
      const field = idx === -1 ? line : line.slice(0, idx);
      const value = idx === -1 ? "" : line.slice(idx + 1).replace(/^ /, "");
      if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    if (!data.length) return;
    const raw = data.join("\n");
    let parsed: unknown = raw;
    try {
      parsed = JSON.parse(raw);
    } catch {
      /* plain text */
    }
    onEvent(event, parsed);
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let sep: RegExpExecArray | null;
    while ((sep = /\r?\n\r?\n/.exec(buf))) {
      flush(buf.slice(0, sep.index));
      buf = buf.slice(sep.index + sep[0].length);
    }
  }
  if (buf.trim()) flush(buf);
}
