/**
 * 前端类型定义，与 docs/DATA_CONTRACT.md v2.0.0 一一对应。
 *
 * 改动规则：契约破坏性变更必须三人确认，本文件与 backend/app 与 contracts/models.py
 * 同步更新。字段含义看 DATA_CONTRACT.md 对应小节。
 *
 * §5 书与题目 | §6 知识层 | §7 人工修正 | §8 生成产物 | §9 交互协议 | §10 Job
 * §11 能力报告 | §12 评测
 */

export const SCHEMA_VERSION = "2.0.0";

/* ------------------------------------------------------------------ §1 基础 */

export type Language = "zh-CN" | "en";
export type ContentType = "narrative" | "expository" | "mixed";
export type SourceType = "pdf" | "photo" | "scan" | "mixed";
export type BookStatus =
  | "draft" | "ingested" | "understood" | "generated" | "reviewed" | "ready" | "failed";
export type TextSource = "embedded_pdf" | "ocr" | "vlm" | "manual" | "mixed" | "none";
export type BlockType =
  | "title" | "body" | "caption" | "sfx" | "note" | "header" | "footer" | "other";
export type SpanSource = "embedded_pdf" | "ocr" | "vlm" | "manual";
export type HotspotSource = "pdf_annotation" | "vlm" | "auto" | "manual";
export type Status = "active" | "superseded";

export type BBoxPx = [number, number, number, number];

/* ------------------------------------------------------------- §5 书与题目 */

export interface RenderInfo {
  dpi: number;
  renderer: string;
  version: string;
}

export interface StyleBible {
  reference_pages: number[];
  palette: string[];
  line: string | null;
  texture: string | null;
  negative_prompts: string[];
}

export interface Rights {
  license: string;
  note: string | null;
}

export interface PageBlock {
  block_id: string;
  page_index: number;
  type: BlockType;
  text: string;
  bbox_px: BBoxPx;
  source: SpanSource;
  confidence: number;
  reading_order: number;
  lang: string | null;
}

export interface TextSpan {
  span_id: string;
  page_index: number;
  text: string;
  bbox_px: BBoxPx;
  source: SpanSource;
  confidence: number;
  version: number;
  status: Status;
  hash: string;
}

export interface Hotspot {
  hotspot_id: string;
  page_index: number;
  label: string;
  bbox_px: BBoxPx;
  description: string;
  source: HotspotSource;
  confidence: number;
  version: number;
  status: Status;
  hash: string;
}

export interface Page {
  index: number;
  image_path: string;
  width_px: number;
  height_px: number;
  width_pt: number | null;
  height_pt: number | null;
  text: string;
  text_source: TextSource;
  text_confidence: number | null;
  language: string | null;
  blocks: PageBlock[];
  text_spans: TextSpan[];
  hotspots: Hotspot[];
  sha256: string;
  render: RenderInfo | null;
}

