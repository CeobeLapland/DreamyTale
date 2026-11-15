/**
 * 前后端 WebSocket 事件契约。
 * 一条连接传所有东西；音频、视频帧走二进制，其余走 JSON。
 * 改这里之前先改 docs/ARCH.md 的七条链路。
 */

export type AgeBand = "3-5" | "6-8";
export type Mode = "theater" | "bedtime" | "judge";

/* ---------- 客户端 → 服务端 ---------- */

export type ClientEvent =
  | { type: "session.start"; bookId: string; ageBand: AgeBand; mode: Mode }
  | { type: "session.end"; reason: "done" | "quit" }
  | { type: "page.set"; pageId: string; corners: [number, number][]; confidence: number }
  | { type: "touch.point"; pageId: string; x: number; y: number; t: number }
  | { type: "voice.start"; pageId: string }
  | { type: "voice.stop" }
  | { type: "choice.select"; branchId: string; optionId: string }
  | { type: "mode.set"; mode: Mode }
  | { type: "debug.subscribe"; on: boolean };

/* ---------- 服务端 → 客户端 ---------- */

export type ServerEvent =
  | { type: "session.ready"; sessionId: string; bookId: string }
  | { type: "page.loading"; pageId: string }
  | { type: "page.ready"; pageId: string; assetUrl: string; hotspots: string[] }
  | { type: "touch.resolved"; hotspotId: string | null; candidates: TouchCandidate[] }
  | { type: "asr.partial"; text: string }
  | { type: "asr.final"; text: string; confidence: number }
  | { type: "intent.routed"; intent: "in_book" | "video" | "out_of_book" | "chitchat" }
  | { type: "answer.delta"; text: string }
  | { type: "answer.done"; text: string; citations: Citation[]; refused: boolean }
  | { type: "stage.start"; stage: StageName; budgetMs: number }
  | { type: "stage.end"; stage: StageName; ms: number; ok: boolean }
  | { type: "agent.event"; agent: AgentName; phase: "start" | "end" | "retry" | "blocked"; ms?: number; note?: string }
  | { type: "degrade"; from: string; to: string; reason: string }
  | { type: "safety.blocked"; scope: "input" | "output"; reason: string }
  | { type: "error"; code: string; message: string };

export interface TouchCandidate {
  hotspotId: string;
  label: string;
  score: number;
}

export interface Citation {
  pageId: string;
  /** 页面归一化坐标 [x, y, w, h]，用于空间高亮 */
  bbox?: [number, number, number, number];
  /** 视频秒数，用于故事地图跳转 */
  timestamp?: number;
  quote?: string;
}

export type StageName =
  | "page_understanding"
  | "story_graph"
  | "script"
  | "puppet_render"
  | "highlight_shot"
  | "tts"
  | "safety"
  | "continuity";

export type AgentName =
  | "producer"
  | "playwright"
  | "director"
  | "puppeteer"
  | "voice"
  | "supervisor"
  | "knowledge"
  | "safety";

/* ---------- 二进制通道 ---------- */

export type BinaryChannel =
  | { kind: "audio_in"; seq: number; sampleRate: 16000 }
  | { kind: "tts_out"; seq: number; sampleRate: 24000 }
  | { kind: "frame_in"; pageId: string };
