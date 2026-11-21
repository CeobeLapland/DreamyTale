export type Language = "zh-CN" | "en";
export type ActionType =
  | "control" | "find_scene" | "question" | "click"
  | "search_text" | "highlight" | "other";

export type JobStatus =
  | "queued" | "running" | "completed" | "failed" | "cancelled";

export type JobStage =
  | "ingest" | "ocr" | "vlm" | "story" | "scene"
  | "video" | "tts" | "compose" | "index";

export type BBoxPx = [number, number, number, number];

export interface TextSpan {
  span_id: string;
  page_index: number;
  text: string;
  bbox_px: BBoxPx;
  source: "embedded_pdf" | "ocr" | "manual" | "vlm";
}

export interface Hotspot {
  hotspot_id: string;
  page_index: number;
  label: string;
  bbox_px: BBoxPx;
  description: string;
  source: "pdf_annotation" | "vlm" | "manual";
}

export interface ScriptAction {
  action_id: string;
  type: ActionType;
  text: string;
  mandatory: boolean;
  target: string | null;
}

export interface ScriptStep {
  number: number;
  instruction: string;
  mandatory: boolean;
  audio_path: string;
  actions: ScriptAction[];
}

export interface BookPage {
  index: number;
  image_path: string;
  text: string;
  text_source: "embedded_pdf" | "ocr" | "manual";
  width_pt: number;
  height_pt: number;
  width_px: number;
  height_px: number;
  text_spans: TextSpan[];
  hotspots: Hotspot[];
}

export interface BookPackage {
  schema_version: string;
  book_id: string;
  source_name: string;
  title: string;
  language: Language;
  pdf_path: string;
  script_path: string;
  page_count: number;
  pages: BookPage[];
  steps: ScriptStep[];
  click_targets: string[];
}

export interface BookSummary {
  book_id: string;
  title: string;
  source_name: string;
  language: Language;
  page_count: number;
}

export interface Job {
  job_id: string;
  book_id: string;
  status: JobStatus;
  stage: JobStage;
  progress: number;
  created_at: string;
  updated_at: string;
  error: string | null;
}

export interface QARequest {
  book_id: string;
  page_index: number;
  current_time_ms: number;
  hotspot_id: string | null;
  question_text: string | null;
  audio_path: string | null;
}

export interface QAResponse {
  request_id: string;
  answer_text: string;
  page_index: number;
  scene_id: string | null;
  evidence_span_ids: string[];
  answer_audio_path: string | null;
  latency_ms: number;
  status: string;
}

export interface ApiError {
  error: {
    code: string;
    message: string;
    details?: string[];
  };
}