export interface BookPackage {
  schema_version: typeof SCHEMA_VERSION;
  book_id: string;
  source_name: string;
  title: string;
  authors: string[];
  language: Language;
  languages: string[];
  content_type: ContentType;
  source_type: SourceType;
  source_path: string;
  page_count: number;
  pages: Page[];
  style: StyleBible | null;
  rights: Rights | null;
  status: BookStatus;
  query_set_ids: string[];
  capabilities_path: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface BookSummary {
  book_id: string;
  title: string;
  source_name: string;
  language: Language;
  content_type: ContentType;
  page_count: number;
  status: BookStatus;
}

/* ----------------------------------------------------------------- §5 题目 */

export type QueryKind = "control" | "seek" | "search" | "highlight" | "click" | "qa";
export type QueryLang = "zh" | "en" | "mixed";
export type ControlAction = "play" | "pause" | "resume" | "stop";

export interface QueryAction {
  action_id: string;
  kind: QueryKind;
  text: string;
  mandatory: boolean;
  control_action: ControlAction | null;
  seek_query: string | null;
  search_text: string | null;
  highlight_text: string | null;
  target: string | null;
  expected: Record<string, unknown> | null;
}

export interface QueryItem {
  query_id: string;
  number: number;
  instruction: string;
  audio_path: string | null;
  mandatory: boolean;
  lang: QueryLang;
  actions: QueryAction[];
  expected: Record<string, unknown> | null;
}

export interface QuerySet {
  schema_version: typeof SCHEMA_VERSION;
  query_set_id: string;
  book_id: string | null;
  name: string;
  language: QueryLang;
  source: "official_script" | "human" | "auto";
  items: QueryItem[];
}

/* --------------------------------------------------------------- §8 生成产物 */

export interface Subtitle {
  text: string;
  start_ms: number;
  end_ms: number;
  lang: string;
}

export interface SceneObject {
  entity: string;
  bbox_px: BBoxPx;
  start_ms: number;
  end_ms: number;
}

export type GenerationStatus = "ok" | "fallback" | "failed";

/** 播放器消费的最小单元。start_ms/end_ms 相对所属页面，不是整本书。 */
export interface Scene {
  scene_id: string;
  page_index: number;
  beat_id: string;
  start_ms: number;
  end_ms: number;
  caption: string;
  aliases: string[];
  entities: string[];
  action: string;
  camera: string;
  prompt: string;
  negative_prompt: string;
  keyframe_path: string;
  video_path: string;
  thumbnail_path: string;
  subtitles: Subtitle[];
  objects: SceneObject[];
  hotspot_ids: string[];
  seed: number;
  style_score: number | null;
  source: "auto" | "human";
  status: GenerationStatus;
}

export interface PageMap {
  page_index: number;
  scene_ids: string[];
  start_ms: number;
  end_ms: number;
}

export interface ScenePlan {
  schema_version: typeof SCHEMA_VERSION;
  book_id: string;
  plan_version: number;
  page_map: PageMap[];
  scenes: Scene[];
  model: string;
  prompt_version: string;
  source_hash: string;
  created_at: string;
}

/** 整本时间轴：pages[].start_ms/end_ms 是绝对时间。 */
export interface GenerationPage {
  page_index: number;
  video_path: string;
  start_ms: number;
  end_ms: number;
  scene_ids: string[];
  thumbnail_path: string | null;
}

export interface BookGenerationResult {
  schema_version: typeof SCHEMA_VERSION;
  book_id: string;
  generation_version: number;
  status: string;
  pages: GenerationPage[];
  full_video_path: string | null;
  subtitle_paths: string[];
  audio_paths: string[];
  timeline_path: string | null;
  manifest_path: string | null;
  metrics: {
    style_score_avg: number | null;
    fallback_pages: number;
    qa_cards: number;
    duration_ms: number;
  } | null;
  model_versions: Record<string, string>;
  prompt_versions: Record<string, string>;
  created_at: string;
}

/* --------------------------------------------------------------- §9 交互协议 */

export type InteractionKind =
  | "auto" | "control" | "seek" | "search" | "highlight" | "click" | "qa";
export type ActionType =
  | "play" | "pause" | "resume" | "stop" | "seek" | "highlight" | "show_card" | "none";
export type AnswerTier = "strong" | "weak" | "quote" | "guide";

export interface ClickPoint {
  x_px: number | null;
  y_px: number | null;
  x_norm: number | null;
  y_norm: number | null;
}

export interface InteractionInput {
  text: string | null;
  audio_path: string | null;
  audio_url: string | null;
  language: string | null;
  page_index: number | null;
  current_time_ms: number | null;
  click: ClickPoint | null;
}

export interface InteractionContext {
  last_page_index: number | null;
  last_scene_id: string | null;
  last_entities: string[];
  last_lang: string | null;
  history_turn_ids: string[];
}

export interface InteractionRequest {
  request_id?: string | null;
  book_id: string;
  session_id: string;
  kind: InteractionKind;
  input: InteractionInput;
  context?: InteractionContext;
}

export interface InteractionAction {
  type: ActionType;
  scene_id: string | null;
  time_ms: number | null;
  span_ids: string[];
  hotspot_id: string | null;
}

export interface Evidence {
  page_index: number;
  bbox_px: BBoxPx | null;
  span_id: string | null;
  fact_id: string | null;
  quote: string | null;
}

export interface AnswerPayload {
  text: string;
  audio_path: string | null;
  language: string | null;
  tier: AnswerTier | null;
  evidence: Evidence[];
  scene_id: string | null;
  time_ms: number | null;
}

export interface LatencyBreakdown {
  asr: number | null;
  route: number | null;
  retrieve: number | null;
  generate: number | null;
  tts: number | null;
  total: number;
}

export interface ErrorInfo {
  code: string;
  message: string;
  retryable: boolean;
}

export interface InteractionResponse {
  request_id: string;
  book_id: string;
  session_id: string;
  kind: InteractionKind;
  action: InteractionAction;
  answer: AnswerPayload | null;
  latency: LatencyBreakdown;
  status: "ok" | "fallback" | "error";
  error: ErrorInfo | null;
}

/** 语义对话历史（多模态：语音 + 图片）。 */
export interface Turn {
  turn_id: string;
  session_id: string;
  book_id: string;
  ts: string;
  input_audio: string | null;
  input_text: string | null;
  input_image: string | null;
  kind: InteractionKind;
  tier: AnswerTier | null;
  reply_text: string | null;
  reply_audio: string | null;
  evidence: Evidence[];
  video_time: number | null;
  latency: LatencyBreakdown | null;
}

/* ------------------------------------------------------------------ §10 Job */

export type JobStatus =
  | "queued" | "running" | "completed" | "failed" | "cancelled" | "degraded";
export type JobStage =
  | "ingest" | "ocr" | "vlm" | "story" | "scene" | "video" | "tts" | "compose" | "index";

export interface Job {
  job_id: string;
  book_id: string;
  status: JobStatus;
  stage: JobStage;
  progress: number;
  created_at: string;
  updated_at: string;
  error: string | null;
  error_code: string | null;
  degraded: boolean;
  retryable: boolean;
  manifest_path: string | null;
}

/* ---------------------------------------------------------- §11 能力报告 */

export interface CapabilityReport {
  schema_version: typeof SCHEMA_VERSION;
  book_id: string;
  generated_at: string;
  content_type: ContentType;
  languages: string[];
  pages_total: number;
  pages_with_text: number;
  ocr_pages: number;
  blocks: number;
  hotspots: number;
  scenes: number;
  videos: number;
  qa_cards: number;
  coverage: { text_search: number; video: number; qa: number };
  needs_review: { target_type: string; target_id: string; reason: string }[];
  limitations: string[];
  status: string;
}

/* ----------------------------------------------------------- §7 人工修正 */

export type AnnotationTargetType =
  | "page_block" | "text_span" | "hotspot" | "page_fact" | "qa_card" | "alias" | "scene" | "book";

export interface Annotation {
  annotation_id: string;
  target_type: AnnotationTargetType;
  target_id: string;
  field: string;
  value: unknown;
  old_value: unknown;
  source: "human";
  reviewer: string;
  created_at: string;
  status: Status;
  reason: string | null;
  hash: string;
}

export interface ReviewItem {
  review_id: string;
  target_type: AnnotationTargetType;
  target_id: string;
  reason: "low_confidence" | "conflict" | "missing" | "generated";
  status: "pending" | "accepted" | "rejected" | "edited";
  assignee: string | null;
  created_at: string;
  resolved_at: string | null;
  notes: string | null;
}

/* ------------------------------------------------------------- §6 知识层 */

export interface QaCard {
  card_id: string;
  book_id: string;
  kind: "qa";
  intent: string;
  scope: "page" | "book" | "video";
  langs: string[];
  question_canonical: string;
  variants: string[];
  entities: string[];
  answers: Record<string, { strong: string; weak: string; guide: string }>;
  evidence: Evidence[];
  video_anchor: { scene_id: string; start_ms: number; end_ms: number } | null;
  priority: number;
  source: "auto" | "human";
  version: number;
  status: Status;
  hash: string;
  created_at: string;
}

export interface ApiError {
  error: {
    code: string;
    message: string;
    details?: string[];
  };
}
