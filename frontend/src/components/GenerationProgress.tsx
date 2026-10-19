"use client";
import { Loom } from "./Loom";
import { GEN_STAGES, type GenState } from "@/hooks/useWorldGeneration";

/** Streaming world-generation visualisation (progress stages + the draft the model is writing). */
export function GenerationProgress({ gen, title = "造化之中" }: { gen: GenState; title?: string }) {
  return (
    <div className="card gen-progress" data-testid="generation-progress">
      <Loom stages={GEN_STAGES} progress={gen.progress} title={title} />
      {gen.draft ? (
        <pre className="gen-draft" aria-label="模型草稿">
          {gen.draft}
          <span className="caret" aria-hidden />
        </pre>
      ) : null}
    </div>
  );
}
