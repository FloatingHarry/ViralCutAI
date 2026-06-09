"use client";

import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import Link from "next/link";
import {
  CheckCircle2,
  Download,
  FileUp,
  ImageIcon,
  Loader2,
  Play,
  RefreshCcw,
  Scissors,
  Search,
  ShieldCheck,
  Sparkles,
  Video,
} from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { ProviderTruthBadge, artifactProviderMode, humanizeProviderText } from "@/components/provider-truth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  assembleGenerationPreview,
  assembledVideoUrl,
  createGenerationRunWithAssets,
  getGenerationRun,
  getGenerationRunExport,
  listAssetCollections,
  listAssets,
  listCreativeTemplates,
  listViralFactors,
  listViralVideos,
  patchStoryboardShot,
  regenerateShotClip,
  regenerateStoryboardShot,
  renderGenerationPreview,
  searchAssets,
  type TimelineSegment,
  type AssetCollection,
  type AssetLibraryItem,
  type AssetSearchResult,
  type CreativeTemplate,
  type GenerationRun,
  type GenerationRunRequest,
  type MediaArtifact,
  type ViralFactor,
  type ViralVideoAnalysis,
} from "@/lib/api";

function displayArtifactTitle(artifact: MediaArtifact) {
  if (artifact.artifact_type.startsWith("ffmpeg_assembled_video")) {
    return "Local FFmpeg assembled video";
  }
  if (artifact.artifact_type === "cover_image_mock") {
    return "Cover image not generated";
  }
  if (artifact.artifact_type === "cover_image_failed") {
    return "Cover image failed";
  }
  if (artifact.artifact_type === "image_text_plan" || artifact.artifact_type === "image_mock") {
    return "Image prompt plan";
  }
  if (artifact.artifact_type === "video_mock") {
    return "Video provider not connected";
  }
  if (artifact.artifact_type === "video_failed") {
    return "Video provider failed";
  }
  if (artifact.artifact_type === "seedance_draft_video") {
    return "Seedance continuous draft";
  }
  if (artifact.artifact_type === "seedance_replacement_clip") {
    return "Seedance replacement segment";
  }
  if (artifact.artifact_type === "seedance_shot_clip") {
    return "Legacy Seedance shot clip";
  }
  return artifact.title.replaceAll("_", " ").replace(/\bmock\b/gi, "plan");
}

function displayArtifactStatus(artifact: MediaArtifact) {
  const mode = artifactProviderMode(artifact.status, artifact.payload);
  if (mode === "real") {
    return "Real output";
  }
  if (mode === "local") {
    return "Local assembled output";
  }
  if (mode === "real_failed") {
    return "Provider failed";
  }
  if (artifact.artifact_type === "image_text_plan") {
    return "Prompt plan";
  }
  return "Not connected";
}

function artifactMessage(artifact: MediaArtifact) {
  if (artifact.payload.failure_reason) {
    return humanizeProviderText(artifact.payload.failure_reason);
  }
  if (artifact.artifact_type === "cover_image_mock") {
    return "Connect VOLCENGINE_IMAGE_MODEL to generate a real cover image.";
  }
  if (artifact.artifact_type === "video_mock") {
    return "Connect Seedance to render a real video.";
  }
  if (artifact.payload.mock_reason) {
    return humanizeProviderText(artifact.payload.mock_reason);
  }
  return "";
}

function factorConfidenceLabel(confidence: number | null | undefined) {
  if (typeof confidence !== "number" || !Number.isFinite(confidence) || confidence <= 0) {
    return "provider not scored";
  }
  return `${Math.round(confidence)}% confidence`;
}

