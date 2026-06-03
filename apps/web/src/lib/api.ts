export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

export type GenerationRunRequest = {
  generation_mode?: "viral_rewrite" | "template_fusion" | "auto_mix";
  asset_collection_id?: string | null;
  product_name: string;
  category: string;
  selling_points: string[];
  target_audience: string;
  price_offer: string;
  material_notes: string;
  creative_goal: string;
  reference_style: string;
  visual_style: string;
  duration_seconds: number;
  platform: string;
  source_assets?: SourceAssetInput[];
  asset_ids?: string[];
  asset_slice_ids?: string[];
  reference_video_id?: string | null;
  template_id?: string | null;
  factor_ids?: string[];
  auto_retrieve_assets?: boolean;
  auto_retrieve_factors?: boolean;
};

export type AssemblyRequest = {
  aspect_ratio: "9:16" | "16:9" | "1:1";
  include_bgm: boolean;
};

export type SourceAssetInput = {
  filename: string;
  content_type: string;
  asset_kind: string;
  size_bytes: number;
  description?: string;
};

export type AgentStep = {
  id: string;
  run_id: string;
  order_index: number;
  agent_name: string;
  status: string;
  provider: string;
  model: string;
  execution_mode: "real" | "mock_missing_config" | "real_failed" | string;
  provider_status: "configured" | "missing_config" | "error" | string;
  provider_message: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  duration_ms: number;
  fallback: string;
  error?: string | null;
  created_at: string;
};

export type AgentSubstep = {
  substep_name: string;
  status: string;
  provider: string;
  model: string;
  execution_mode: "real" | "mock_missing_config" | "real_failed" | string;
  provider_status: "configured" | "missing_config" | "error" | string;
  provider_message: string;
  input_summary: Record<string, unknown>;
  output_summary: Record<string, unknown>;
  duration_ms: number;
  error?: string | null;
};

export type ExperimentTraceStep = {
  agent_name: string;
  status: string;
  provider: string;
  model: string;
  execution_mode?: "real" | "mock_missing_config" | "real_failed" | string;
  provider_status?: "configured" | "missing_config" | "error" | string;
  provider_message?: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  duration_ms: number;
  fallback: string;
  error?: string | null;
};

