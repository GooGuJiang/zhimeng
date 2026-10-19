"use client";
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

type ToastFn = (msg: string) => void;
const Ctx = createContext<ToastFn>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [msg, setMsg] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const show = useCallback<ToastFn>((m) => {
    setMsg(m);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setMsg(null), 2800);
  }, []);
  return (
    <Ctx.Provider value={show}>
      {children}
      {msg ? (
        <div className="toast" role="status" aria-live="polite" data-testid="toast">
          {msg}
        </div>
      ) : null}
    </Ctx.Provider>
  );
}

export const useToast = () => useContext(Ctx);