function audioSourceLabel(source: unknown) {
  if (source === "uploaded_audio") {
    return "Uploaded audio mixed";
  }
  if (source === "editor_timeline_audio") {
    return "Editor timeline audio synced";
  }
  if (source === "draft_audio") {
    return "Draft audio preserved";
  }
  return "No audio track";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

const inputClass =
  "mt-1 h-10 w-full rounded-md border border-black/10 bg-white px-3 text-sm text-slate-950 outline-none transition focus:border-blue-400 focus:ring-4 focus:ring-blue-100";
const textareaClass =
  "mt-1 min-h-24 w-full resize-none rounded-md border border-black/10 bg-white px-3 py-2 text-sm leading-6 text-slate-950 outline-none transition focus:border-blue-400 focus:ring-4 focus:ring-blue-100";

const initialForm = {
  productName: "Aurora Glow Bottle",
  category: "beauty & personal care",
  sellingPoints: "iridescent color-shift finish, premium 100ml bottle, giftable beauty-shelf packaging",
  targetAudience: "beauty shoppers, fragrance lovers, and gift buyers",
  priceOffer: "limited launch offer with free shipping today",
  materialNotes: "vanity table, beauty shelf, gift box, and soft radiant studio lighting",
  creativeGoal: "Generate a conversion-oriented 12-second TikTok Shop product video.",
  referenceStyle: "fast native short-video beauty product reveal with premium close-up proof shots",
  visualStyle: "soft pastel studio, cyan lavender pink glow, reflective surface, clean product close-ups",
  durationSeconds: 12,
  platform: "TikTok Shop",
};

function assetKindForFile(file: File) {
  if (file.type.startsWith("video/")) {
    return "video";
  }
  if (file.type.startsWith("image/")) {
    return "image";
  }
  if (file.type.startsWith("audio/")) {
    return "audio";
  }
  return "reference";
}

function previewFrameClass(aspectRatio: string) {
  if (aspectRatio === "16:9") {
    return "aspect-video";
  }
  if (aspectRatio === "1:1") {
    return "mx-auto aspect-square max-w-[340px]";
  }
  return "mx-auto h-[480px] max-w-[270px]";
}

const activeStatuses = new Set(["queued", "running", "pending", "submitted", "processing", "polling", "real_task_pending"]);

function shouldPollRun(run: GenerationRun | null) {
  if (!run) {
    return false;
  }
  const runStatus = String(run.status ?? "").toLowerCase();
  const assemblyStatus = String(run.preview.assembly_status ?? "").toLowerCase();
  const seedanceStatus = String(run.preview.video_task_status ?? "").toLowerCase();
  const pendingVideoArtifact = run.artifacts.some(
    (artifact) =>
      ["video_real", "seedance_shot_clip", "seedance_draft_video", "seedance_replacement_clip"].includes(artifact.artifact_type) &&
      activeStatuses.has(String(artifact.status ?? "").toLowerCase()),
  );
  return activeStatuses.has(runStatus) || activeStatuses.has(assemblyStatus) || activeStatuses.has(seedanceStatus) || pendingVideoArtifact;
}

function statusBadgeClass(status: string) {
  const value = status.toLowerCase();
  if (value === "succeeded" || value === "completed") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (value === "failed") {
    return "border-rose-200 bg-rose-50 text-rose-700";
  }
  if (activeStatuses.has(value)) {
    return "border-blue-200 bg-blue-50 text-blue-700";
  }
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function timelineSegmentStatusText(segment: TimelineSegment | null) {
  if (!segment) {
    return "Waiting for draft";
  }
  const status = String(segment.artifact_status ?? segment.task_status ?? "").toLowerCase();
  const replacementStatus = String(segment.replacement_status ?? "").toLowerCase();
  if (segment.dirty) {
    return "Dirty";
  }
  if (replacementStatus === "queued" || replacementStatus === "processing") {
    return "Generating";
  }
  if (replacementStatus === "failed") {
    return "Failed";
  }
  if (segment.source === "replacement_clip" && segment.video_url) {
    return "Replacement ready";
  }
  if (segment.source === "asset_slice") {
    return "Asset slice";
  }
  if (segment.video_url) {
    return "Draft ready";
  }
  if (status === "provider_failed" || status === "failed") {
    return "Provider failed";
  }
  if (activeStatuses.has(status)) {
    return segment.source === "replacement_clip" ? "Replacement generating" : "Draft generating";
  }
  return humanizeProviderText(status || "Waiting for draft");
}

function segmentVideoUrl(segment: TimelineSegment) {
  if (!segment.video_url) {
    return null;
  }
  if (segment.source === "draft_video" && typeof segment.start_seconds === "number" && typeof segment.end_seconds === "number") {
    return `${segment.video_url}#t=${segment.start_seconds},${segment.end_seconds}`;
  }
  return segment.video_url;
}

export default function StudioPage() {
  const [form, setForm] = useState(initialForm);
  const [files, setFiles] = useState<File[]>([]);
  const [run, setRun] = useState<GenerationRun | null>(null);
  const [selectedShotId, setSelectedShotId] = useState("");
  const [segmentAction, setSegmentAction] = useState<string | null>(null);
  const [assetCollections, setAssetCollections] = useState<AssetCollection[]>([]);
  const [libraryAssets, setLibraryAssets] = useState<AssetLibraryItem[]>([]);
  const [viralFactors, setViralFactors] = useState<ViralFactor[]>([]);
  const [templates, setTemplates] = useState<CreativeTemplate[]>([]);
  const [references, setReferences] = useState<ViralVideoAnalysis[]>([]);
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([]);
  const [selectedAssetCollectionId, setSelectedAssetCollectionId] = useState("");
  const [selectedAssetSliceIds, setSelectedAssetSliceIds] = useState<string[]>([]);
  const [selectedFactorIds, setSelectedFactorIds] = useState<string[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [selectedReferenceId, setSelectedReferenceId] = useState("");
  const [generationMode, setGenerationMode] = useState<"viral_rewrite" | "template_fusion" | "auto_mix">("auto_mix");
  const [autoRetrieveAssets, setAutoRetrieveAssets] = useState(true);
  const [autoRetrieveFactors, setAutoRetrieveFactors] = useState(true);
  const [assetSearchQuery, setAssetSearchQuery] = useState("");
  const [assetSearchResults, setAssetSearchResults] = useState<AssetSearchResult[]>([]);
  const [assetSearching, setAssetSearching] = useState(false);
  const [loading, setLoading] = useState(false);
  const [assembling, setAssembling] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [assemblyAspectRatio, setAssemblyAspectRatio] = useState<"9:16" | "16:9" | "1:1">("9:16");
  const [includeBgm, setIncludeBgm] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastPolledAt, setLastPolledAt] = useState<string | null>(null);

  const imageArtifacts = useMemo(
    () => run?.artifacts.filter((artifact) => artifact.artifact_type.includes("image")) ?? [],
    [run],
  );
  const coverImageArtifact = useMemo(
    () => run?.artifacts.find((artifact) => artifact.artifact_type.includes("cover_image")) ?? null,
    [run],
  );
  const videoArtifact = useMemo(
    () =>
      run?.artifacts.find((artifact) => ["seedance_draft_video", "seedance_replacement_clip", "seedance_shot_clip", "video_real", "video_mock", "video_failed"].includes(artifact.artifact_type)) ??
      null,
    [run],
  );
  const autoPollActive = useMemo(() => shouldPollRun(run), [run]);
  const polling = autoPollActive;
  const latestEvent = useMemo(() => run?.events.at(-1) ?? null, [run]);
  const generationActive = run ? activeStatuses.has(String(run.status ?? "").toLowerCase()) : false;
  const assemblyActive = run ? activeStatuses.has(String(run.preview.assembly_status ?? "").toLowerCase()) : false;
  const draftVideoArtifact = useMemo(() => run?.artifacts.find((artifact) => artifact.artifact_type === "seedance_draft_video" || artifact.artifact_type === "video_real") ?? null, [run]);
  const replacementClipArtifacts = useMemo(() => run?.artifacts.filter((artifact) => artifact.artifact_type === "seedance_replacement_clip") ?? [], [run]);
  const draftVideoReady = Boolean(draftVideoArtifact?.status === "real_generated" && typeof draftVideoArtifact.payload.video_url === "string");
  const replacementClipPending = replacementClipArtifacts.some((artifact) => activeStatuses.has(String(artifact.status ?? "").toLowerCase()));
  const generationReadyForAssembly = run?.status === "succeeded" && run.storyboard.length > 0 && draftVideoReady && !replacementClipPending;
  const sortedStoryboard = useMemo(() => (run ? [...run.storyboard].sort((a, b) => a.order_index - b.order_index) : []), [run]);
  const timelineSegments = useMemo<TimelineSegment[]>(
    () => run?.preview.timeline_segments ?? (run?.preview.timeline_clips as TimelineSegment[] | undefined) ?? [],
    [run],
  );
  const timelineTotalSeconds = useMemo(
    () => sortedStoryboard.reduce((total, shot) => total + Number(shot.duration_seconds || 0), 0),
    [sortedStoryboard],
  );
  const fixedThreeSegmentTimeline = sortedStoryboard.length === 3 && timelineTotalSeconds === 12;
  const dirtySegmentCount = useMemo(
    () => sortedStoryboard.filter((shot) => shot.dirty).length + timelineSegments.filter((segment) => segment.dirty).length,
    [sortedStoryboard, timelineSegments],
  );
  const timelineIsStale = run?.preview.assembly_status === "stale" || Boolean(run?.preview.assembled_stale) || dirtySegmentCount > 0;
  const selectedShot = useMemo(
    () => sortedStoryboard.find((shot) => shot.shot_id === selectedShotId) ?? sortedStoryboard[0] ?? null,
    [selectedShotId, sortedStoryboard],
  );
  const selectedSegment = useMemo(
    () => timelineSegments.find((segment) => segment.shot_id === selectedShot?.shot_id) ?? null,
    [selectedShot, timelineSegments],
  );
  const selectedSegmentPreviewUrl = selectedSegment ? segmentVideoUrl(selectedSegment) : null;
  const readySegmentCount = useMemo(
    () => timelineSegments.filter((segment) => typeof segment.video_url === "string" && segment.video_url.length > 0).length,
    [timelineSegments],
  );
  const assembledVideoArtifact = useMemo(
    () =>
      run?.artifacts.find(
        (artifact) =>
          artifact.artifact_type.startsWith("ffmpeg_assembled_video") &&
          (artifact.payload.aspect_ratio === assemblyAspectRatio || artifact.payload.aspect_ratio === run.preview.assembled_aspect_ratio),
      ) ?? null,
    [assemblyAspectRatio, run],
  );
  const assembledExports = useMemo(() => run?.preview.assembled_exports ?? {}, [run]);
  const selectedAssembledUrl = useMemo(() => {
    if (!run) {
      return null;
    }
    if (assembledExports[assemblyAspectRatio]) {
      return assembledVideoUrl(run.run_id, assemblyAspectRatio);
    }
    if (run.preview.assembled_aspect_ratio === assemblyAspectRatio && run.preview.assembled_video_url) {
      return assembledVideoUrl(run.run_id, assemblyAspectRatio);
    }
    return null;
  }, [assembledExports, assemblyAspectRatio, run]);
  const selectedAspectForPreview = selectedAssembledUrl ? assemblyAspectRatio : run?.preview.assembled_aspect_ratio ?? assemblyAspectRatio;
  const hasUploadedAudio = files.some((file) => file.type.startsWith("audio/"));
  const selectedAssetCollection = useMemo(
    () => assetCollections.find((collection) => collection.id === selectedAssetCollectionId) ?? null,
    [assetCollections, selectedAssetCollectionId],
  );
  const visibleLibraryAssets = useMemo(
    () => libraryAssets.filter((asset) => !selectedAssetCollectionId || asset.collection_id === selectedAssetCollectionId),
    [libraryAssets, selectedAssetCollectionId],
  );
  const retrievalEvidence = useMemo(() => run?.strategy.retrieval_evidence ?? [], [run]);
  const assetUsagePlan = useMemo(() => run?.strategy.asset_usage_plan ?? [], [run]);
  const factorSelectionReason = useMemo(() => run?.strategy.factor_selection_reason ?? [], [run]);
  const selectedViralReference = useMemo(() => {
    const value = (run?.strategy as Record<string, unknown> | undefined)?.selected_reference_video;
    return isRecord(value) ? value : null;
  }, [run]);
  const referenceMatchReason = String((run?.strategy as Record<string, unknown> | undefined)?.reference_match_reason ?? "");
  const referenceMatchMode = String((run?.strategy as Record<string, unknown> | undefined)?.reference_match_mode ?? "none");
  const autoReferenceCount = Array.isArray((run?.strategy as Record<string, unknown> | undefined)?.auto_references)
    ? ((run?.strategy as Record<string, unknown>).auto_references as unknown[]).length
    : 0;
  const availableSlices = useMemo(() => {
    const slices = new Map<
      string,
      {
        slice_id: string;
        label: string;
        usable_for?: string | null;
        summary?: string | null;
      }
    >();
    for (const asset of visibleLibraryAssets) {
      for (const slice of asset.slices) {
        slices.set(slice.id, {
          slice_id: slice.id,
          label: `${asset.filename} / slice ${slice.order_index}`,
          usable_for: slice.usable_for,
          summary: slice.summary,
        });
      }
    }
    for (const result of assetSearchResults) {
      for (const slice of result.matched_slices) {
        slices.set(slice.slice_id, {
          slice_id: slice.slice_id,
          label: `${result.asset.filename} / slice ${slice.order_index}`,
          usable_for: slice.usable_for,
          summary: slice.summary,
        });
      }
    }
    return Array.from(slices.values());
  }, [assetSearchResults, visibleLibraryAssets]);
  const capabilityRows = useMemo(() => {
    if (!run) {
      return [];
    }
    const findArtifact = (matcher: (artifact: MediaArtifact) => boolean) => run.artifacts.find(matcher);
    const cover = findArtifact((artifact) => artifact.artifact_type.includes("cover_image"));
    const imagePlan = findArtifact((artifact) => artifact.artifact_type === "image_text_plan" || artifact.artifact_type === "image_mock");
    const video = findArtifact((artifact) => ["seedance_draft_video", "seedance_replacement_clip", "seedance_shot_clip", "video_real", "video_mock", "video_failed"].includes(artifact.artifact_type));
    const assembled = findArtifact((artifact) => artifact.artifact_type.startsWith("ffmpeg_assembled_video"));
    const voice = findArtifact((artifact) => artifact.artifact_type.includes("voice_track"));
    const subtitle = findArtifact((artifact) => artifact.artifact_type.includes("subtitle_track"));
    const bgm = findArtifact((artifact) => artifact.artifact_type.includes("bgm_plan"));
    const editing = findArtifact((artifact) => artifact.artifact_type.includes("edit_decision"));
    const rows = [
      {
        name: "Cover Image",
        artifact: cover,
        detail: cover ? artifactMessage(cover) || "Cover provider completed." : "Cover image waits for Render & Review Agent.",
      },
      {
        name: "Image Prompt Plan",
        artifact: imagePlan,
        detail: "Prompt planning is text output from the LLM, not a generated image.",
      },
      {
        name: "AI Draft Timeline",
        artifact: video,
        detail: draftVideoReady
          ? `Continuous draft is ready; ${replacementClipArtifacts.length} replacement segment${replacementClipArtifacts.length === 1 ? "" : "s"} recorded.`
          : video?.payload.video_url
          ? "Seedance rendered a draft video URL."
          : video
          ? artifactMessage(video) || "Video provider completed."
          : "Draft video waits for Render & Review Agent.",
      },
      {
        name: "Local Assembly",
        artifact: assembled,
        detail: assembled?.payload.download_url ? "FFmpeg assembled a local MP4 from storyboard, subtitles, and selected assets." : assembled ? artifactMessage(assembled) || "Local assembly attempted." : "Assemble video after a successful run.",
      },
      {
        name: "Voice / Subtitles / BGM",
        artifact: voice ?? subtitle ?? bgm,
        detail: "Track providers are not connected yet; the run stores planning data only.",
      },
      {
        name: "Editing",
        artifact: editing,
        detail: "Shot-level editing is a provider-pending interface.",
      },
    ];
    return rows;
  }, [draftVideoReady, replacementClipArtifacts.length, run]);

  useEffect(() => {
    const lastRunId = window.localStorage.getItem("viralcutai:lastRunId");
    if (!lastRunId) {
      return;
    }
    getGenerationRun(lastRunId)
      .then(setRun)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!run?.run_id || !autoPollActive) {
      return;
    }

    let cancelled = false;
    const poll = async () => {
      try {
        const nextRun = await getGenerationRun(run.run_id);
        if (cancelled) {
          return;
        }
        setRun(nextRun);
        setLastPolledAt(new Date().toLocaleTimeString());
        window.localStorage.setItem("viralcutai:lastRunId", nextRun.run_id);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Run polling failed");
        }
      }
    };

    void poll();
    const interval = window.setInterval(() => {
      void poll();
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [autoPollActive, run?.run_id]);

  useEffect(() => {
    Promise.all([listAssetCollections(), listAssets(), listViralFactors(), listCreativeTemplates(), listViralVideos()])
      .then(([collections, assets, factors, nextTemplates, videos]) => {
        setAssetCollections(collections);
        setSelectedAssetCollectionId((current) => current || collections[0]?.id || "");
        setLibraryAssets(assets);
        setViralFactors(factors);
        setTemplates(nextTemplates);
        setReferences(videos);
      })
      .catch(() => undefined);
  }, []);

  function updateField<K extends keyof typeof initialForm>(field: K, value: (typeof initialForm)[K]) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  function buildPayload(): GenerationRunRequest {
    return {
      generation_mode: generationMode,
      asset_collection_id: selectedAssetCollectionId || null,
      product_name: form.productName,
      category: form.category,
      selling_points: form.sellingPoints
        .split(",")
        .map((point) => point.trim())
        .filter(Boolean),
      target_audience: form.targetAudience,
      price_offer: form.priceOffer,
      material_notes: form.materialNotes,
      creative_goal: form.creativeGoal,
      reference_style: form.referenceStyle,
      visual_style: form.visualStyle,
      duration_seconds: form.durationSeconds,
      platform: form.platform,
      asset_ids: selectedAssetIds,
      asset_slice_ids: selectedAssetSliceIds,
      reference_video_id: selectedReferenceId || null,
      template_id: selectedTemplateId || null,
      factor_ids: selectedFactorIds,
      auto_retrieve_assets: autoRetrieveAssets,
      auto_retrieve_factors: autoRetrieveFactors,
      source_assets: files.map((file) => ({
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        asset_kind: assetKindForFile(file),
        size_bytes: file.size,
      })),
    };
  }

  function toggleValue(setter: Dispatch<SetStateAction<string[]>>, id: string, checked: boolean) {
    setter((current) => (checked ? Array.from(new Set([...current, id])) : current.filter((item) => item !== id)));
  }

  async function runAssetSearch() {
    setAssetSearching(true);
    setError(null);
    try {
      const query = assetSearchQuery.trim() || [form.productName, form.category, form.sellingPoints, form.materialNotes, form.visualStyle].join(" ");
      setAssetSearchResults(
        await searchAssets({
          query,
          category: form.category,
          collection_id: selectedAssetCollectionId || undefined,
          mode: "hybrid",
          include_slices: true,
          limit: 6,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Asset retrieval failed");
    } finally {
      setAssetSearching(false);
    }
  }

  async function runAgents() {
    setLoading(true);
    setError(null);
    try {
      const nextRun = await createGenerationRunWithAssets(buildPayload(), files);
      setRun(nextRun);
      window.localStorage.setItem("viralcutai:lastRunId", nextRun.run_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generation run failed");
    } finally {
      setLoading(false);
    }
  }

  async function exportPackage() {
    if (!run) {
      return;
    }
    setExporting(true);
    setError(null);
    try {
      const payload = await getGenerationRunExport(run.run_id);
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `viralcutai-${run.run_id}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExporting(false);
    }
  }

  async function assembleVideo() {
    if (!run) {
      return;
    }
    setAssembling(true);
    setError(null);
    try {
      const nextRun = await assembleGenerationPreview(run.run_id, {
        aspect_ratio: assemblyAspectRatio,
        include_bgm: includeBgm,
      });
      setRun(nextRun);
      window.localStorage.setItem("viralcutai:lastRunId", nextRun.run_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Local video assembly failed");
      try {
        setRun(await getGenerationRun(run.run_id));
      } catch {
        // Keep the current run visible if the refresh fails.
      }
    } finally {
      setAssembling(false);
    }
  }

  function downloadMp4() {
    if (!run || !selectedAssembledUrl) {
      return;
    }
    const link = document.createElement("a");
    link.href = assembledVideoUrl(run.run_id, assemblyAspectRatio);
    link.download = `viralcutai-${run.run_id}-${assemblyAspectRatio.replace(":", "x")}.mp4`;
    link.click();
  }

  async function runTimelineAction(actionId: string, action: () => Promise<GenerationRun>, fallbackMessage: string) {
    setSegmentAction(actionId);
    setError(null);
    try {
      const nextRun = await action();
      setRun(nextRun);
      window.localStorage.setItem("viralcutai:lastRunId", nextRun.run_id);
      return nextRun;
    } catch (err) {
      setError(err instanceof Error ? err.message : fallbackMessage);
      return null;
    } finally {
      setSegmentAction(null);
    }
  }

  async function regenerateShot(shotId: string) {
    if (!run) {
      return;
    }
    await runTimelineAction(`copy:${shotId}`, () => regenerateStoryboardShot(run.run_id, shotId), "Shot regeneration failed");
  }

  async function regenerateClip(shotId: string) {
    if (!run) {
      return;
    }
    await runTimelineAction(`clip:${shotId}`, () => regenerateShotClip(run.run_id, shotId), "Clip regeneration failed");
  }

  async function saveShotPatch(shotId: string, payload: Partial<GenerationRun["storyboard"][number]>) {
    if (!run) {
      return;
    }
    setError(null);
    try {
      const nextRun = await patchStoryboardShot(run.run_id, shotId, payload);
      setRun(nextRun);
      window.localStorage.setItem("viralcutai:lastRunId", nextRun.run_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Shot update failed");
    }
  }

  async function refreshPreview() {
    if (!run) {
      return;
    }
    setError(null);
    try {
      setRun(await renderGenerationPreview(run.run_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Preview refresh failed");
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Step 3 / Run & Results"
        title="Run agents and review results"
        description="Run three LangGraph agents to create one continuous Seedance draft, editable timeline segments, compliance checks, and FFmpeg export metadata."
        badges={["AI draft video", "timeline segments", "FFmpeg export"]}
      />

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px] 2xl:grid-cols-[minmax(0,1fr)_380px]">
        <Card className="p-4 xl:col-span-2">
          <CardHeader className="mb-3">
            <div>
              <CardTitle>Generation Brief</CardTitle>
              <CardDescription>Define what to generate, which evidence to use, and then run the agents.</CardDescription>
            </div>
            <Sparkles className="h-5 w-5 text-blue-600" />
          </CardHeader>

          <div className="grid gap-4 2xl:grid-cols-[minmax(0,1.35fr)_minmax(360px,0.85fr)]">
            <div className="grid gap-3">
              <div className="grid gap-3 md:grid-cols-[minmax(0,1.4fr)_minmax(0,0.9fr)_minmax(0,0.8fr)]">
                <label className="block text-sm font-medium text-slate-700">
                  Product name
                  <input className={inputClass} value={form.productName} onChange={(event) => updateField("productName", event.target.value)} />
                </label>
                <label className="block text-sm font-medium text-slate-700">
                  Category
                  <input className={inputClass} value={form.category} onChange={(event) => updateField("category", event.target.value)} />
                </label>
                <label className="block text-sm font-medium text-slate-700">
                  Platform
                  <input className={inputClass} value={form.platform} onChange={(event) => updateField("platform", event.target.value)} />
                </label>
              </div>

              <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                <label className="block text-sm font-medium text-slate-700">
                  Selling points
                  <textarea className={`${textareaClass} min-h-24`} value={form.sellingPoints} onChange={(event) => updateField("sellingPoints", event.target.value)} />
                </label>
                <label className="block text-sm font-medium text-slate-700">
                  Material and scene notes
                  <textarea className={`${textareaClass} min-h-24`} value={form.materialNotes} onChange={(event) => updateField("materialNotes", event.target.value)} />
                </label>
              </div>

              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <label className="block text-sm font-medium text-slate-700">
                  Target audience
                  <input className={inputClass} value={form.targetAudience} onChange={(event) => updateField("targetAudience", event.target.value)} />
                </label>
                <label className="block text-sm font-medium text-slate-700">
                  Price / offer
                  <input className={inputClass} value={form.priceOffer} onChange={(event) => updateField("priceOffer", event.target.value)} />
                </label>
                <label className="block text-sm font-medium text-slate-700">
                  Reference style
                  <input className={inputClass} value={form.referenceStyle} onChange={(event) => updateField("referenceStyle", event.target.value)} />
                </label>
                <label className="block text-sm font-medium text-slate-700">
                  Visual style
                  <input className={inputClass} value={form.visualStyle} onChange={(event) => updateField("visualStyle", event.target.value)} />
                </label>
              </div>

              <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_160px]">
                <label className="block text-sm font-medium text-slate-700">
                  Creative goal
                  <input className={inputClass} value={form.creativeGoal} onChange={(event) => updateField("creativeGoal", event.target.value)} />
                </label>
                <label className="block text-sm font-medium text-slate-700">
                  Duration
                  <input className={inputClass} disabled min={12} max={12} type="number" value={form.durationSeconds} onChange={() => updateField("durationSeconds", 12)} />
                </label>
              </div>
              <p className="text-xs leading-5 text-slate-500">V1 uses a fixed 12s structure: Hook 4s, Proof + Use 4s, CTA 4s.</p>
            </div>

            <div className="grid gap-3 rounded-lg border border-black/10 bg-[#f5f5f7] p-3">
              <div className="grid grid-cols-3 gap-2">
                {[
                  { value: "auto_mix", label: "Auto Mix" },
                  { value: "viral_rewrite", label: "Reference" },
                  { value: "template_fusion", label: "Template" },
                ].map((item) => (
                  <button
                    key={item.value}
                    className={`rounded-md border px-3 py-2 text-xs font-semibold transition ${
                      generationMode === item.value ? "border-blue-200 bg-blue-50 text-blue-700" : "border-black/10 bg-white text-slate-600"
                    }`}
                    type="button"
                    onClick={() => setGenerationMode(item.value as typeof generationMode)}
                  >
                    {item.label}
                  </button>
                ))}
              </div>

              <div className="grid gap-2 md:grid-cols-2 2xl:grid-cols-1">
                <label className="block text-xs font-medium text-slate-700">
                  Asset collection
                  <select className={inputClass} value={selectedAssetCollectionId} onChange={(event) => setSelectedAssetCollectionId(event.target.value)}>
                    <option value="">No private collection</option>
                    {assetCollections.map((collection) => (
                      <option key={collection.id} value={collection.id}>
                        {collection.product_name} / {collection.category}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block text-xs font-medium text-slate-700">
                  Viral reference
                  <select className={inputClass} value={selectedReferenceId} onChange={(event) => setSelectedReferenceId(event.target.value)}>
                    <option value="">{generationMode === "viral_rewrite" ? "Select a reference" : "Auto / none"}</option>
                    {references.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.title}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block text-xs font-medium text-slate-700 md:col-span-2 2xl:col-span-1">
                  Template
                  <select className={inputClass} value={selectedTemplateId} onChange={(event) => setSelectedTemplateId(event.target.value)}>
                    <option value="">{generationMode === "template_fusion" ? "Select a template" : "Auto / none"}</option>
                    {templates.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              {selectedAssetCollection ? (
                <div className="rounded-md border border-blue-100 bg-blue-50 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="min-w-0 flex-1 truncate text-xs font-semibold text-blue-950">{selectedAssetCollection.product_name}</p>
                    <Badge>{selectedAssetCollection.assets.length} assets</Badge>
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs leading-5 text-blue-800">{selectedAssetCollection.summary}</p>
                </div>
              ) : null}

              <div className="grid gap-2 rounded-md bg-white p-3">
                <div className="flex items-center gap-2">
                  <input className={inputClass} value={assetSearchQuery} onChange={(event) => setAssetSearchQuery(event.target.value)} placeholder="Search asset evidence" />
                  <Button size="icon" variant="outline" onClick={runAssetSearch} disabled={assetSearching} aria-label="Search saved assets">
                    {assetSearching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                  </Button>
                </div>
                <div className="max-h-32 overflow-auto pr-1">
                  {assetSearchResults.map((result) => (
                    <label key={result.asset.id} className="mt-2 flex items-start gap-2 rounded-md bg-[#f5f5f7] p-2 text-xs text-slate-700">
                      <input
                        className="mt-1"
                        type="checkbox"
                        checked={selectedAssetIds.includes(result.asset.id)}
                        onChange={(event) => toggleValue(setSelectedAssetIds, result.asset.id, event.target.checked)}
                      />
                      <span className="min-w-0">
                        <span className="line-clamp-1 font-medium text-slate-950">{result.asset.filename}</span>
                        <span className="mt-1 line-clamp-2 leading-5 text-slate-500">{Math.round(result.score * 100)} match / {result.reason}</span>
                      </span>
                    </label>
                  ))}
                  {!assetSearchResults.length ? <p className="py-2 text-xs leading-5 text-slate-500">Optional: search saved assets to pin stronger evidence.</p> : null}
                </div>
              </div>

              <div className="grid gap-2 rounded-md bg-white p-3">
                <p className="text-xs font-semibold text-slate-700">Manual pins</p>
                <div className="grid max-h-32 gap-2 overflow-auto pr-1 md:grid-cols-2 2xl:grid-cols-1">
                  {visibleLibraryAssets.slice(0, 4).map((asset) => (
                    <label key={asset.id} className="flex min-w-0 items-center gap-2 text-xs text-slate-700">
                      <input
                        type="checkbox"
                        checked={selectedAssetIds.includes(asset.id)}
                        onChange={(event) => toggleValue(setSelectedAssetIds, asset.id, event.target.checked)}
                      />
                      <span className="truncate">{asset.filename}</span>
                    </label>
                  ))}
                  {viralFactors.slice(0, 4).map((factor) => (
                    <label key={factor.id} className="flex min-w-0 items-center gap-2 text-xs text-slate-700">
                      <input
                        type="checkbox"
                        checked={selectedFactorIds.includes(factor.id)}
                        onChange={(event) => toggleValue(setSelectedFactorIds, factor.id, event.target.checked)}
                      />
                      <span className="truncate">{factor.category}: {factor.name}</span>
                    </label>
                  ))}
                  {assetSearchResults.flatMap((result) => result.matched_slices).slice(0, 4).map((slice) => (
                    <label key={slice.slice_id} className="flex min-w-0 items-center gap-2 text-xs text-slate-700">
                      <input
                        type="checkbox"
                        checked={selectedAssetSliceIds.includes(slice.slice_id)}
                        onChange={(event) => toggleValue(setSelectedAssetSliceIds, slice.slice_id, event.target.checked)}
                      />
                      <span className="truncate">Slice {slice.order_index}: {slice.summary}</span>
                    </label>
                  ))}
                </div>
                {!visibleLibraryAssets.length && !viralFactors.length && !assetSearchResults.length ? (
                  <p className="text-xs leading-5 text-slate-500">No manual items available yet. Auto retrieval can still run.</p>
                ) : null}
              </div>

              <div className="grid gap-2 md:grid-cols-2 2xl:grid-cols-1">
                <label className="flex items-center justify-between gap-3 rounded-md bg-white px-3 py-2 text-xs text-slate-700">
                  <span>Auto assets</span>
                  <input type="checkbox" checked={autoRetrieveAssets} onChange={(event) => setAutoRetrieveAssets(event.target.checked)} />
                </label>
                <label className="flex items-center justify-between gap-3 rounded-md bg-white px-3 py-2 text-xs text-slate-700">
                  <span>Auto factors</span>
                  <input type="checkbox" checked={autoRetrieveFactors} onChange={(event) => setAutoRetrieveFactors(event.target.checked)} />
                </label>
              </div>

              <label className="flex cursor-pointer items-center justify-center gap-2 rounded-md border border-dashed border-black/15 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:border-blue-200 hover:text-blue-700">
                <FileUp className="h-4 w-4" />
                Attach files
                <input className="sr-only" multiple type="file" accept="image/*,video/*,audio/*" onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
              </label>
              {files.length ? (
                <div className="flex flex-wrap gap-1">
                  {files.slice(0, 4).map((file) => (
                    <Badge key={`${file.name}-${file.size}`} className="max-w-full">
                      <span className="truncate">{file.name}</span>
                    </Badge>
                  ))}
                  {files.length > 4 ? <Badge>+{files.length - 4}</Badge> : null}
                </div>
              ) : null}

              <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto] 2xl:grid-cols-1">
                <div className="flex flex-wrap gap-1">
                  {selectedAssetIds.length ? <Badge>{selectedAssetIds.length} assets pinned</Badge> : null}
                  {selectedFactorIds.length ? <Badge>{selectedFactorIds.length} factors pinned</Badge> : null}
                  {!selectedAssetIds.length && !selectedFactorIds.length ? <span className="text-xs leading-6 text-slate-500">Auto retrieval will choose the best evidence.</span> : null}
                </div>
                <Button variant="secondary" onClick={runAgents} disabled={loading || generationActive}>
                  {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                  {loading ? "Queueing" : generationActive ? "Running" : "Run agents"}
                </Button>
              </div>
            </div>
          </div>
          {error ? <p className="mt-4 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</p> : null}
        </Card>

        <main className="grid gap-6">
          {run ? (
            <div className="rounded-xl border border-black/10 bg-white p-4 shadow-sm shadow-black/[0.03]">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge className={statusBadgeClass(run.status)}>{run.status}</Badge>
                    {polling ? (
                      <span className="inline-flex items-center gap-1 text-xs font-medium text-blue-700">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Auto polling
                      </span>
                    ) : null}
                    {run.preview.assembly_status ? (
                      <Badge className={statusBadgeClass(String(run.preview.assembly_status))}>
                        Assembly {String(run.preview.assembly_status)}
                      </Badge>
                    ) : null}
                  </div>
                  <p className="mt-2 break-words text-sm font-medium text-slate-950">
                    {latestEvent?.message ?? run.summary}
                  </p>
                  <p className="mt-1 break-words font-mono text-xs text-slate-500">
                    {run.run_id}
                    {lastPolledAt ? ` / updated ${lastPolledAt}` : ""}
                  </p>
                </div>
                <Button variant="outline" onClick={refreshPreview}>
                  Refresh now
                </Button>
              </div>
            </div>
          ) : null}

          <section className="grid gap-3 lg:grid-cols-3">
            {["Viral Strategy Agent", "Script & Storyboard Agent", "Render & Review Agent"].map((name, index) => {
              const step = run?.agents.find((agent) => agent.agent_name === name);
              const pendingStatus = run ? (generationActive ? "running" : "waiting") : "waiting";
              return (
                <div key={name} className="rounded-lg border border-black/10 bg-white p-4 shadow-sm shadow-black/[0.03]">
                  <div className="flex items-center justify-between gap-2">
                    <Badge>0{index + 1}</Badge>
                    <Badge className={statusBadgeClass(step?.status ?? pendingStatus)}>{step?.status ?? pendingStatus}</Badge>
                  </div>
                  <p className="mt-3 text-sm font-medium text-slate-950">{name}</p>
                  {step ? (
                    <div className="mt-2 space-y-2">
                      {step.agent_name === "Render & Review Agent" ? (
                        <Badge className="border-blue-200 bg-blue-50 text-blue-700">Capability details below</Badge>
                      ) : (
                        <ProviderTruthBadge mode={step.execution_mode} />
                      )}
                      <p className="break-words text-xs leading-5 text-slate-500">{step.provider} / {step.duration_ms}ms</p>
                      <p className="break-words text-xs leading-5 text-slate-500">{humanizeProviderText(step.provider_message)}</p>
                    </div>
                  ) : (
                    <p className="mt-1 break-words text-xs leading-5 text-slate-500">Waiting for a Studio run.</p>
                  )}
                </div>
              );
            })}
          </section>

          <Card className="p-4">
            <CardHeader className="mb-3">
              <div>
                <CardTitle>Output Check</CardTitle>
                <CardDescription>Compare generated capabilities and provider state at a glance.</CardDescription>
              </div>
              <ShieldCheck className="h-5 w-5 text-emerald-600" />
            </CardHeader>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
              {capabilityRows.map((capability) => (
                <div key={capability.name} className="rounded-lg border border-black/10 bg-[#f5f5f7] p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium text-slate-950">{capability.name}</p>
                    {capability.artifact ? (
                      <ProviderTruthBadge mode={artifactProviderMode(capability.artifact.status, capability.artifact.payload)} />
                    ) : (
                      <Badge>Waiting</Badge>
                    )}
                  </div>
                  <p className="mt-2 text-xs font-medium text-slate-700">
                    {capability.artifact ? displayArtifactStatus(capability.artifact) : "Waiting"}
                  </p>
                  <p className="mt-2 break-words text-xs leading-5 text-slate-500">{humanizeProviderText(capability.detail)}</p>
                </div>
              ))}
              {!run ? <EmptyState className="md:col-span-2 xl:col-span-6" text="Provider outputs appear after a run." /> : null}
            </div>
          </Card>

          <Card className="p-4">
            <CardHeader className="mb-3">
              <div>
                <CardTitle>Run Progress</CardTitle>
                <CardDescription>{run?.summary ?? "Events update while the background run is active."}</CardDescription>
              </div>
              <CheckCircle2 className="h-5 w-5 text-emerald-600" />
            </CardHeader>
            <div className="grid gap-3 md:grid-cols-2">
              {(run?.events ?? []).slice(-8).map((event) => (
                <div key={event.id} className="rounded-lg border border-black/10 bg-[#f5f5f7] p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-medium text-slate-950">{event.event_type.replaceAll("_", " ")}</p>
                    <Badge className={event.status === "failed" ? "border-rose-200 bg-rose-50 text-rose-700" : ""}>{event.status}</Badge>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-slate-500">{event.message}</p>
                </div>
              ))}
              {!run ? (
                <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500 md:col-span-2">
                  No progress events yet.
                </div>
              ) : null}
            </div>
          </Card>

          <details className="rounded-lg border border-black/10 bg-white p-4 shadow-sm shadow-black/[0.03]">
            <summary className="flex cursor-pointer items-center justify-between gap-3 text-sm font-semibold text-slate-950">
              Strategy Details
              <Sparkles className="h-5 w-5 text-blue-600" />
            </summary>
            <p className="mt-1 text-xs leading-5 text-slate-500">{run?.strategy.source_asset_summary ?? "The strategy agent will reference uploaded assets when available."}</p>
            {run ? (
              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
                  <p className="text-xs text-slate-500">Hook</p>
                  {run.strategy.generation_mode ? <Badge className="mb-2 mt-2">{String(run.strategy.generation_mode).replaceAll("_", " ")}</Badge> : null}
                  <p className="mt-2 text-sm font-medium leading-6 text-slate-950">{run.strategy.hook}</p>
                </div>
                <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
                  <p className="text-xs text-slate-500">Product angle</p>
                  <p className="mt-2 text-sm leading-6 text-slate-700">{run.strategy.product_angle}</p>
                </div>
                <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4 lg:col-span-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-xs text-slate-500">Viral reference match</p>
                    <div className="flex flex-wrap gap-2">
                      <Badge className={selectedViralReference ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700"}>
                        {selectedViralReference ? "Strong reference selected" : "No strong reference"}
                      </Badge>
                      <Badge>{referenceMatchMode}</Badge>
                    </div>
                  </div>
                  {selectedViralReference ? (
                    <div className="mt-3 rounded-md border border-black/10 bg-white p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge>{String(selectedViralReference.category ?? "reference")}</Badge>
                        <Badge>{Boolean(selectedViralReference.visual_verified) ? "video verified" : "structured only"}</Badge>
                        <Badge>{autoReferenceCount} auto reference</Badge>
                      </div>
                      <p className="mt-2 break-words text-sm font-medium text-slate-950">{String(selectedViralReference.title ?? "Selected viral reference")}</p>
                      <p className="mt-1 break-words text-xs leading-5 text-slate-500">
                        {referenceMatchReason || "Best matched viral reference selected for this run."}
                      </p>
                    </div>
                  ) : (
                    <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3">
                      <p className="text-sm font-medium text-amber-900">Default commerce structure is being used.</p>
                      <p className="mt-1 text-xs leading-5 text-amber-800">
                        {referenceMatchReason || "No strong viral reference match found; the strategy uses default commerce factors instead of forcing an unrelated FastMoss reference."}
                      </p>
                    </div>
                  )}
                </div>
                <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4 lg:col-span-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-xs text-slate-500">Retrieval evidence</p>
                    <Badge>{retrievalEvidence.length} signals</Badge>
                  </div>
                  <div className="mt-3 grid gap-3 md:grid-cols-2">
                    {retrievalEvidence.slice(0, 6).map((item, index) => (
                      <div key={`${item.title ?? "evidence"}-${index}`} className="rounded-md border border-black/10 bg-white p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge>{item.type ?? "asset"}</Badge>
                          {typeof item.score === "number" ? <Badge>{Math.round(item.score * 100)} match</Badge> : null}
                        </div>
                        <p className="mt-2 break-words text-sm font-medium text-slate-950">{item.title ?? "Retrieved signal"}</p>
                        <p className="mt-1 break-words text-xs leading-5 text-slate-500">{item.reason}</p>
                      </div>
                    ))}
                    {!retrievalEvidence.length ? <EmptyState className="md:col-span-2" text="No retrieval evidence attached to this run." /> : null}
                  </div>
                </div>
                <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4 lg:col-span-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-xs text-slate-500">Asset usage plan</p>
                    <Badge>{assetUsagePlan.length} placements</Badge>
                  </div>
                  <div className="mt-3 grid gap-3 md:grid-cols-2">
                    {assetUsagePlan.slice(0, 6).map((item, index) => (
                      <div key={`${item.shot_id ?? "shot"}-${index}`} className="rounded-md border border-black/10 bg-white p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge>{item.shot_id ?? "shot"}</Badge>
                          <Badge>{item.usage ?? "evidence"}</Badge>
                        </div>
                        <p className="mt-2 break-words text-sm font-medium text-slate-950">{item.asset_title ?? "Retrieved asset"}</p>
                        <p className="mt-1 break-words text-xs leading-5 text-slate-500">{item.reason}</p>
                      </div>
                    ))}
                    {!assetUsagePlan.length ? <EmptyState className="md:col-span-2" text="No asset placement plan yet." /> : null}
                  </div>
                </div>
                <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4 lg:col-span-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-xs text-slate-500">Factor selection rationale</p>
                    <Badge>{factorSelectionReason.length} reasons</Badge>
                  </div>
                  <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {factorSelectionReason.slice(0, 9).map((item, index) => (
                      <div key={`${item.factor_key ?? item.name ?? "factor"}-${index}`} className="rounded-md border border-black/10 bg-white p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge>{item.category ?? "factor"}</Badge>
                          <Badge>{item.source ?? "library"}</Badge>
                        </div>
                        <p className="mt-2 break-words text-sm font-medium text-slate-950">{item.name ?? "Selected factor"}</p>
                        <p className="mt-1 break-words text-xs leading-5 text-slate-500">{item.reason}</p>
                      </div>
                    ))}
                    {!factorSelectionReason.length ? <EmptyState className="md:col-span-2 xl:col-span-3" text="No factor selection rationale yet." /> : null}
                  </div>
                </div>
                <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4 lg:col-span-2">
                    <p className="text-xs text-slate-500">Run factor board</p>
                  <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                    {(run.viral_factors.length ? run.viral_factors : run.strategy.factor_board ?? []).map((factor) => (
                      <div key={factor.factor_key} className="rounded-md border border-black/10 bg-white p-3">
                        <div className="flex items-center justify-between gap-2">
                          <p className="text-sm font-medium text-slate-950">{factor.name}</p>
                          <Badge>{factor.category}</Badge>
                        </div>
                        <p className="mt-1 text-xs leading-5 text-slate-500">{factor.reason}</p>
                        <p className="mt-2 text-xs leading-5 text-blue-700">{factor.expected_effect}</p>
                        <p className="mt-2 font-mono text-[11px] text-slate-400">{factorConfidenceLabel(factor.confidence)} / {factor.source}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <EmptyState text="No strategy yet." />
            )}
          </details>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Video Editor</CardTitle>
                <CardDescription>
                  {run
                    ? `${readySegmentCount}/3 generated segments are available. Continue trimming, cutting, appending, and assembling on the dedicated editor page.`
                    : "Generate a run first, then open the dedicated editor page."}
                </CardDescription>
              </div>
              <Scissors className="h-5 w-5 text-rose-600" />
            </CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
              <div className="min-w-0">
                <p className="text-sm font-medium text-slate-950">Timeline assembly moved out of Studio</p>
                <p className="mt-1 text-xs leading-5 text-slate-500">
                  Studio remains the generation surface. Editor handles trimming, cuts, replacement clips, asset slices, and final FFmpeg assembly.
                </p>
              </div>
              <Link href="/editor">
                <Button variant="secondary" disabled={!run}>
                  <Scissors className="h-4 w-4" />
                  Open Editor
                </Button>
              </Link>
            </div>
          </Card>

          <Card className="hidden">
            <CardHeader>
              <div>
                <CardTitle>Editing Workbench</CardTitle>
                <CardDescription>
                  {run
                    ? fixedThreeSegmentTimeline
                      ? `${readySegmentCount}/3 fixed storyboard segments ready. Edit one segment, regenerate it as a replacement, then assemble the final MP4.`
                      : `${sortedStoryboard.length} segments on this older run. Create a fresh run to use the fixed 3-segment editor.`
                    : "AI draft slices and editable timeline segment controls appear after generation."}
                </CardDescription>
              </div>
              <Video className="h-5 w-5 text-rose-600" />
            </CardHeader>
            {run ? (
              <div className="space-y-4">
                <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="min-w-0">
                        <p className="text-sm font-medium text-slate-950">Fixed 3-Segment Storyboard Editor</p>
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                        <Badge>{fixedThreeSegmentTimeline ? "3/3 fixed segments" : `${sortedStoryboard.length} segment legacy run`}</Badge>
                        <Badge>{timelineTotalSeconds}s total</Badge>
                        <Badge className={draftVideoReady ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-blue-200 bg-blue-50 text-blue-700"}>
                          {draftVideoReady ? "Draft ready" : "Waiting for draft"}
                        </Badge>
                        {timelineIsStale ? <Badge className="border-amber-200 bg-amber-50 text-amber-700">Stale</Badge> : null}
                      </div>
                    </div>
                  </div>

                  <div className="mt-4 flex min-h-24 gap-2 overflow-x-auto pb-1">
                    {sortedStoryboard.map((shot) => {
                      const segment = timelineSegments.find((item) => item.shot_id === shot.shot_id) ?? null;
                      const active = selectedShot?.shot_id === shot.shot_id;
                      const status = timelineSegmentStatusText(segment);
                      const failed = status.toLowerCase().includes("failed");
                      const generating = status.toLowerCase().includes("generating") || segmentAction === `clip:${shot.shot_id}`;
                      const ready = Boolean(segment?.source === "replacement_clip" || segment?.source === "asset_slice" || segment?.video_url);
                      return (
                        <button
                          key={shot.shot_id}
                          className={`min-w-36 rounded-md border p-3 text-left transition ${
                            active
                              ? "border-blue-300 bg-white shadow-sm shadow-blue-100"
                              : "border-black/10 bg-white/75 hover:border-blue-200 hover:bg-white"
                          }`}
                          style={{ flexGrow: Math.max(1, Number(shot.duration_seconds || 1)) }}
                          type="button"
                          onClick={() => setSelectedShotId(shot.shot_id)}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <Badge>Shot {shot.order_index}</Badge>
                            <span className="font-mono text-[11px] text-slate-500">{shot.duration_seconds}s</span>
                          </div>
                          <p className="mt-2 truncate text-sm font-medium text-slate-950">{shot.beat}</p>
                          <div className="mt-2 flex flex-wrap gap-1">
                            <Badge className={failed ? "border-rose-200 bg-rose-50 text-rose-700" : generating ? "border-blue-200 bg-blue-50 text-blue-700" : ready ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-slate-50 text-slate-600"}>
                              {status}
                            </Badge>
                            <Badge>{segment?.source_label ?? "Draft"}</Badge>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {selectedShot ? (
                  <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
                    <div className="rounded-lg border border-black/10 bg-white p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-slate-950">
                            Shot {selectedShot.order_index}: {selectedShot.beat}
                          </p>
                          <p className="mt-1 font-mono text-[11px] text-slate-400">{selectedSegment?.time_range ?? `${selectedShot.duration_seconds}s segment`}</p>
                        </div>
                        <Badge>{timelineSegmentStatusText(selectedSegment)}</Badge>
                      </div>
                      <div className="mt-4 grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
                        <div className="overflow-hidden rounded-md border border-black/10 bg-slate-950">
                          {selectedSegmentPreviewUrl ? (
                            <video className="aspect-[9/16] w-full object-cover" controls src={selectedSegmentPreviewUrl} />
                          ) : (
                            <div className="flex aspect-[9/16] flex-col justify-between p-4 text-white">
                              <div>
                                <p className="text-xs text-white/50">{timelineSegmentStatusText(selectedSegment)}</p>
                                <p className="mt-3 text-sm font-medium leading-5">{selectedShot.beat}</p>
                              </div>
                              <p className="break-words text-[11px] leading-5 text-white/55">
                                {selectedSegment?.failure_reason
                                  ? humanizeProviderText(selectedSegment.failure_reason)
                                  : selectedSegment?.source === "asset_slice"
                                    ? "This segment will use the selected asset slice during assembly."
                                    : "Draft segment appears here when Seedance finishes."}
                              </p>
                            </div>
                          )}
                        </div>
                        <div className="min-w-0 space-y-3">
                          <div className="grid gap-3 md:grid-cols-2">
                            <div className="rounded-md border border-black/10 bg-[#f5f5f7] p-3">
                              <p className="text-xs text-slate-500">Visual</p>
                              <p className="mt-2 break-words text-sm leading-6 text-slate-700">{selectedShot.visual_description}</p>
                            </div>
                            <div className="rounded-md border border-black/10 bg-[#f5f5f7] p-3">
                              <p className="text-xs text-slate-500">Voiceover</p>
                              <p className="mt-2 break-words text-sm leading-6 text-slate-700">{selectedShot.voiceover}</p>
                            </div>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {(selectedShot.linked_factor_keys ?? []).map((key) => (
                              <Badge key={key}>{key}</Badge>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>

                    <form
                      key={selectedShot.shot_id}
                      className="rounded-lg border border-black/10 bg-white p-4"
                      onSubmit={(event) => {
                        event.preventDefault();
                        const formData = new FormData(event.currentTarget);
                        void saveShotPatch(selectedShot.shot_id, {
                          beat: String(formData.get("beat") ?? ""),
                          selected_asset_slice_id: String(formData.get("selected_asset_slice_id") ?? "") || null,
                          subtitle: String(formData.get("subtitle") ?? ""),
                          voiceover: String(formData.get("voiceover") ?? ""),
                          camera_motion: String(formData.get("camera_motion") ?? ""),
                          visual_description: String(formData.get("visual_description") ?? ""),
                          image_prompt: String(formData.get("image_prompt") ?? ""),
                          video_prompt: String(formData.get("video_prompt") ?? ""),
                        });
                      }}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-sm font-medium text-slate-950">Segment Inspector</p>
                        <Button size="sm" type="submit">
                          <CheckCircle2 className="h-4 w-4" />
                          Save
                        </Button>
                      </div>
                      <div className="mt-4 grid gap-3">
                        <label className="block text-xs text-slate-600">
                          Beat
                          <input className={inputClass} defaultValue={selectedShot.beat} name="beat" />
                        </label>
                        <div className="grid gap-3 sm:grid-cols-[96px_minmax(0,1fr)]">
                          <div className="block text-xs text-slate-600">
                            Seconds
                            <div className="mt-1 rounded-md border border-black/10 bg-[#f5f5f7] px-3 py-2 font-mono text-sm text-slate-700">
                              {selectedShot.duration_seconds}s
                            </div>
                          </div>
                          <label className="block text-xs text-slate-600">
                            Source slice
                            <select className={inputClass} defaultValue={selectedShot.selected_asset_slice_id ?? ""} name="selected_asset_slice_id">
                              <option value="">Use draft or replacement</option>
                              {availableSlices.map((slice) => (
                                <option key={slice.slice_id} value={slice.slice_id}>
                                  {slice.label} / {slice.usable_for ?? "evidence"}
                                </option>
                              ))}
                            </select>
                          </label>
                        </div>
                        <label className="block text-xs text-slate-600">
                          Subtitle
                          <input className={inputClass} defaultValue={selectedShot.subtitle} name="subtitle" />
                        </label>
                        <label className="block text-xs text-slate-600">
                          Voiceover
                          <textarea className={`${textareaClass} min-h-20`} defaultValue={selectedShot.voiceover} name="voiceover" />
                        </label>
                        <label className="block text-xs text-slate-600">
                          Camera motion
                          <input className={inputClass} defaultValue={selectedShot.camera_motion} name="camera_motion" />
                        </label>
                        <label className="block text-xs text-slate-600">
                          Lens / scene
                          <textarea className={`${textareaClass} min-h-20`} defaultValue={selectedShot.visual_description} name="visual_description" />
                        </label>
                        <label className="block text-xs text-slate-600">
                          Image prompt
                          <textarea className={`${textareaClass} min-h-20`} defaultValue={selectedShot.image_prompt} name="image_prompt" />
                        </label>
                        <label className="block text-xs text-slate-600">
                          Video prompt
                          <textarea className={`${textareaClass} min-h-24`} defaultValue={selectedShot.video_prompt} name="video_prompt" />
                        </label>
                      </div>

                      <div className="mt-4 grid grid-cols-2 gap-2">
                        <Button size="sm" variant="outline" type="button" onClick={() => void regenerateShot(selectedShot.shot_id)} disabled={segmentAction === `copy:${selectedShot.shot_id}`}>
                          {segmentAction === `copy:${selectedShot.shot_id}` ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                          Regenerate copy
                        </Button>
                        <Button size="sm" variant="secondary" type="button" onClick={() => void regenerateClip(selectedShot.shot_id)} disabled={segmentAction === `clip:${selectedShot.shot_id}`}>
                          {segmentAction === `clip:${selectedShot.shot_id}` ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
                          Regenerate segment
                        </Button>
                      </div>

                      <div className="mt-4 rounded-md border border-black/10 bg-[#f5f5f7] p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div>
                            <p className="text-xs font-medium text-slate-700">Assemble / Export</p>
                            <p className="mt-1 text-xs text-slate-500">{timelineTotalSeconds}s timeline{timelineIsStale ? " / stale" : ""}</p>
                          </div>
                          <Badge>{assemblyAspectRatio}</Badge>
                        </div>
                        <div className="mt-3 grid gap-2">
                          <select className={inputClass} value={assemblyAspectRatio} onChange={(event) => setAssemblyAspectRatio(event.target.value as typeof assemblyAspectRatio)}>
                            <option value="9:16">9:16</option>
                            <option value="16:9">16:9</option>
                            <option value="1:1">1:1</option>
                          </select>
                          <label className="flex items-center justify-between gap-3 text-xs text-slate-700">
                            <span>Include timeline audio</span>
                            <input type="checkbox" checked={includeBgm} onChange={(event) => setIncludeBgm(event.target.checked)} />
                          </label>
                          <Button size="sm" variant="secondary" type="button" onClick={assembleVideo} disabled={!generationReadyForAssembly || assembling || assemblyActive}>
                            {assembling ? <Loader2 className="h-4 w-4 animate-spin" /> : <Video className="h-4 w-4" />}
                            {assemblyActive ? "Assembly running" : "Assemble"}
                          </Button>
                        </div>
                      </div>
                    </form>
                  </div>
                ) : (
                  <EmptyState text="No segment selected." />
                )}
              </div>
            ) : (
              <EmptyState text="No storyboard yet." />
            )}
          </Card>

          <details className="rounded-lg border border-black/10 bg-white p-4 shadow-sm shadow-black/[0.03]">
            <summary className="flex cursor-pointer items-center justify-between gap-3 text-sm font-semibold text-slate-950">
              Media Artifacts
              <ImageIcon className="h-5 w-5 text-cyan-700" />
            </summary>
            <p className="mt-1 text-xs leading-5 text-slate-500">Image prompts, cover generation, and provider failures stay separated.</p>
            <div className="grid gap-3 md:grid-cols-2">
              {imageArtifacts.map((artifact) => (
                <div key={artifact.id} className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium text-slate-950">{displayArtifactTitle(artifact)}</p>
                    <Badge>{displayArtifactStatus(artifact)}</Badge>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <ProviderTruthBadge mode={artifactProviderMode(artifact.status, artifact.payload)} />
                    <span className="text-xs text-slate-500">{artifact.provider}</span>
                  </div>
                  {typeof artifact.payload.image_url === "string" ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      alt={displayArtifactTitle(artifact)}
                      className="mt-3 aspect-[9/16] w-full rounded-md border border-black/10 object-cover"
                      src={artifact.payload.image_url}
                    />
                  ) : null}
                  <p className="mt-3 break-words text-xs leading-5 text-slate-500">
                    {humanizeProviderText(artifact.payload.description ?? artifact.payload.image_url ?? artifact.payload.prompt ?? "")}
                  </p>
                  {artifactMessage(artifact) ? (
                    <p className={`mt-2 break-words text-xs leading-5 ${artifact.payload.failure_reason ? "text-rose-700" : "text-amber-700"}`}>
                      {artifactMessage(artifact)}
                    </p>
                  ) : null}
                </div>
              ))}
              {!imageArtifacts.length ? <EmptyState className="md:col-span-2" text="No media artifacts yet." /> : null}
            </div>
          </details>
        </main>

        <aside className="grid gap-4 xl:sticky xl:top-32 xl:self-start">
          <Card className="p-4">
            <CardHeader className="mb-3">
              <div>
                <CardTitle>Preview</CardTitle>
                <CardDescription>{run?.preview.mode ?? "Provider preview appears after generation."}</CardDescription>
              </div>
              <Video className="h-5 w-5 text-slate-800" />
            </CardHeader>
            <div className={`${previewFrameClass(selectedAspectForPreview)} overflow-hidden rounded-[28px] border border-black/10 bg-slate-950 p-4 text-white shadow-inner`}>
              {run && selectedAssembledUrl ? (
                <video className="h-full w-full rounded-[20px] object-cover" controls src={selectedAssembledUrl} />
              ) : typeof run?.preview.video_url === "string" ? (
                <video className="h-full w-full rounded-[20px] object-cover" controls src={run.preview.video_url} />
              ) : typeof run?.preview.cover_image_url === "string" ? (
                <div className="relative h-full overflow-hidden rounded-[20px]">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img alt="Generated cover" className="h-full w-full object-cover" src={run.preview.cover_image_url} />
                  <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-4">
                    <p className="text-xs text-white/60">{run.preview.cover_image_status ?? coverImageArtifact?.status ?? "cover image"}</p>
                    <p className="mt-2 text-lg font-semibold leading-6">{run.preview.cover_text ?? run.script.title}</p>
                  </div>
                </div>
              ) : (
                <div className="flex h-full flex-col justify-between rounded-[20px] border border-white/10 bg-[linear-gradient(180deg,#1d1d1f_0%,#111827_58%,#020617_100%)] p-4">
                  <div>
                    <p className="text-xs text-white/50">{videoArtifact ? displayArtifactStatus(videoArtifact) : "Provider video preview"}</p>
                    <p className="mt-4 text-xl font-semibold leading-7">{run?.preview.cover_text ?? "Run agents to create a preview."}</p>
                    {videoArtifact?.payload.task_id ? (
                      <p className="mt-2 break-words font-mono text-[11px] text-white/45">
                        Task {String(videoArtifact.payload.task_id)} / {String(videoArtifact.payload.task_status ?? "submitted")}
                      </p>
                    ) : null}
                  </div>
                  <div className="space-y-2">
                    {(run?.preview.timeline ?? []).map((item) => (
                      <div key={item.shot_id} className="rounded-md bg-white/10 p-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-medium text-white/85">{item.beat}</span>
                          <span className="font-mono text-[11px] text-white/45">{item.time_range}</span>
                        </div>
                        <p className="mt-1 line-clamp-2 text-xs leading-4 text-white/70">{item.caption}</p>
                      </div>
                    ))}
                    {!run ? <p className="rounded-md bg-white/10 p-3 text-xs leading-5 text-white/60">Storyboard captions will render here.</p> : null}
                  </div>
                </div>
              )}
            </div>
            {run && timelineSegments.length ? (
              <div className="mt-4 grid gap-2">
                {timelineSegments.map((segment) => (
                  <div key={segment.shot_id} className="rounded-lg border border-black/10 bg-[#f5f5f7] p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-xs font-medium text-slate-950">
                          Shot {segment.order_index ?? "-"} / {segment.beat ?? segment.shot_id}
                        </p>
                        <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">
                          {segment.source_label ?? "Draft slice"} {segment.time_range ? `/ ${segment.time_range}` : ""} / {segment.subtitle ?? segment.prompt ?? "No caption yet."}
                        </p>
                      </div>
                      <Badge className={segment.video_url ? "border-emerald-200 bg-emerald-50 text-emerald-700" : statusBadgeClass(String(segment.artifact_status ?? segment.task_status ?? "pending"))}>
                        {timelineSegmentStatusText(segment)}
                      </Badge>
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
            <div className="mt-4 grid gap-2">
              <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-3">
                <p className="text-xs font-medium text-slate-950">Export profile</p>
                <div className="mt-3 grid grid-cols-3 gap-2">
                  {(["9:16", "16:9", "1:1"] as const).map((aspect) => (
                    <button
                      key={aspect}
                      className={`rounded-md border px-3 py-2 text-xs font-medium transition ${
                        assemblyAspectRatio === aspect ? "border-blue-200 bg-blue-50 text-blue-700" : "border-black/10 bg-white text-slate-600"
                      }`}
                      type="button"
                      onClick={() => setAssemblyAspectRatio(aspect)}
                    >
                      {aspect}
                    </button>
                  ))}
                </div>
                <label className="mt-3 flex items-start justify-between gap-3 text-xs text-slate-600">
                  <span>
                    Include timeline audio
                    <span className="mt-1 block leading-5 text-slate-500">
                      {hasUploadedAudio ? "Uploaded audio is used first; otherwise the continuous draft audio is preserved." : "Use the continuous draft audio track when available. TTS remains a placeholder."}
                    </span>
                  </span>
                  <input type="checkbox" checked={includeBgm} onChange={(event) => setIncludeBgm(event.target.checked)} />
                </label>
              </div>
              <Button variant="secondary" onClick={assembleVideo} disabled={!generationReadyForAssembly || assembling || assemblyActive}>
                {assembling ? <Loader2 className="h-4 w-4 animate-spin" /> : <Video className="h-4 w-4" />}
                {assemblyActive ? `Assembling ${assemblyAspectRatio}` : `Assemble ${assemblyAspectRatio}`}
              </Button>
              <Button variant="outline" onClick={downloadMp4} disabled={!selectedAssembledUrl}>
                <Download className="h-4 w-4" />
                Download {assemblyAspectRatio} MP4
              </Button>
              <Button variant="secondary" onClick={exportPackage} disabled={!run || exporting}>
                {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                Export JSON package
              </Button>
              <Button variant="outline" onClick={refreshPreview} disabled={!run}>
                Refresh preview
              </Button>
              <p className="text-xs leading-5 text-slate-500">
                Local assembly exports MP4 with burned subtitles. It preserves draft audio by default, or uses uploaded audio when attached.
              </p>
              {run ? (
                <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-3">
                  <p className="text-xs font-medium text-slate-950">Duration</p>
                  <p className="mt-1 text-xs leading-5 text-slate-500">
                    {selectedAssembledUrl
                      ? `Assembled ${String(run.preview.assembled_duration_seconds)}s at ${String(run.preview.assembled_resolution ?? "720x1280")} for ${String(run.preview.assembled_aspect_ratio ?? assemblyAspectRatio)}.`
                      : run.preview.provider_duration_seconds
                      ? `Rendered ${String(run.preview.provider_duration_seconds)}s.`
                      : `Target ${String(run.script.duration_seconds ?? form.durationSeconds)}s. Video provider output is not available yet.`}
                  </p>
                  {assembledVideoArtifact?.payload.has_audio === true ? (
                    <p className="mt-1 text-xs leading-5 text-slate-500">
                      {audioSourceLabel(assembledVideoArtifact.payload.audio_source)}. TTS voiceover is still a placeholder.
                    </p>
                  ) : assembledVideoArtifact?.payload.has_audio === false ? (
                    <p className="mt-1 text-xs leading-5 text-slate-500">No usable audio track was found. TTS voiceover is a placeholder; subtitles are burned into the picture.</p>
                  ) : null}
                </div>
              ) : null}
            </div>
            {run ? (
              <div className="mt-4 grid gap-3">
                <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-3">
                  <p className="text-xs font-medium text-slate-950">Voice and subtitle track</p>
                  <p className="mt-1 text-xs leading-5 text-slate-500">
                    {String(run.preview.voice_track ? "TTS lines ready, audio provider pending" : "Voice track waits for render")} /{" "}
                    {String(run.preview.subtitle_track ? "subtitle cues ready" : "subtitle cues pending")}
                  </p>
                </div>
                <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-3">
                  <p className="text-xs font-medium text-slate-950">BGM plan</p>
                  <p className="mt-1 text-xs leading-5 text-slate-500">{String((run.preview.bgm_plan as { mix_notes?: string } | undefined)?.mix_notes ?? "No BGM plan yet")}</p>
                </div>
              </div>
            ) : null}
          </Card>

          <details className="rounded-lg border border-black/10 bg-white p-4 shadow-sm shadow-black/[0.03]">
            <summary className="flex cursor-pointer items-center justify-between gap-3 text-sm font-semibold text-slate-950">
              My Assets Used
              <FileUp className="h-5 w-5 text-blue-600" />
            </summary>
            <p className="mt-1 text-xs leading-5 text-slate-500">{run ? `${run.assets.length} private assets attached to this run.` : "Uploaded files are attached only to this run."}</p>
            <div className="space-y-3">
              {(run?.assets ?? []).map((asset) => (
                <div key={asset.id} className="rounded-lg border border-black/10 bg-[#f5f5f7] p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="min-w-0 truncate text-sm font-medium text-slate-950">{asset.filename}</p>
                    <Badge>{asset.asset_kind}</Badge>
                  </div>
                  <p className="mt-2 break-words text-xs leading-5 text-slate-500">{asset.description}</p>
                </div>
              ))}
              {!run?.assets.length ? <EmptyState text="No private assets attached yet." /> : null}
            </div>
          </details>

          <details className="rounded-lg border border-black/10 bg-white p-4 shadow-sm shadow-black/[0.03]">
            <summary className="flex cursor-pointer items-center justify-between gap-3 text-sm font-semibold text-slate-950">
              Compliance
              {run?.compliance.passed ? <CheckCircle2 className="h-5 w-5 text-emerald-600" /> : <ShieldCheck className="h-5 w-5 text-slate-500" />}
            </summary>
            <p className="mt-1 text-xs leading-5 text-slate-500">{run?.compliance.final_delivery ?? "Render & Review Agent will add checks."}</p>
            <div className="space-y-3">
              {(run?.compliance.checks ?? []).map((check) => (
                <div key={check.name} className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
                  <Badge className="border-emerald-200 bg-emerald-50 text-emerald-700">{check.status}</Badge>
                  <p className="mt-3 text-sm font-medium text-slate-950">{check.name}</p>
                  <p className="mt-1 text-xs leading-5 text-slate-500">{check.note}</p>
                </div>
              ))}
              {!run ? <EmptyState text="No compliance report yet." /> : null}
            </div>
          </details>
        </aside>
      </section>
    </>
  );
}

function EmptyState({ text, className = "" }: { text: string; className?: string }) {
  return (
    <div className={`rounded-md border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500 ${className}`}>
      {text}
    </div>
  );
}