export type MediaArtifact = {
  id: string;
  run_id: string;
  order_index: number;
  artifact_type: string;
  title: string;
  provider: string;
  status: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type SourceAsset = {
  id: string;
  run_id: string;
  order_index: number;
  filename: string;
  content_type: string;
  asset_kind: string;
  size_bytes: number;
  storage_path: string;
  description: string;
  metadata_payload: Record<string, unknown>;
  created_at: string;
};

export type RunEvent = {
  id: string;
  run_id: string;
  order_index: number;
  event_type: string;
  agent_name?: string | null;
  status: string;
  message: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type StoryboardShot = {
  shot_id: string;
  order_index: number;
  duration_seconds: number;
  beat: string;
  visual_description: string;
  camera_motion: string;
  voiceover: string;
  subtitle: string;
  tts_line?: string;
  bgm_cue?: string;
  linked_factor_keys?: string[];
  image_prompt: string;
  video_prompt: string;
  selected_asset_slice_id?: string | null;
};

export type TimelineClip = {
  shot_id: string;
  order_index?: number | null;
  beat?: string | null;
  subtitle?: string | null;
  voiceover?: string | null;
  duration_seconds?: number | null;
  time_range?: string | null;
  artifact_id?: string | null;
  artifact_type?: string | null;
  artifact_status?: string | null;
  task_id?: string | null;
  task_status?: string | null;
  video_url?: string | null;
  last_frame_url?: string | null;
  prompt?: string | null;
  failure_reason?: string | null;
  mock_reason?: string | null;
};

export type TimelineSegment = TimelineClip & {
  start_seconds?: number | null;
  end_seconds?: number | null;
  source?: "draft_video" | "replacement_clip" | string | null;
  source_label?: string | null;
  draft_video_url?: string | null;
  replacement_video_url?: string | null;
  draft_prompt?: string | null;
};

export type ViralFactorBoardItem = {
  factor_key: string;
  name: string;
  category: string;
  reason: string;
  expected_effect: string;
  confidence: number;
  linked_shot_ids: string[];
  source: string;
};

export type GenerationRun = {
  run_id: string;
  status: string;
  summary: string;
  request_payload: GenerationRunRequest;
  assets: SourceAsset[];
  agents: AgentStep[];
  events: RunEvent[];
  strategy: {
    generation_mode?: string;
    product_angle?: string;
    hook?: string;
    audience_pain?: string;
    source_asset_summary?: string;
    retrieval_evidence?: Array<{
      type?: string;
      title?: string;
      score?: number;
      reason?: string;
      usable_for?: string[];
      matched_slices?: Array<Record<string, unknown>>;
    }>;
    asset_usage_plan?: Array<{
      shot_id?: string;
      asset_title?: string;
      usage?: string;
      reason?: string;
    }>;
    factor_selection_reason?: Array<{
      factor_key?: string;
      name?: string;
      category?: string;
      source?: string;
      reason?: string;
    }>;
    selling_point_order?: string[];
    factor_coverage?: number;
    factor_board?: ViralFactorBoardItem[];
    content_rhythm?: string[];
    selected_factors?: ViralFactorBoardItem[];
    risk_notes?: string[];
  };
  viral_factors: ViralFactorBoardItem[];
  script: {
    title?: string;
    narrative?: string;
    voiceover_lines?: string[];
    subtitle_lines?: string[];
    tts_lines?: string[];
    bgm_plan?: string;
    duration_seconds?: number;
    visual_style?: string;
  };
  storyboard: StoryboardShot[];
  preview: {
    mode?: string;
    aspect_ratio?: string;
    total_duration_seconds?: number;
    source_asset_count?: number;
    cover_text?: string;
    cover_image_url?: string | null;
    cover_image_status?: string | null;
    video_url?: string | null;
    video_task_id?: string | null;
    video_task_status?: string | null;
    draft_video_url?: string | null;
    draft_video_status?: string | null;
    replacement_clip_status?: string | null;
    assembled_video_url?: string | null;
    assembled_duration_seconds?: number | null;
    assembled_resolution?: string | null;
    assembled_aspect_ratio?: string | null;
    assembled_has_audio?: boolean | null;
    assembled_bgm_status?: string | null;
    assembled_tts_status?: string | null;
    assembled_exports?: Record<string, string>;
    assembly_status?: string | null;
    assembly_failure_reason?: string | null;
    active_export_profile?: string | null;
    planned_duration_seconds?: number | null;
    requested_provider_duration_seconds?: number | null;
    provider_duration_seconds?: number | null;
    voice_track?: Record<string, unknown>;
    subtitle_track?: Record<string, unknown>;
    bgm_plan?: Record<string, unknown>;
    timeline?: Array<{
      shot_id: string;
      time_range: string;
      beat: string;
      caption: string;
      visual: string;
    }>;
    timeline_clips?: TimelineClip[];
    timeline_segments?: TimelineSegment[];
    active_segment_sources?: Record<string, string>;
  };
  export_manifest: Record<string, unknown>;
  artifacts: MediaArtifact[];
  compliance: {
    passed?: boolean;
    checks?: Array<{ name: string; status: string; note: string }>;
    final_delivery?: string;
  };
  error_message?: string | null;
  created_at: string;
  updated_at: string;
};

export type AssetSlice = {
  id: string;
  asset_id: string;
  order_index: number;
  slice_type: string;
  start_seconds: number;
  end_seconds: number;
  summary: string;
  features: Record<string, unknown>;
  usable_for: string;
  source_frame_path: string;
  is_pinned: boolean;
  created_at: string;
};

export type AssetTag = {
  id: string;
  asset_id: string;
  name: string;
  tag_type: string;
  confidence: number;
  source: string;
  created_at: string;
};

export type AssetEmbedding = {
  id: string;
  asset_id: string;
  model: string;
  vector: number[];
  created_at: string;
};

export type AssetLibraryItem = {
  id: string;
  collection_id?: string | null;
  filename: string;
  content_type: string;
  asset_kind: string;
  category: string;
  size_bytes: number;
  storage_path: string;
  description: string;
  analysis_status: string;
  provider_status: string;
  provider_message: string;
  analysis: {
    summary?: string;
    product_subject?: string;
    category?: string;
    colors?: string[];
    material?: string;
    materials?: string[];
    visible_details?: string[];
    scale_cues?: string[];
    usage_scenes?: string[];
    risk_tags?: string[];
    recommended_usage?: string[];
    retrieval_text?: string;
    tags?: string[];
  };
  slices: AssetSlice[];
  tags: AssetTag[];
  embedding?: AssetEmbedding | null;
  created_at: string;
  updated_at: string;
};

export type AssetCollection = {
  id: string;
  product_name: string;
  category: string;
  description: string;
  usage_notes: string;
  status: string;
  summary: string;
  coverage: Record<string, unknown>;
  tags: string[];
  assets: AssetLibraryItem[];
  created_at: string;
  updated_at: string;
};

export type AssetSearchResult = {
  collection?: {
    collection_id?: string;
    product_name?: string;
    category?: string;
    status?: string;
    asset_count?: number;
  } | null;
  asset: AssetLibraryItem;
  score: number;
  retrieval_mode: string;
  matched_tags: string[];
  matched_slices: Array<{
    slice_id: string;
    order_index: number;
    slice_type: string;
    start_seconds: number;
    end_seconds: number;
    summary: string;
    features: Record<string, unknown>;
    usable_for?: string | null;
    source_frame_path?: string;
    is_pinned?: boolean;
    score?: number;
    reason?: string;
  }>;
  usable_for: string[];
  reason: string;
};

export type ViralVideoAnalysis = {
  id: string;
  title: string;
  source_url: string;
  category: string;
  source_statement: string;
  analysis: Record<string, unknown> & {
    source?: {
      reference_id?: string;
      platform?: string;
      source_url?: string;
      category?: string;
      product_type?: string;
      country?: string;
      language?: string;
      metrics?: Record<string, unknown>;
      published_at?: string;
      thumbnail_url?: string;
      source_statement?: string;
      notes?: string;
    };
    factor_board?: ViralFactorBoardItem[];
    template_strategy?: string;
    hook_method?: string;
    selling_point_order?: string[];
    storyboard_structure?: Array<Record<string, unknown>>;
    visual_style?: string;
    caption_style?: string;
    audio_style?: string;
    cta_pattern?: string;
    risk_notes?: string[];
    compliance_statement?: string;
  };
  created_at: string;
};

export type ViralFactor = {
  id: string;
  factor_key: string;
  name: string;
  category: string;
  source: string;
  description: string;
  metadata_payload: Partial<ViralFactorBoardItem> & Record<string, unknown>;
  created_at: string;
};

export type CreativeTemplate = {
  id: string;
  name: string;
  category: string;
  strategy: string;
  factor_keys: string[];
  structure: Record<string, unknown>;
  created_at: string;
};

export type CreativeTemplateBuildRequest = {
  name?: string;
  category?: string;
  reference_ids: string[];
  notes?: string;
};

export type ExperimentAnalysis = {
  experiment_id: string;
  title: string;
  status: string;
  summary: string;
  winner_run_id?: string | null;
  input_payload: Record<string, unknown>;
  result: {
    mode?: string;
    winner_label?: string;
    variants?: Array<{ run_id: string; label: string; product_name: string; metrics: Record<string, number | boolean | string> }>;
    factor_attribution?: Array<{
      factor_key: string;
      factor_name: string;
      category: string;
      score: number;
      lift: number;
      evidence: string;
    }>;
    next_iteration_recommendation?: Record<string, unknown>;
    risk_notes?: string[];
  };
  trace: ExperimentTraceStep[];
  variants: Array<{
    id: string;
    experiment_id: string;
    run_id: string;
    order_index: number;
    label: string;
    metrics: Record<string, number | boolean | string>;
    created_at: string;
  }>;
  attributions: Array<{
    id: string;
    experiment_id: string;
    factor_key: string;
    factor_name: string;
    category: string;
    score: number;
    lift: number;
    evidence: string;
    created_at: string;
  }>;
  created_at: string;
  updated_at: string;
};

export type ExperimentVariantMetricsInput = {
  run_id: string;
  label?: string;
  views: number;
  watch_completion_rate: number;
  avg_watch_seconds: number;
  ctr: number;
  cvr: number;
  orders: number;
  revenue: number;
};

export type Health = {
  status: string;
  graph: string;
  providers: Record<string, string>;
};

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function getHealth() {
  return parseResponse<Health>(await fetch(`${API_BASE}/health`));
}

export async function createAsset(payload: { filename?: string; category: string; description: string }, file?: File | null) {
  if (file) {
    const formData = new FormData();
    formData.append("payload", JSON.stringify(payload));
    formData.append("file", file);
    return parseResponse<AssetLibraryItem>(
      await fetch(`${API_BASE}/assets`, {
        method: "POST",
        body: formData,
      }),
    );
  }
  return parseResponse<AssetLibraryItem>(
    await fetch(`${API_BASE}/assets`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: payload.filename ?? "manual-asset",
        category: payload.category,
        description: payload.description,
      }),
    }),
  );
}

