"use client";
/**
 * Model text → Markdown (GFM tables/lists/strikethrough, single newlines kept as line breaks).
 * Raw HTML is never rendered (react-markdown escapes it by default; we also drop html nodes and
 * unsafe link protocols). `streaming` closes dangling ** / * / ` / ``` so a half-written token
 * doesn't flash raw markers or swallow the rest of the text while it streams.
 */
import { memo } from "react";
import ReactMarkdown, { defaultUrlTransform, type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";

const REMARK = [remarkGfm, remarkBreaks];

/** Balance unfinished inline/fence markers in a streaming prefix (display only). */
export function healPartial(src: string): string {
  let s = src;
  const fences = (s.match(/^\s*```/gm) ?? []).length;
  if (fences % 2) return s + "\n```";
  // ignore markers inside inline code when counting
  const plain = s.replace(/`[^`\n]*`/g, "");
  if ((plain.match(/`/g) ?? []).length % 2) s += "`";
  const bold = (plain.match(/\*\*/g) ?? []).length % 2 === 1;
  const singles = plain
    .replace(/\*\*/g, "")
    .replace(/^\s*[*+-]\s/gm, "")
    .replace(/\\\*/g, "");
  if ((singles.match(/\*/g) ?? []).length % 2) s += "*"; // innermost first
  if (bold) s += "**";
  return s;
}

const linkSafe = (url: string) => {
  const u = defaultUrlTransform(url);
  return /^(https?:|mailto:|\/|#)/i.test(u) ? u : "";
};

const components: Components = {
  a: ({ href, children }) => {
    const cite = href?.match(/^#zm-cite-(\d+)$/);
    if (cite)
      return (
        <sup className="cite-ref">
          <a href={href} data-cite={cite[1]} aria-label={`查看出处 ${cite[1]}`}>
            {children}
          </a>
        </sup>
      );
    return (
      <a href={href || undefined} target="_blank" rel="noopener noreferrer nofollow">
        {children}
      </a>
    );
  },
  table: ({ children }) => (
    <div className="md-table">
      <table>{children}</table>
    </div>
  ),
  img: ({ alt }) => (alt ? <span className="faint">[{alt}]</span> : null), // no remote images from model text
};

const inlineComponents: Components = {
  ...components,
  p: ({ children }) => <>{children}</>,
  // inline text often sits inside buttons/cards — never nest interactive links there
  a: ({ children }) => <span className="md-link">{children}</span>,
};

type Props = {
  text: string | null | undefined;
  className?: string;
  streaming?: boolean;
  /** render without block wrappers (for short labels inside existing <p>/<span>) */
  inline?: boolean;
  as?: "div" | "span";
  testId?: string;
};

function MarkdownImpl({ text, className, streaming, inline, as, testId }: Props) {
  const src = streaming ? healPartial(text ?? "") : (text ?? "");
  const Tag = as ?? (inline ? "span" : "div");
  return (
    <Tag
      className={`md${inline ? " md-inline" : ""}${className ? ` ${className}` : ""}`}
      data-testid={testId}
    >
      <ReactMarkdown
        remarkPlugins={REMARK}
        skipHtml
        urlTransform={linkSafe}
        components={inline ? inlineComponents : components}
      >
        {src}
      </ReactMarkdown>
    </Tag>
  );
}

export const Markdown = memo(MarkdownImpl);
