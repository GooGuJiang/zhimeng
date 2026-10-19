// Types mirrored from /workspace/zhimeng/API.md (backend contract v1).

export type Mode = "story" | "education";
export type Rating = "all" | "teen" | "mature";

export interface Location {
  id: string;
  name: string;
  description: string;
  x: number;
  y: number;
  connections: string[];
  interactables: string[];
}
export interface Relation {
  target_id: string;
  type: string;
  affinity: number;
  note?: string;
}
export interface Character {
  id: string;
  name: string;
  role: string;
  persona: string;
  goals: string[];
  relations: Relation[];
  location_id: string | null;
  mood: string;
  status: string;
  is_player: boolean;
  avatar_emoji?: string;
}
export interface Item {
  id: string;
  name: string;
  description: string;
  owner_id: string | null;
  quantity: number;
}
export interface KnowledgeCard {
  id: string;
  title: string;
  content: string;
  source?: string;
  turn?: number;
}
export interface WorldState {
  turn: number;
  chapter: number;
  time: string;
  day: number;
  player_location_id: string | null;
  flags: Record<string, unknown>;
  hp: number;
  stats: Record<string, number>;
}
export interface World {
  id: string;
  title: string;
  genre: string;
  tone: string;
  era: string;
  setting: string;
  mode: Mode;
  language: string;
  premise: string;
  initial_conflict: string;
  opening_scene: string;
  player: { name: string; role: string; character_id: string };
  locations: Location[];
  characters: Character[];
  items: Item[];
  knowledge_cards: KnowledgeCard[];
  state: WorldState;
  rating: Rating;
  minor_mode: boolean;
  status: "draft" | "active" | "ended";
  created_at: string;
  updated_at: string;
  source: "llm" | "fallback";
  ai_generated: true;
  ai_label: string;
}
export interface WorldSummary {
  id: string;
  title: string;
  genre: string;
  tone: string;
  mode: Mode;
  turn: number;
  status: World["status"];
  created_at: string;
  updated_at: string;
}
export interface Option {
  id: string;
  text: string;
  hint?: string;
}
export interface WorldEvent {
  id: string;
  world_id: string;
  type: "offscreen" | "world" | "player" | "injected" | "npc_action";
  summary: string;
  actor_ids: string[];
  location_id: string | null;
  turn: number;
  chapter: number;
  impact: string;
  timestamp: string;
  in_world_time: string;
  seen: boolean;
}
export interface Citation {
  fact_id: string;
  content: string;
  turn: number;
  chapter: number;
  kind: string;
  score: number;
  source: string;
}
export interface Turn {
  id: string;
  world_id: string;
  index: number;
  chapter: number;
  action: string;
  narration: string;
  options: Option[];
  events: WorldEvent[];
  facts: string[];
  asset_ids: string[];
  key_scene: boolean;
  created_at: string;
  ai_generated: true;
  ai_label: string;
}
export interface Asset {
  id: string;
  world_id: string;
  type: "image" | "audio";
  url: string;
  turn_id: string | null;
  prompt: string;
  source: "dashscope" | "fallback";
  created_at: string;
}
export interface SafetyResult {
  allowed: boolean;
  blocked: boolean;
  crisis: boolean;
  categories: string[];
  rating: Rating;
  message: string | null;
  filtered_text?: string;
}
export type UIType =
  | "status_panel"
  | "relationship_graph"
  | "inventory"
  | "map"
  | "event_feed"
  | "knowledge_cards"
  | "choice_list";
export interface UIAction {
  id: string;
  label: string;
  kind: "turn" | "god_inject" | "query" | "navigate";
  payload: Record<string, unknown>;
}
export interface UIComponent {
  id: string;
  type: UIType;
  title: string;
  priority: number;
  layout: { area: "main" | "side" | "bottom"; size: "sm" | "md" | "lg" };
  props: Record<string, unknown>;
  actions: UIAction[];
  openui?: string;
}
export interface Progress {
  stage: string;
  message: string;
  pct: number;
}
export interface GenerateWorldRequest {
  prompt: string;
  genre?: string;
  tone?: string;
  length?: "short" | "medium" | "long";
  language?: string;
  mode?: Mode;
  source_text?: string | null;
  minor_mode?: boolean;
  rating?: Rating;
}
export interface NpcView {
  character: Character;
  trajectory: {
    turn: number;
    location_id: string | null;
    location_name: string;
    action: string;
    mood: string;
    timestamp: string;
  }[];
  recent_events: WorldEvent[];
  memories: string[];
}
export interface MemoryEntry {
  id: string;
  content: string;
  kind: "fact" | "event" | "summary" | "injected" | "setting";
  turn: number;
  chapter: number;
  source: string;
  created_at: string;
}
export interface EducationSummary {
  title: string;
  key_points: string[];
  cards: KnowledgeCard[];
  timeline: { turn: number; summary: string }[];
  quiz: { question: string; options: string[]; answer_index: number; explanation: string }[];
  reflection: string;
  ai_label: string;
}
export interface Poster {
  title: string;
  subtitle: string;
  tagline: string;
  summary: string;
  ending: string | null;
  characters: { name: string; role: string; emoji: string }[];
  stats: { turns: number; chapters: number; events: number };
  image_url: string | null;
  theme: { primary: string; secondary: string; background: string };
  qr_text: string;
  ai_label: string;
  safety_label: string;
  rating: Rating;
}
