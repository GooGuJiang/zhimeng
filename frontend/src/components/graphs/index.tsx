"use client";
/**
 * Lazy, client-only entry points for the graph canvases. React Flow measures the DOM, so it never
 * renders on the server: SSR (and the first hydration pass) shows a sized placeholder instead.
 * Plain React.lazy keeps the OpenUI library free of Next-only APIs (it's also imported by node scripts).
 */
import { Suspense, lazy, useSyncExternalStore, type ComponentProps } from "react";

const RelationFlowLazy = lazy(() => import("./RelationFlow"));
const MapFlowLazy = lazy(() => import("./MapFlow"));

const noop = () => () => {};
function useMounted() {
  return useSyncExternalStore(
    noop,
    () => true,
    () => false,
  );
}

function Placeholder({ height, label }: { height: number; label: string }) {
  return (
    <div className="rf-wrap rf-loading" style={{ height }} aria-busy="true">
      <span>{label}</span>
    </div>
  );
}

export function RelationCanvas(props: ComponentProps<typeof RelationFlowLazy>) {
  const mounted = useMounted();
  const ph = <Placeholder height={props.height ?? 300} label="人物关系图载入中…" />;
  if (!mounted) return ph;
  return (
    <Suspense fallback={ph}>
      <RelationFlowLazy {...props} />
    </Suspense>
  );
}

export function MapCanvas(props: ComponentProps<typeof MapFlowLazy>) {
  const mounted = useMounted();
  const ph = <Placeholder height={props.height ?? 300} label="地图载入中…" />;
  if (!mounted) return ph;
  return (
    <Suspense fallback={ph}>
      <MapFlowLazy {...props} />
    </Suspense>
  );
}