export async function createAssetCollection(payload: {
  product_name: string;
  category: string;
  description?: string;
  usage_notes?: string;
}) {
  return parseResponse<AssetCollection>(
    await fetch(`${API_BASE}/asset-collections`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function listAssetCollections() {
  return parseResponse<AssetCollection[]>(await fetch(`${API_BASE}/asset-collections`));
}

export async function getAssetCollection(collectionId: string) {
  return parseResponse<AssetCollection>(await fetch(`${API_BASE}/asset-collections/${collectionId}`));
}

export async function updateAssetCollection(
  collectionId: string,
  payload: Partial<Pick<AssetCollection, "product_name" | "category" | "description" | "usage_notes">>,
) {
  return parseResponse<AssetCollection>(
    await fetch(`${API_BASE}/asset-collections/${collectionId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function addAssetsToCollection(
  collectionId: string,
  payload: { category: string; description?: string },
  files: File[],
) {
  const formData = new FormData();
  formData.append("payload", JSON.stringify(payload));
  for (const file of files) {
    formData.append("files", file);
  }
  return parseResponse<AssetLibraryItem[]>(
    await fetch(`${API_BASE}/asset-collections/${collectionId}/assets`, {
      method: "POST",
      body: formData,
    }),
  );
}

export function assetFileUrl(assetId: string) {
  return `${API_BASE}/assets/${assetId}/file`;
}

export async function patchAsset(assetId: string, payload: Partial<Pick<AssetLibraryItem, "category" | "description" | "analysis_status">>) {
  return parseResponse<AssetLibraryItem>(
    await fetch(`${API_BASE}/assets/${assetId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function patchAssetSlice(sliceId: string, payload: Partial<Pick<AssetSlice, "summary" | "usable_for" | "is_pinned">>) {
  return parseResponse<AssetSlice>(
    await fetch(`${API_BASE}/asset-slices/${sliceId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function listAssets() {
  return parseResponse<AssetLibraryItem[]>(await fetch(`${API_BASE}/assets`));
}

export async function searchAssets(options: {
  query?: string;
  tag?: string;
  category?: string;
  asset_kind?: string;
  collection_id?: string;
  mode?: "keyword" | "tag" | "vector" | "hybrid";
  limit?: number;
  include_slices?: boolean;
}) {
  const params = new URLSearchParams();
  if (options.query) {
    params.set("q", options.query);
  }
  if (options.tag) {
    params.set("tag", options.tag);
  }
  if (options.category) {
    params.set("category", options.category);
  }
  if (options.asset_kind) {
    params.set("asset_kind", options.asset_kind);
  }
  if (options.collection_id) {
    params.set("collection_id", options.collection_id);
  }
  if (options.mode) {
    params.set("mode", options.mode);
  }
  if (options.limit) {
    params.set("limit", String(options.limit));
  }
  if (options.include_slices !== undefined) {
    params.set("include_slices", String(options.include_slices));
  }
  return parseResponse<AssetSearchResult[]>(await fetch(`${API_BASE}/assets/search?${params.toString()}`));
}

export async function analyzeAsset(assetId: string) {
  return parseResponse<AssetLibraryItem>(await fetch(`${API_BASE}/assets/${assetId}/analyze`, { method: "POST" }));
}

export async function analyzeViralVideo(payload: {
  title: string;
  source_url: string;
  platform?: string;
  category: string;
  product_type?: string;
  country?: string;
  language?: string;
  metrics?: Record<string, unknown>;
  published_at?: string;
  thumbnail_url?: string;
  notes: string;
  source_statement?: string;
}) {
  return parseResponse<ViralVideoAnalysis>(
    await fetch(`${API_BASE}/viral-videos/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function listViralVideos(options: { query?: string; category?: string; factor_category?: string } = {}) {
  const params = new URLSearchParams();
  if (options.query) {
    params.set("q", options.query);
  }
  if (options.category) {
    params.set("category", options.category);
  }
  if (options.factor_category) {
    params.set("factor_category", options.factor_category);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return parseResponse<ViralVideoAnalysis[]>(await fetch(`${API_BASE}/viral-videos${suffix}`));
}

export async function listViralFactors(options: { query?: string; category?: string } = {}) {
  const params = new URLSearchParams();
  if (options.query) {
    params.set("q", options.query);
  }
  if (options.category) {
    params.set("category", options.category);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return parseResponse<ViralFactor[]>(await fetch(`${API_BASE}/viral-factors${suffix}`));
}

export async function listCreativeTemplates(options: { query?: string; category?: string } = {}) {
  const params = new URLSearchParams();
  if (options.query) {
    params.set("q", options.query);
  }
  if (options.category) {
    params.set("category", options.category);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return parseResponse<CreativeTemplate[]>(await fetch(`${API_BASE}/creative-templates${suffix}`));
}

export async function buildCreativeTemplate(payload: CreativeTemplateBuildRequest) {
  return parseResponse<CreativeTemplate>(
    await fetch(`${API_BASE}/creative-templates/build`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function createGenerationRun(payload: GenerationRunRequest) {
  return postGenerationRun(payload);
}

export async function createGenerationRunWithAssets(payload: GenerationRunRequest, files: File[]) {
  return postGenerationRun(payload, files);
}

async function postGenerationRun(payload: GenerationRunRequest, files: File[] = []) {
  if (files.length > 0) {
    const formData = new FormData();
    formData.append("payload", JSON.stringify(payload));
    for (const file of files) {
      formData.append("assets", file);
    }
    return parseResponse<GenerationRun>(
      await fetch(`${API_BASE}/generation-runs`, {
        method: "POST",
        body: formData,
      }),
    );
  }
  return parseResponse<GenerationRun>(
    await fetch(`${API_BASE}/generation-runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function listGenerationRuns() {
  return parseResponse<GenerationRun[]>(await fetch(`${API_BASE}/generation-runs`));
}

export async function getGenerationRun(runId: string) {
  return parseResponse<GenerationRun>(await fetch(`${API_BASE}/generation-runs/${runId}`));
}

export async function getGenerationRunExport(runId: string) {
  return parseResponse<Record<string, unknown>>(await fetch(`${API_BASE}/generation-runs/${runId}/export`));
}

export async function patchStoryboardShot(runId: string, shotId: string, payload: Partial<StoryboardShot>) {
  return parseResponse<GenerationRun>(
    await fetch(`${API_BASE}/generation-runs/${runId}/storyboard/${shotId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function regenerateStoryboardShot(runId: string, shotId: string) {
  return parseResponse<GenerationRun>(
    await fetch(`${API_BASE}/generation-runs/${runId}/storyboard/${shotId}/regenerate`, { method: "POST" }),
  );
}

export async function regenerateShotClip(runId: string, shotId: string) {
  return parseResponse<GenerationRun>(
    await fetch(`${API_BASE}/generation-runs/${runId}/storyboard/${shotId}/regenerate-clip`, { method: "POST" }),
  );
}

export async function renderGenerationPreview(runId: string) {
  return parseResponse<GenerationRun>(await fetch(`${API_BASE}/generation-runs/${runId}/render-preview`, { method: "POST" }));
}

export async function assembleGenerationPreview(runId: string, payload: AssemblyRequest) {
  return parseResponse<GenerationRun>(
    await fetch(`${API_BASE}/generation-runs/${runId}/assemble-preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export function assembledVideoUrl(runId: string, aspectRatio?: string | null) {
  const params = new URLSearchParams();
  if (aspectRatio) {
    params.set("aspect_ratio", aspectRatio);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return `${API_BASE}/generation-runs/${runId}/assembled-video${suffix}`;
}

export async function retryGenerationRun(runId: string) {
  return parseResponse<GenerationRun>(await fetch(`${API_BASE}/generation-runs/${runId}/retry`, { method: "POST" }));
}

export async function analyzeExperiment(payload: {
  title: string;
  run_ids: string[];
  objective: string;
  variant_metrics: ExperimentVariantMetricsInput[];
}) {
  return parseResponse<ExperimentAnalysis>(
    await fetch(`${API_BASE}/experiments/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function listExperiments() {
  return parseResponse<ExperimentAnalysis[]>(await fetch(`${API_BASE}/experiments`));
}
