"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type DragEvent } from "react";
import { ArrowLeft, ArrowRight, BarChart3, Download, Film, GripVertical, Loader2, Plus, RefreshCcw, Save, Scissors, Trash2, Video } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  assembleGenerationPreview,
  assembledVideoUrl,
  assetFileUrl,
  editorClipVideoUrl,
  getEditorTimeline,
  getGenerationRun,
  listAssets,
  listGenerationRuns,
  regenerateShotClip,
  updateEditorTimeline,
  type AssetLibraryItem,
  type AssetSlice,
  type EditorTimeline,
  type EditorTimelineClip,
  type GenerationRun,
  type TimelineSegment,
} from "@/lib/api";

const inputClass =
  "mt-1 w-full rounded-md border border-black/10 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-300 focus:ring-4 focus:ring-blue-100";
const textareaClass =
  "mt-1 w-full rounded-md border border-black/10 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-300 focus:ring-4 focus:ring-blue-100";

type SliceOption = {
  slice: AssetSlice;
  asset: AssetLibraryItem;
  label: string;
};

export default function EditorPage() {
  const [runs, setRuns] = useState<GenerationRun[]>([]);
  const [runId, setRunId] = useState("");
  const [run, setRun] = useState<GenerationRun | null>(null);
  const [timeline, setTimeline] = useState<EditorTimeline | null>(null);
  const [clips, setClips] = useState<EditorTimelineClip[]>([]);
  const [selectedClipId, setSelectedClipId] = useState("");
  const [assets, setAssets] = useState<AssetLibraryItem[]>([]);
  const [selectedAssetSliceId, setSelectedAssetSliceId] = useState("");
  const [assemblyAspectRatio, setAssemblyAspectRatio] = useState<"9:16" | "16:9" | "1:1">("9:16");
  const [includeBgm, setIncludeBgm] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [assembling, setAssembling] = useState(false);
  const [regeneratingShotId, setRegeneratingShotId] = useState("");
  const [draggedClipId, setDraggedClipId] = useState("");
  const [dropTargetClipId, setDropTargetClipId] = useState("");
  const [cutStartSeconds, setCutStartSeconds] = useState(0);
  const [cutEndSeconds, setCutEndSeconds] = useState(1);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([listGenerationRuns(), listAssets()])
      .then(([nextRuns, nextAssets]) => {
        if (!active) {
          return;
        }
        setRuns(nextRuns);
        setAssets(nextAssets);
        if (!runId && nextRuns[0]) {
          setRunId(nextRuns[0].run_id);
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load editor data"))
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [runId]);

  useEffect(() => {
    if (!runId) {
      return;
    }
    void loadRun(runId);
  }, [runId]);

  useEffect(() => {
    if (!runId || !run) {
      return;
    }
    const active = shouldPollRun(run);
    if (!active) {
      return;
    }
    const timer = window.setInterval(() => {
      void loadRun(runId, { quiet: true });
    }, 5000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, run?.preview.assembly_status, run?.preview.video_task_status, run?.preview.replacement_clip_status]);

  const timelineSegments = useMemo<TimelineSegment[]>(() => run?.preview.timeline_segments ?? [], [run]);
  const selectedClip = useMemo(() => clips.find((clip) => clip.clip_id === selectedClipId) ?? clips[0] ?? null, [clips, selectedClipId]);
  const selectedClipSegment = useMemo(
    () => timelineSegments.find((segment) => segment.shot_id === selectedClip?.shot_id) ?? null,
    [selectedClip, timelineSegments],
  );
  const sliceOptions = useMemo<SliceOption[]>(
    () =>
      assets
        .filter((asset) => asset.content_type.startsWith("video/"))
        .flatMap((asset) =>
          asset.slices.map((slice) => ({
            asset,
            slice,
            label: `${asset.filename} / slice ${slice.order_index} / ${slice.start_seconds}-${slice.end_seconds}s`,
          })),
        ),
    [assets],
  );
  const selectedSliceOption = useMemo(
    () => sliceOptions.find((option) => option.slice.id === (selectedClip?.asset_slice_id || selectedAssetSliceId)) ?? null,
    [selectedAssetSliceId, selectedClip, sliceOptions],
  );
  const assembledExports = run?.preview.assembled_exports ?? {};
  const assembledUrl =
    run && (assembledExports[assemblyAspectRatio] || run.preview.assembled_aspect_ratio === assemblyAspectRatio)
      ? assembledVideoUrl(run.run_id, assemblyAspectRatio)
      : null;
  const mainVideoUrl = assembledUrl ?? run?.preview.video_url ?? run?.preview.draft_video_url ?? "";
  const totalSeconds = clips.reduce((total, clip) => total + Math.max(1, Number(clip.duration_seconds || 1)), 0);
  const selectedSourceMax = selectedClip ? clipSourceMax(selectedClip, selectedClipSegment, selectedSliceOption) : 12;
  const assemblyActive = run?.preview.assembly_status === "queued" || run?.preview.assembly_status === "running";
  const hasVisualAnchors = useMemo(() => hasRunVisualAnchors(run), [run]);

  async function loadRun(id: string, options: { quiet?: boolean } = {}) {
    if (!options.quiet) {
      setError("");
    }
    const [nextRun, nextTimeline] = await Promise.all([getGenerationRun(id), getEditorTimeline(id)]);
    setRun(nextRun);
    setTimeline(nextTimeline);
    setClips(recalculateClips(nextTimeline.clips));
    setSelectedClipId((current) => current || nextTimeline.clips[0]?.clip_id || "");
  }

  function updateClip(clipId: string, patch: Partial<EditorTimelineClip>) {
    setMessage("");
    setClips((current) =>
      recalculateClips(
        current.map((clip) => {
          if (clip.clip_id !== clipId) {
            return clip;
          }
          const next = { ...clip, ...patch };
          const sourceStart = Math.max(0, Number(next.source_start_seconds || 0));
          const sourceEnd = Math.max(sourceStart + 1, Number(next.source_end_seconds || sourceStart + Number(next.duration_seconds || 1)));
          return {
            ...next,
            source_start_seconds: sourceStart,
            source_end_seconds: sourceEnd,
            duration_seconds: Math.max(1, sourceEnd - sourceStart),
          };
        }),
      ),
    );
  }

  function appendSegment(segment: TimelineSegment, sourceType: EditorTimelineClip["source_type"]) {
    const clip = clipFromSegment(segment, sourceType);
    setClips((current) => insertClipAfterSelection(current, clip, selectedClipId));
    setSelectedClipId(clip.clip_id);
    setMessage("");
  }

  function replaceSegmentSource(segment: TimelineSegment, sourceType: EditorTimelineClip["source_type"]) {
    const replacement = clipFromSegment(segment, sourceType);
    setClips((current) => {
      const targetIndex = current.findIndex((clip) => clip.shot_id === segment.shot_id && clip.source_type !== "asset_slice");
      if (targetIndex < 0) {
        return insertClipAfterSelection(current, replacement, selectedClipId);
      }
      const next = current.filter(
        (clip, index) =>
          index === targetIndex ||
          clip.shot_id !== segment.shot_id ||
          clip.source_type === "asset_slice",
      );
      next[targetIndex] = {
        ...replacement,
        clip_id: current[targetIndex].clip_id,
        order_index: current[targetIndex].order_index,
      };
      return recalculateClips(next);
    });
    setSelectedClipId((current) => current || replacement.clip_id);
    setMessage(`${segment.beat ?? segment.shot_id} will use the ${sourceTypeLabel(sourceType).toLowerCase()} source. Save to apply.`);
  }

  function appendAssetSlice(sliceId: string) {
    const option = sliceOptions.find((item) => item.slice.id === sliceId);
    if (!option) {
      return;
    }
    const duration = Math.max(1, option.slice.end_seconds - option.slice.start_seconds || 4);
    const clip: EditorTimelineClip = {
      clip_id: `asset-${option.slice.id}-${Date.now()}`,
      source_type: "asset_slice",
      shot_id: null,
      asset_slice_id: option.slice.id,
      label: option.label,
      subtitle: option.slice.summary,
      voiceover: "",
      source_start_seconds: option.slice.start_seconds,
      source_end_seconds: option.slice.start_seconds + duration,
      duration_seconds: duration,
      enabled: true,
      source_label: "Asset library slice",
      source_url: assetFileUrl(option.asset.id),
      status: option.asset.analysis_status,
    };
    setClips((current) => insertClipAfterSelection(current, clip, selectedClipId));
    setSelectedClipId(clip.clip_id);
    setMessage("");
  }

  function removeSelectedClip() {
    if (!selectedClip || clips.length <= 1) {
      return;
    }
    const next = recalculateClips(clips.filter((clip) => clip.clip_id !== selectedClip.clip_id));
    setClips(next);
    setSelectedClipId(next[0]?.clip_id ?? "");
    setMessage("");
  }

  function removeTimelineRange() {
    const start = Math.max(0, Math.min(cutStartSeconds, cutEndSeconds - 1));
    const end = Math.min(totalSeconds, Math.max(cutEndSeconds, start + 1));
    if (end <= start || !clips.length) {
      return;
    }
    const nextClips: EditorTimelineClip[] = [];
    for (const clip of clips) {
      const clipStart = Number(clip.timeline_start_seconds ?? 0);
      const clipEnd = Number(clip.timeline_end_seconds ?? clipStart + clip.duration_seconds);
      if (clipEnd <= start || clipStart >= end) {
        nextClips.push(clip);
        continue;
      }
      const beforeDuration = Math.max(0, start - clipStart);
      const afterDuration = Math.max(0, clipEnd - end);
      if (beforeDuration > 0) {
        nextClips.push({
          ...clip,
          clip_id: `${clip.clip_id}-before-${Date.now()}`,
          source_end_seconds: clip.source_start_seconds + beforeDuration,
          duration_seconds: beforeDuration,
        });
      }
      if (afterDuration > 0) {
        const afterSourceStart = clip.source_start_seconds + Math.max(0, end - clipStart);
        nextClips.push({
          ...clip,
          clip_id: `${clip.clip_id}-after-${Date.now()}`,
          source_start_seconds: afterSourceStart,
          source_end_seconds: afterSourceStart + afterDuration,
          duration_seconds: afterDuration,
        });
      }
    }
    const recalculated = recalculateClips(nextClips);
    setClips(recalculated);
    setSelectedClipId(recalculated[0]?.clip_id ?? "");
    setMessage(`Removed ${start}-${end}s from the editor timeline. Save to apply.`);
  }

  function resetTimelineFromGeneratedSegments() {
    const next = recalculateClips(timelineSegments.slice(0, 3).map((segment) => clipFromSegment(segment, "draft_segment")));
    setClips(next);
    setSelectedClipId(next[0]?.clip_id ?? "");
    setMessage("Timeline reset from generated segments. Save to apply.");
  }

  function moveSelectedClip(direction: -1 | 1) {
    if (!selectedClip) {
      return;
    }
    setClips((current) => moveClip(current, selectedClip.clip_id, direction));
    setMessage("");
  }

  function handleClipDragStart(event: DragEvent<HTMLButtonElement>, clipId: string) {
    setDraggedClipId(clipId);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", clipId);
  }

  function handleClipDrop(event: DragEvent<HTMLButtonElement>, targetClipId: string) {
    event.preventDefault();
    const sourceClipId = draggedClipId || event.dataTransfer.getData("text/plain");
    setDraggedClipId("");
    setDropTargetClipId("");
    if (!sourceClipId || sourceClipId === targetClipId) {
      return;
    }
    setClips((current) => reorderClipBefore(current, sourceClipId, targetClipId));
    setSelectedClipId(sourceClipId);
    setMessage("");
  }

  async function saveTimeline() {
    if (!run) {
      return null;
    }
    setSaving(true);
    setError("");
    try {
      const nextRun = await updateEditorTimeline(run.run_id, clips);
      const nextTimeline = await getEditorTimeline(run.run_id);
      setRun(nextRun);
      setTimeline(nextTimeline);
      setClips(recalculateClips(nextTimeline.clips));
      setMessage("Timeline saved.");
      return nextRun;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save timeline");
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function assembleTimeline() {
    if (!run) {
      return;
    }
    setAssembling(true);
    setError("");
    setMessage("");
    try {
      await updateEditorTimeline(run.run_id, clips);
      const queued = await assembleGenerationPreview(run.run_id, {
        aspect_ratio: assemblyAspectRatio,
        include_bgm: includeBgm,
      });
      setRun(queued);
      setMessage("Assembly queued.");
      window.setTimeout(() => void loadRun(run.run_id, { quiet: true }), 2500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Assembly failed");
    } finally {
      setAssembling(false);
    }
  }

  async function regenerateSelectedClip() {
    if (!run || !selectedClip?.shot_id) {
      return;
    }
    setRegeneratingShotId(selectedClip.shot_id);
    setError("");
    try {
      const nextRun = await regenerateShotClip(run.run_id, selectedClip.shot_id);
      const nextTimeline = await getEditorTimeline(run.run_id);
      setRun(nextRun);
      setTimeline(nextTimeline);
      setClips(recalculateClips(nextTimeline.clips));
      setMessage(`Regeneration queued for ${selectedClip.shot_id}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Segment regeneration failed");
    } finally {
      setRegeneratingShotId("");
    }
  }

  function downloadMp4() {
    if (!run || !assembledUrl) {
      return;
    }
    const link = document.createElement("a");
    link.href = assembledUrl;
    link.download = `viralcutai-editor-${run.run_id}-${assemblyAspectRatio.replace(":", "x")}.mp4`;
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Step 4 / Edit Video"
        title="Edit and assemble the video"
        description="Trim generated segments, append replacement clips or private asset slices, then assemble a local MP4."
        badges={["Editor Timeline V2", "Drag reorder", "Synced audio assembly"]}
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <main className="grid gap-6">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Run</CardTitle>
                <CardDescription>{run ? run.summary : loading ? "Loading runs." : "Select a generated run."}</CardDescription>
              </div>
              <Film className="h-5 w-5 text-slate-700" />
            </CardHeader>
            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
              <select className={inputClass} value={runId} onChange={(event) => setRunId(event.target.value)}>
                {runs.map((item) => (
                  <option key={item.run_id} value={item.run_id}>
                    {item.request_payload.product_name} / {new Date(item.created_at).toLocaleString()}
                  </option>
                ))}
              </select>
              <Button variant="outline" onClick={() => runId && void loadRun(runId)} disabled={!runId || loading}>
                <RefreshCcw className="h-4 w-4" />
                Refresh
              </Button>
            </div>
            {error ? <p className="mt-3 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</p> : null}
            {message ? <p className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">{message}</p> : null}
          </Card>

          <Card className="p-4">
            <CardHeader className="mb-3">
              <div>
                <CardTitle>Cut Desk</CardTitle>
                <CardDescription>{assembledUrl ? "Review the assembled output beside the three 4s source clips." : "Review the 12s draft beside three independent 4s source clips."}</CardDescription>
              </div>
              <Video className="h-5 w-5 text-blue-700" />
            </CardHeader>
            <div className="grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(360px,1.05fr)]">
              <div className="min-w-0">
                <div className="mx-auto max-w-[360px] overflow-hidden rounded-lg border border-black/10 bg-slate-950">
                  {mainVideoUrl ? (
                    <video className="aspect-[9/16] w-full bg-black object-contain" controls src={mainVideoUrl} />
                  ) : (
                    <div className="flex aspect-[9/16] items-center justify-center text-sm text-white/55">No video output yet.</div>
                  )}
                </div>
                <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
                  <Badge>{assembledUrl ? "Assembled" : "Draft"}</Badge>
                  <Badge>{run?.preview.assembled_has_audio ? "Audio" : "Silent / draft audio pending"}</Badge>
                </div>
              </div>
              <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-1 2xl:grid-cols-3">
                {timelineSegments.slice(0, 3).map((segment) => (
                  <SegmentPreview
                    key={segment.shot_id}
                    onAppendDraft={() => appendSegment(segment, "draft_segment")}
                    onReplaceReplacement={() => replaceSegmentSource(segment, "replacement_clip")}
                    runId={run?.run_id ?? ""}
                    segment={segment}
                  />
                ))}
                {!timelineSegments.length ? <p className="rounded-md bg-[#f5f5f7] p-4 text-sm text-slate-500 md:col-span-3 xl:col-span-1 2xl:col-span-3">No generated segments yet.</p> : null}
              </div>
            </div>
          </Card>

          <Card className="p-4">
            <CardHeader className="mb-3">
              <div>
                <CardTitle>Timeline Cut</CardTitle>
                <CardDescription>{timeline ? `${totalSeconds}s / ${clips.length} clips. Select a block, then drag the trim handles below.` : "No editor timeline loaded."}</CardDescription>
              </div>
              <Scissors className="h-5 w-5 text-rose-600" />
            </CardHeader>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap gap-2">
                <Badge>{totalSeconds}s output</Badge>
                <Badge>{clips.length} clips</Badge>
                {selectedClip ? <Badge>{selectedClip.source_start_seconds}-{selectedClip.source_end_seconds}s selected source</Badge> : null}
                {run?.preview.editor_timeline_stale ? <Badge className="border-amber-200 bg-amber-50 text-amber-700">Unsaved assembly</Badge> : null}
              </div>
              <Button size="sm" variant="outline" onClick={resetTimelineFromGeneratedSegments} disabled={!timelineSegments.length}>
                <RefreshCcw className="h-4 w-4" />
                Reset
              </Button>
            </div>
            <div className="overflow-x-auto pb-2">
              <div className="min-w-[720px] rounded-lg border border-black/10 bg-[#f5f5f7] p-3">
                <TimelineRuler totalSeconds={Math.max(12, totalSeconds)} />
                <div className="mt-2 flex min-h-20 gap-2">
                  {clips.map((clip) => {
                    const active = selectedClip?.clip_id === clip.clip_id;
                    return (
                      <button
                        key={clip.clip_id}
                        className={`min-w-28 rounded-md border p-3 text-left transition ${
                          active
                            ? "border-blue-300 bg-white shadow-sm shadow-blue-100"
                            : dropTargetClipId === clip.clip_id
                              ? "border-emerald-300 bg-emerald-50"
                              : "border-black/10 bg-white/80 hover:border-blue-200"
                        }`}
                        draggable
                        style={{ flexGrow: Math.max(1, Number(clip.duration_seconds || 1)), flexBasis: 0 }}
                        type="button"
                        onDragEnd={() => {
                          setDraggedClipId("");
                          setDropTargetClipId("");
                        }}
                        onDragOver={(event) => {
                          event.preventDefault();
                          event.dataTransfer.dropEffect = "move";
                          setDropTargetClipId(clip.clip_id);
                        }}
                        onDragStart={(event) => handleClipDragStart(event, clip.clip_id)}
                        onDrop={(event) => handleClipDrop(event, clip.clip_id)}
                        onClick={() => setSelectedClipId(clip.clip_id)}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <GripVertical className="h-4 w-4 text-slate-400" />
                            <Badge>{clip.order_index ?? "-"}</Badge>
                          </div>
                          <span className="font-mono text-[11px] text-slate-500">{clip.duration_seconds}s</span>
                        </div>
                        <p className="mt-2 line-clamp-1 text-sm font-medium text-slate-950">{clip.label}</p>
                        <p className="mt-2 truncate text-[11px] text-slate-500">
                          {sourceTypeLabel(clip.source_type)} / keep {clip.source_start_seconds}-{clip.source_end_seconds}s
                        </p>
                      </button>
                    );
                  })}
                </div>
                {selectedClip ? (
                  <TimelineTrimControls
                    maxSeconds={selectedSourceMax}
                    onChange={(patch) => updateClip(selectedClip.clip_id, patch)}
                    clip={selectedClip}
                  />
                ) : null}
                <div className="mt-4 rounded-md border border-black/10 bg-white p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="text-xs font-semibold text-slate-950">Remove range from full timeline</p>
                      <p className="mt-1 font-mono text-[11px] text-slate-500">Cut out {cutStartSeconds}-{cutEndSeconds}s from the current output timeline</p>
                    </div>
                    <Button size="sm" variant="outline" onClick={removeTimelineRange} disabled={cutEndSeconds <= cutStartSeconds || totalSeconds <= 1}>
                      <Trash2 className="h-4 w-4" />
                      Remove range
                    </Button>
                  </div>
                  <div className="mt-3 grid gap-3 md:grid-cols-2">
                    <label className="block text-xs text-slate-600">
                      Range start
                      <input
                        className="mt-2 w-full accent-rose-600"
                        max={Math.max(0, totalSeconds - 1)}
                        min={0}
                        step={1}
                        type="range"
                        value={Math.min(cutStartSeconds, Math.max(0, totalSeconds - 1))}
                        onChange={(event) => {
                          const value = Number(event.target.value);
                          setCutStartSeconds(value);
                          setCutEndSeconds((current) => Math.max(value + 1, current));
                        }}
                      />
                    </label>
                    <label className="block text-xs text-slate-600">
                      Range end
                      <input
                        className="mt-2 w-full accent-rose-600"
                        max={Math.max(1, totalSeconds)}
                        min={1}
                        step={1}
                        type="range"
                        value={Math.min(Math.max(cutEndSeconds, cutStartSeconds + 1), Math.max(1, totalSeconds))}
                        onChange={(event) => setCutEndSeconds(Math.max(cutStartSeconds + 1, Number(event.target.value)))}
                      />
                    </label>
                  </div>
                </div>
              </div>
            </div>
          </Card>
        </main>

        <aside className="grid gap-6 xl:sticky xl:top-24 xl:self-start">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Clip Inspector</CardTitle>
                <CardDescription>{selectedClip ? selectedClip.label : "Select a clip."}</CardDescription>
              </div>
              <Scissors className="h-5 w-5 text-slate-700" />
            </CardHeader>
            {selectedClip ? (
              <div className="space-y-4">
                <div className={`rounded-lg border p-3 ${hasVisualAnchors ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
                  <p className="text-xs font-medium">{hasVisualAnchors ? "Style anchors available" : "Style drift risk"}</p>
                  <p className="mt-1 text-xs leading-5">
                    {hasVisualAnchors
                      ? "Selected product assets or slices will be included as continuity anchors for segment regeneration."
                      : "No private product asset/slice is pinned to this run. A regenerated segment may differ from the original draft style."}
                  </p>
                </div>
                <label className="block text-xs text-slate-600">
                  Label
                  <input className={inputClass} value={selectedClip.label} onChange={(event) => updateClip(selectedClip.clip_id, { label: event.target.value })} />
                </label>
                <label className="block text-xs text-slate-600">
                  Source
                  <select
                    className={inputClass}
                    value={selectedClip.source_type}
                    onChange={(event) => {
                      const sourceType = event.target.value as EditorTimelineClip["source_type"];
                      if (sourceType === "asset_slice") {
                        const option = selectedSliceOption ?? sliceOptions[0];
                        if (option) {
                          updateClip(selectedClip.clip_id, {
                            source_type: sourceType,
                            asset_slice_id: option.slice.id,
                            source_start_seconds: option.slice.start_seconds,
                            source_end_seconds: Math.max(option.slice.start_seconds + 1, option.slice.end_seconds),
                            source_label: "Asset library slice",
                            source_url: assetFileUrl(option.asset.id),
                          });
                          setSelectedAssetSliceId(option.slice.id);
                        }
                        return;
                      }
                      updateClip(selectedClip.clip_id, {
                        source_type: sourceType,
                        asset_slice_id: null,
                        source_start_seconds: sourceType === "replacement_clip" ? 0 : selectedClipSegment?.start_seconds ?? 0,
                        source_end_seconds:
                          sourceType === "replacement_clip"
                            ? selectedClip.duration_seconds
                            : selectedClipSegment?.end_seconds ?? selectedClip.source_start_seconds + selectedClip.duration_seconds,
                      });
                    }}
                  >
                    <option value="draft_segment">Draft segment</option>
                    <option value="replacement_clip">Replacement clip</option>
                    <option value="asset_slice">Asset slice</option>
                  </select>
                </label>
                {selectedClip.source_type !== "asset_slice" ? (
                  <label className="block text-xs text-slate-600">
                    Generated segment
                    <select className={inputClass} value={selectedClip.shot_id ?? ""} onChange={(event) => updateClip(selectedClip.clip_id, { shot_id: event.target.value })}>
                      {timelineSegments.map((segment) => (
                        <option key={segment.shot_id} value={segment.shot_id}>
                          Shot {segment.order_index}: {segment.beat}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <label className="block text-xs text-slate-600">
                    Asset slice
                    <select
                      className={inputClass}
                      value={selectedClip.asset_slice_id ?? ""}
                      onChange={(event) => {
                        const option = sliceOptions.find((item) => item.slice.id === event.target.value);
                        if (!option) {
                          return;
                        }
                        setSelectedAssetSliceId(option.slice.id);
                        updateClip(selectedClip.clip_id, {
                          asset_slice_id: option.slice.id,
                          label: option.label,
                          source_start_seconds: option.slice.start_seconds,
                          source_end_seconds: Math.max(option.slice.start_seconds + 1, option.slice.end_seconds),
                          source_url: assetFileUrl(option.asset.id),
                        });
                      }}
                    >
                      {sliceOptions.map((option) => (
                        <option key={option.slice.id} value={option.slice.id}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-3">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-xs font-medium text-slate-700">Trim</p>
                    <span className="font-mono text-[11px] text-slate-500">
                      {selectedClip.source_start_seconds}-{selectedClip.source_end_seconds}s
                    </span>
                  </div>
                  <label className="mt-3 block text-xs text-slate-600">
                    Start
                    <input
                      className="mt-2 w-full accent-blue-600"
                      max={Math.max(1, selectedSourceMax - 1)}
                      min={0}
                      type="range"
                      value={Math.min(selectedClip.source_start_seconds, selectedSourceMax - 1)}
                      onChange={(event) => {
                        const start = Number(event.target.value);
                        const end = Math.max(start + 1, selectedClip.source_end_seconds);
                        updateClip(selectedClip.clip_id, { source_start_seconds: start, source_end_seconds: Math.min(end, selectedSourceMax) });
                      }}
                    />
                  </label>
                  <label className="mt-3 block text-xs text-slate-600">
                    End
                    <input
                      className="mt-2 w-full accent-blue-600"
                      max={selectedSourceMax}
                      min={1}
                      type="range"
                      value={Math.min(selectedClip.source_end_seconds, selectedSourceMax)}
                      onChange={(event) => {
                        const end = Number(event.target.value);
                        updateClip(selectedClip.clip_id, { source_end_seconds: Math.max(selectedClip.source_start_seconds + 1, end) });
                      }}
                    />
                  </label>
                </div>
                <label className="block text-xs text-slate-600">
                  Subtitle
                  <input className={inputClass} value={selectedClip.subtitle} onChange={(event) => updateClip(selectedClip.clip_id, { subtitle: event.target.value })} />
                </label>
                <label className="block text-xs text-slate-600">
                  Voiceover note
                  <textarea className={`${textareaClass} min-h-20`} value={selectedClip.voiceover} onChange={(event) => updateClip(selectedClip.clip_id, { voiceover: event.target.value })} />
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <Button variant="secondary" onClick={saveTimeline} disabled={saving}>
                    {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                    Save
                  </Button>
                  <Button variant="outline" onClick={removeSelectedClip} disabled={clips.length <= 1}>
                    <Trash2 className="h-4 w-4" />
                    Cut
                  </Button>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Button variant="outline" onClick={() => moveSelectedClip(-1)} disabled={!selectedClip || (selectedClip.order_index ?? 1) <= 1}>
                    <ArrowLeft className="h-4 w-4" />
                    Move left
                  </Button>
                  <Button variant="outline" onClick={() => moveSelectedClip(1)} disabled={!selectedClip || (selectedClip.order_index ?? clips.length) >= clips.length}>
                    <ArrowRight className="h-4 w-4" />
                    Move right
                  </Button>
                </div>
                <Button className="w-full" variant="outline" onClick={regenerateSelectedClip} disabled={!selectedClip.shot_id || regeneratingShotId === selectedClip.shot_id}>
                  {regeneratingShotId === selectedClip.shot_id ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
                  Regenerate selected segment
                </Button>
              </div>
            ) : (
              <p className="rounded-md bg-[#f5f5f7] p-4 text-sm text-slate-500">No clip selected.</p>
            )}
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Append</CardTitle>
                <CardDescription>{sliceOptions.length} video slices available.</CardDescription>
              </div>
              <Plus className="h-5 w-5 text-emerald-700" />
            </CardHeader>
            <div className="grid gap-3">
              <select className={inputClass} value={selectedAssetSliceId} onChange={(event) => setSelectedAssetSliceId(event.target.value)}>
                <option value="">Select asset slice</option>
                {sliceOptions.map((option) => (
                  <option key={option.slice.id} value={option.slice.id}>
                    {option.label}
                  </option>
                ))}
              </select>
              <Button variant="secondary" onClick={() => appendAssetSlice(selectedAssetSliceId)} disabled={!selectedAssetSliceId}>
                <Plus className="h-4 w-4" />
                Append asset slice
              </Button>
            </div>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Assemble</CardTitle>
                <CardDescription>{totalSeconds}s editor timeline</CardDescription>
              </div>
              <Video className="h-5 w-5 text-slate-800" />
            </CardHeader>
            <div className="space-y-3">
              <select className={inputClass} value={assemblyAspectRatio} onChange={(event) => setAssemblyAspectRatio(event.target.value as typeof assemblyAspectRatio)}>
                <option value="9:16">9:16</option>
                <option value="16:9">16:9</option>
                <option value="1:1">1:1</option>
              </select>
              <label className="flex items-center justify-between gap-3 text-xs text-slate-700">
                <span>Include draft or uploaded audio</span>
                <input type="checkbox" checked={includeBgm} onChange={(event) => setIncludeBgm(event.target.checked)} />
              </label>
              <Button className="w-full" variant="secondary" onClick={assembleTimeline} disabled={!run || assembling || assemblyActive}>
                {assembling || assemblyActive ? <Loader2 className="h-4 w-4 animate-spin" /> : <Video className="h-4 w-4" />}
                {assemblyActive ? "Assembly running" : "Assemble timeline"}
              </Button>
              <Button className="w-full" variant="outline" onClick={downloadMp4} disabled={!assembledUrl}>
                <Download className="h-4 w-4" />
                Download MP4
              </Button>
              {assembledUrl ? (
                <Link href="/analytics">
                  <Button className="w-full">
                    <BarChart3 className="h-4 w-4" />
                    Analyze run
                  </Button>
                </Link>
              ) : (
                <Button className="w-full" disabled>
                  <BarChart3 className="h-4 w-4" />
                  Analyze run
                </Button>
              )}
            </div>
          </Card>
        </aside>
      </div>
    </div>
  );
}

function SegmentPreview({
  segment,
  onAppendDraft,
  onReplaceReplacement,
  runId,
}: {
  segment: TimelineSegment;
  onAppendDraft: () => void;
  onReplaceReplacement: () => void;
  runId: string;
}) {
  const sourceType = segment.source === "replacement_clip" && segment.replacement_video_url ? "replacement_clip" : "draft_segment";
  const videoUrl = runId && (segment.draft_video_url || segment.replacement_video_url)
    ? editorClipVideoUrl(runId, { shotId: segment.shot_id, sourceType })
    : segmentVideoUrl(segment);
  const replacementReady = Boolean(segment.replacement_video_url);
  return (
    <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-3">
      <div className="grid gap-3 xl:grid-cols-[92px_minmax(0,1fr)] 2xl:grid-cols-1">
        <div className="overflow-hidden rounded-md bg-slate-950">
          {videoUrl ? <video className="aspect-[9/16] h-full w-full object-cover" controls preload="metadata" src={videoUrl} /> : <div className="aspect-[9/16]" />}
        </div>
        <div className="min-w-0">
          <div className="flex items-center justify-between gap-2">
            <Badge>Shot {segment.order_index ?? "-"}</Badge>
            <span className="font-mono text-[11px] text-slate-500">{segment.duration_seconds ?? 4}s clip</span>
          </div>
          <p className="mt-2 line-clamp-2 text-sm font-medium text-slate-950">{segment.beat ?? segment.shot_id}</p>
          <p className="mt-1 font-mono text-[11px] text-slate-500">{segment.start_seconds ?? 0}-{segment.end_seconds ?? Number(segment.start_seconds ?? 0) + Number(segment.duration_seconds ?? 4)}s from draft</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={onAppendDraft}>
              <Plus className="h-4 w-4" />
              Draft
            </Button>
            <Button size="sm" variant="secondary" onClick={onReplaceReplacement} disabled={!replacementReady}>
              <RefreshCcw className="h-4 w-4" />
              Use replacement
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function TimelineRuler({ totalSeconds }: { totalSeconds: number }) {
  const ticks = Array.from({ length: Math.max(2, Math.floor(totalSeconds) + 1) }, (_, index) => index);
  return (
    <div className="grid grid-flow-col auto-cols-fr text-[11px] text-slate-500">
      {ticks.map((tick) => (
        <div key={tick} className="border-l border-slate-300 pl-1">
          {tick}s
        </div>
      ))}
    </div>
  );
}

function TimelineTrimControls({
  clip,
  maxSeconds,
  onChange,
}: {
  clip: EditorTimelineClip;
  maxSeconds: number;
  onChange: (patch: Partial<EditorTimelineClip>) => void;
}) {
  const max = Math.max(1, Math.ceil(maxSeconds));
  const start = Math.min(max - 1, Math.max(0, Number(clip.source_start_seconds || 0)));
  const end = Math.min(max, Math.max(start + 1, Number(clip.source_end_seconds || start + 1)));
  const left = (start / max) * 100;
  const width = ((end - start) / max) * 100;
  return (
    <div className="mt-4 rounded-md border border-black/10 bg-white p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold text-slate-950">Trim selected clip</p>
          <p className="mt-1 font-mono text-[11px] text-slate-500">Keep {start}-{end}s / remove before {start}s and after {end}s</p>
        </div>
        <Badge>{end - start}s output</Badge>
      </div>
      <div className="relative mt-4 h-3 rounded-full bg-slate-200">
        <div className="absolute inset-y-0 rounded-full bg-blue-500" style={{ left: `${left}%`, width: `${width}%` }} />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <label className="block text-xs text-slate-600">
          Trim start
          <input
            className="mt-2 w-full accent-blue-600"
            max={max - 1}
            min={0}
            step={1}
            type="range"
            value={start}
            onChange={(event) => {
              const nextStart = Number(event.target.value);
              onChange({
                source_start_seconds: nextStart,
                source_end_seconds: Math.max(nextStart + 1, end),
              });
            }}
          />
        </label>
        <label className="block text-xs text-slate-600">
          Trim end
          <input
            className="mt-2 w-full accent-blue-600"
            max={max}
            min={1}
            step={1}
            type="range"
            value={end}
            onChange={(event) => {
              const nextEnd = Number(event.target.value);
              onChange({
                source_end_seconds: Math.max(start + 1, nextEnd),
              });
            }}
          />
        </label>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => onChange({ source_start_seconds: 0, source_end_seconds: max })}>
          Full source
        </Button>
        <Button size="sm" variant="outline" onClick={() => onChange({ source_start_seconds: Math.min(max - 1, start + 1), source_end_seconds: end })} disabled={end - start <= 1}>
          Cut first 1s
        </Button>
        <Button size="sm" variant="outline" onClick={() => onChange({ source_start_seconds: start, source_end_seconds: Math.max(start + 1, end - 1) })} disabled={end - start <= 1}>
          Cut last 1s
        </Button>
      </div>
    </div>
  );
}

function shouldPollRun(run: GenerationRun) {
  const statuses = [run.preview.assembly_status, run.preview.video_task_status, run.preview.replacement_clip_status].map((item) => String(item ?? "").toLowerCase());
  return statuses.some((status) => ["queued", "running", "processing", "submitted", "pending"].includes(status));
}

function hasRunVisualAnchors(run: GenerationRun | null) {
  if (!run) {
    return false;
  }
  if ((run.request_payload.asset_ids ?? []).length || (run.request_payload.asset_slice_ids ?? []).length) {
    return true;
  }
  return (run.assets ?? []).some((asset) => asset.content_type.startsWith("image/") || asset.content_type.startsWith("video/"));
}

function recalculateClips(clips: EditorTimelineClip[]) {
  let cursor = 0;
  return clips.map((clip, index) => {
    const start = Math.max(0, Number(clip.source_start_seconds || 0));
    const end = Math.max(start + 1, Number(clip.source_end_seconds || start + Number(clip.duration_seconds || 1)));
    const duration = Math.max(1, end - start);
    const next = {
      ...clip,
      order_index: index + 1,
      source_start_seconds: start,
      source_end_seconds: end,
      duration_seconds: duration,
      timeline_start_seconds: cursor,
      timeline_end_seconds: cursor + duration,
      enabled: true,
    };
    cursor += duration;
    return next;
  });
}

function insertClipAfterSelection(clips: EditorTimelineClip[], clip: EditorTimelineClip, selectedClipId: string) {
  if (!clips.length || !selectedClipId) {
    return recalculateClips([...clips, clip]);
  }
  const index = clips.findIndex((item) => item.clip_id === selectedClipId);
  if (index < 0) {
    return recalculateClips([...clips, clip]);
  }
  return recalculateClips([...clips.slice(0, index + 1), clip, ...clips.slice(index + 1)]);
}

function moveClip(clips: EditorTimelineClip[], clipId: string, direction: -1 | 1) {
  const index = clips.findIndex((clip) => clip.clip_id === clipId);
  if (index < 0) {
    return clips;
  }
  const nextIndex = index + direction;
  if (nextIndex < 0 || nextIndex >= clips.length) {
    return clips;
  }
  const next = [...clips];
  const [item] = next.splice(index, 1);
  next.splice(nextIndex, 0, item);
  return recalculateClips(next);
}

function reorderClipBefore(clips: EditorTimelineClip[], sourceClipId: string, targetClipId: string) {
  const source = clips.find((clip) => clip.clip_id === sourceClipId);
  if (!source) {
    return clips;
  }
  const withoutSource = clips.filter((clip) => clip.clip_id !== sourceClipId);
  const targetIndex = withoutSource.findIndex((clip) => clip.clip_id === targetClipId);
  if (targetIndex < 0) {
    return recalculateClips([...withoutSource, source]);
  }
  return recalculateClips([...withoutSource.slice(0, targetIndex), source, ...withoutSource.slice(targetIndex)]);
}

function clipFromSegment(segment: TimelineSegment, sourceType: EditorTimelineClip["source_type"]): EditorTimelineClip {
  const duration = Math.max(1, Number(segment.duration_seconds || 4));
  const start = sourceType === "replacement_clip" ? 0 : Math.max(0, Number(segment.start_seconds || 0));
  const clipId = `${sourceType}-${segment.shot_id}-${Date.now()}`;
  return {
    clip_id: clipId,
    source_type: sourceType,
    shot_id: segment.shot_id,
    asset_slice_id: null,
    label: `${segment.beat ?? segment.shot_id}`,
    subtitle: segment.subtitle ?? "",
    voiceover: segment.voiceover ?? "",
    source_start_seconds: start,
    source_end_seconds: start + duration,
    duration_seconds: duration,
    enabled: true,
    source_label: sourceTypeLabel(sourceType),
    source_url: sourceType === "replacement_clip" ? segment.replacement_video_url : segment.draft_video_url,
    status: segment.artifact_status ?? segment.task_status ?? "ready",
  };
}

function clipSourceMax(clip: EditorTimelineClip, segment: TimelineSegment | null, sliceOption: SliceOption | null) {
  if (clip.source_type === "asset_slice" && sliceOption) {
    return Math.max(sliceOption.slice.end_seconds || 0, clip.source_end_seconds, clip.source_start_seconds + 1);
  }
  if (clip.source_type === "replacement_clip") {
    return Math.max(clip.source_end_seconds, Number(segment?.duration_seconds || 4), 1);
  }
  return Math.max(clip.source_end_seconds, Number(segment?.end_seconds || 12), 1);
}

function segmentVideoUrl(segment: TimelineSegment) {
  if (segment.replacement_video_url && segment.source === "replacement_clip") {
    return segment.replacement_video_url;
  }
  if (segment.video_url && segment.source !== "asset_slice") {
    return segment.video_url;
  }
  if (segment.draft_video_url) {
    const start = Number(segment.start_seconds ?? 0);
    const end = Number(segment.end_seconds ?? start + Number(segment.duration_seconds ?? 4));
    return `${segment.draft_video_url}#t=${start},${end}`;
  }
  return "";
}

function sourceTypeLabel(sourceType: EditorTimelineClip["source_type"]) {
  if (sourceType === "replacement_clip") {
    return "Replacement";
  }
  if (sourceType === "asset_slice") {
    return "Asset slice";
  }
  return "Draft";
}
