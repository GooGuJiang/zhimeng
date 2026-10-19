"use client";
import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

/** Accessible modal: role=dialog, Esc / backdrop closes, focus moves inside. */
export function Dialog({
  title,
  onClose,
  children,
  wide,
  testId,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
  testId?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("textarea, input, select, button:not([data-close])")?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [onClose]);
  return createPortal(
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={ref}
        className={`dialog card${wide ? " wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        data-testid={testId}
      >
        <div className="card-h">
          <i className="knot" aria-hidden />
          <h2 className="h2">{title}</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭" data-close>
            <X size={16} />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
