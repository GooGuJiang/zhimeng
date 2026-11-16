"use client";
/**
 * 剧情脉络: a tree of story lines. The player can return to a past point and take another path
 * when the backend supports POST /branches/rewind; otherwise the tree is a read-only single line.
 */
import { useState } from "react";
import { GitFork, RotateCcw } from "lucide-react";
import { Dialog } from "@/components/Dialog";
import { lineCount, walkTree, type BranchNode, type BranchTree } from "@/lib/branches";

export function BranchStrip({
  tree,
  onOpen,
}: {
  tree: BranchTree;
  onOpen: () => void;
}) {
  const walked = walkTree(tree.nodes);
  const current = walked.filter((x) => x.node.line_id === currentLine(tree) || x.node.id === tree.current_node_id);
  const nLines = lineCount(tree);
  return (
    <div className="branch-strip" data-testid="branch-strip">
      <ol className="branch-strip-line" aria-label="当前这条故事线">
        {current.slice(0, 8).map(({ node }) => (
          <li key={node.id} className={node.id === tree.current_node_id ? "on" : ""}>
            <span className="branch-pip" />
            <span className="branch-pip-label">{node.index === 0 ? "开局" : truncate(node.action || node.summary, 10)}</span>
          </li>
        ))}
      </ol>
      <button type="button" className="btn sm ghost" data-testid="branch-open" onClick={onOpen}>
        <GitFork size={14} aria-hidden />
        剧情脉络{nLines > 1 ? ` · ${nLines} 条线` : ""}
      </button>
    </div>
  );
}

export function BranchDialog({
  tree,
  supported,
  loading,
  error,
  rewinding,
  busy,
  onClose,
  onRetry,
  onRewind,
}: {
  tree: BranchTree;
  supported: boolean;
  loading?: boolean;
  error?: string | null;
  rewinding?: boolean;
  busy?: boolean;
  onClose: () => void;
  onRetry: () => void;
  onRewind: (node: BranchNode) => Promise<boolean>;
}) {
  const [pending, setPending] = useState<BranchNode | null>(null);
  const [working, setWorking] = useState(false);
  const walked = walkTree(tree.nodes);
  const nLines = lineCount(tree);

  const confirm = async () => {
    if (!pending || working) return;
    setWorking(true);
    const ok = await onRewind(pending);
    setWorking(false);
    if (ok) {
      setPending(null);
      onClose();
    }
  };

  return (
    <Dialog title="剧情脉络" onClose={onClose} wide testId="branch-view">
      <p className="branch-lead">
        {nLines > 1
          ? `已经走出 ${nLines} 条故事线。这里能看见你走过的每一条路。想改主意时，可以回到其中一步，另选一条。`
          : "一路走来的选择会留在这里。走出第二条路之后，就能并排看见不同的走向。"}
      </p>
      {loading && !tree.nodes.length ? <div className="skel" style={{ height: 120 }} /> : null}
      {error ? (
        <div className="notice warn row" role="alert">
          <span style={{ flex: 1 }}>{error}</span>
          <button type="button" className="btn sm" data-testid="branch-retry" onClick={onRetry}>
            <RotateCcw size={14} aria-hidden /> 重试
          </button>
        </div>
      ) : null}
      {!supported ? (
        <p className="branch-note" data-testid="branch-readonly">
          现在可以回顾已经走过的路。从某一步分出另一条线，还要等故事引擎就绪之后才能用。
        </p>
      ) : null}
      <ol className="branch-tree" data-testid="branch-tree">
        {walked.map(({ node, depth }) => {
          const here = node.id === tree.current_node_id;
          const can = supported && !here && !busy && !rewinding;
          return (
            <li
              key={node.id}
              className={`branch-node${here ? " current" : ""}`}
              style={{ paddingLeft: 8 + depth * 22 }}
              data-testid={here ? "branch-node-current" : "branch-node"}
              data-index={node.index}
            >
              <span className="branch-dot" aria-hidden />
              <div className="branch-body">
                <div className="branch-title">
                  {node.index === 0 ? "开局" : node.action || "一次选择"}
                  {here ? <span className="tag gold">你在这里</span> : null}
                </div>
                {node.summary ? <div className="branch-summary">{node.summary}</div> : null}
                {can ? (
                  <button
                    type="button"
                    className="linkish"
                    data-testid="branch-rewind"
                    onClick={() => setPending(node)}
                  >
                    回到这里，另选一条
                  </button>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
      {pending ? (
        <div className="branch-confirm" data-testid="branch-confirm" role="alertdialog" aria-label="确认回到这一步">
          <p>
            回到「{pending.index === 0 ? "开局" : pending.action || "这一步"}」之后，将从这里走出一条新的故事线。已经走过的路会留在脉络里，不会消失。
          </p>
          <div className="row" style={{ gap: 8, justifyContent: "flex-end" }}>
            <button type="button" className="btn sm ghost" onClick={() => setPending(null)} disabled={working}>
              再想想
            </button>
            <button type="button" className="btn sm" data-testid="branch-confirm-ok" onClick={() => void confirm()} disabled={working}>
              {working ? "正在回去…" : "回到这里"}
            </button>
          </div>
        </div>
      ) : null}
    </Dialog>
  );
}

function currentLine(tree: BranchTree): string | undefined {
  return tree.lines.find((l) => l.current)?.id ?? tree.nodes.find((n) => n.id === tree.current_node_id)?.line_id;
}

function truncate(s: string, n: number) {
  return s.length <= n ? s : `${s.slice(0, n)}…`;
}
