"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ArrowRight, FileVideo, Library, Loader2, Search, Sparkles } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  attachViralSourceVideo,
  buildCreativeTemplate,
  API_BASE,
  listCreativeTemplates,
  listViralFactors,
  listViralVideos,
  type CreativeTemplate,
  type ViralFactor,
  type ViralVideoAnalysis,
} from "@/lib/api";

const inputClass =
  "h-10 w-full rounded-md border border-black/10 bg-white px-3 text-sm outline-none transition focus:border-blue-400 focus:ring-4 focus:ring-blue-100";
const factorOrder = ["hook", "proof", "scene", "trust", "visual", "audio", "cta", "risk"];

export default function ViralLibraryPage() {
  const [videos, setVideos] = useState<ViralVideoAnalysis[]>([]);
  const [factors, setFactors] = useState<ViralFactor[]>([]);
  const [templates, setTemplates] = useState<CreativeTemplate[]>([]);
  const [selectedVideoId, setSelectedVideoId] = useState("");
  const [templateReferenceUidInput, setTemplateReferenceUidInput] = useState("");
  const [templateName, setTemplateName] = useState("");
  const [templateNotes, setTemplateNotes] = useState("");
  const [libraryQuery, setLibraryQuery] = useState("");
  const [libraryCategory, setLibraryCategory] = useState("");
  const [factorCategory, setFactorCategory] = useState("");
  const [activeFactorCategory, setActiveFactorCategory] = useState("hook");
  const [verificationFile, setVerificationFile] = useState<File | null>(null);
  const [selectedFactorId, setSelectedFactorId] = useState("");
  const [loading, setLoading] = useState(true);
  const [verifying, setVerifying] = useState(false);
  const [buildingTemplate, setBuildingTemplate] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedVideo = useMemo(
    () => videos.find((video) => video.id === selectedVideoId) ?? videos[0] ?? null,
    [selectedVideoId, videos],
  );

  const factorGroups = useMemo(() => {
    const groups = new Map<string, ViralFactor[]>();
    for (const factor of factors) {
      groups.set(factor.category, [...(groups.get(factor.category) ?? []), factor]);
    }
    return [...groups.entries()].sort(([a], [b]) => factorOrder.indexOf(a) - factorOrder.indexOf(b));
  }, [factors]);
  const activeFactorGroup = useMemo(
    () => factorGroups.find(([group]) => group === activeFactorCategory) ?? factorGroups[0] ?? null,
    [activeFactorCategory, factorGroups],
  );
  const activeFactors = useMemo(() => activeFactorGroup?.[1] ?? [], [activeFactorGroup]);
  const selectedFactor = useMemo(
    () => activeFactors.find((factor) => factor.id === selectedFactorId) ?? activeFactors[0] ?? null,
    [activeFactors, selectedFactorId],
  );
  const templateReferenceMatches = useMemo(
    () => resolveTemplateReferenceMatches(videos, templateReferenceUidInput),
    [videos, templateReferenceUidInput],
  );
  const templateReferenceTokens = useMemo(() => uidTokens(templateReferenceUidInput), [templateReferenceUidInput]);
  const unmatchedTemplateUids = useMemo(
    () =>
      templateReferenceTokens.filter((token) => !templateReferenceMatches.some((video) => referenceMatchesUid(video, token))),
    [templateReferenceMatches, templateReferenceTokens],
  );

  useEffect(() => {
    async function loadInitialLibrary() {
      setLoading(true);
      setError(null);
      try {
        const [nextVideos, nextFactors, nextTemplates] = await Promise.all([
          listViralVideos(),
          listViralFactors(),
          listCreativeTemplates(),
        ]);
        setVideos(nextVideos);
        setFactors(nextFactors);
        setTemplates(nextTemplates);
        if (nextVideos[0]) {
          setSelectedVideoId(nextVideos[0].id);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load viral library");
      } finally {
        setLoading(false);
      }
    }

    void loadInitialLibrary();
  }, []);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const [nextVideos, nextFactors, nextTemplates] = await Promise.all([
        listViralVideos({ query: libraryQuery, category: libraryCategory, factor_category: factorCategory }),
        listViralFactors({ query: libraryQuery, category: factorCategory }),
        listCreativeTemplates({ query: libraryQuery, category: libraryCategory }),
      ]);
      setVideos(nextVideos);
      setFactors(nextFactors);
      setTemplates(nextTemplates);
      if (!selectedVideoId && nextVideos[0]) {
        setSelectedVideoId(nextVideos[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load viral library");
    } finally {
      setLoading(false);
    }
  }

  async function createTemplate() {
    const referenceIds = templateReferenceMatches.map((video) => video.id);
    if (referenceIds.length < 2) {
      setError("Enter at least two valid reference UIDs to build a template.");
      return;
    }
    setBuildingTemplate(true);
    setError(null);
    try {
      const template = await buildCreativeTemplate({
        name: templateName,
        category: libraryCategory || selectedVideo?.category || "general",
        reference_ids: referenceIds,
        notes: templateNotes,
      });
      setTemplateName(template.name);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Template build failed");
    } finally {
      setBuildingTemplate(false);
    }
  }

  async function attachSourceVideo() {
    if (!selectedVideo || !verificationFile) {
      setError("Select a viral reference and choose an MP4 file first.");
      return;
    }
    setVerifying(true);
    setError(null);
    try {
      const updated = await attachViralSourceVideo(selectedVideo.id, verificationFile);
      await refresh();
      setSelectedVideoId(updated.id);
      setVerificationFile(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Source video verification failed");
    } finally {
      setVerifying(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Step 2 / Select Factors"
        title="Select viral factors and references"
        description="Browse curated viral references, inspect reusable factors, upload key viral MP4s, and cluster references into reusable templates."
        badges={["market signals", "8-factor board", "templates"]}
      />

      <section className="grid gap-4">
        <section className="grid gap-4 xl:grid-cols-2">
          <Card className="p-4">
            <CardHeader className="mb-3">
              <div>
                <CardTitle>Upload Viral MP4</CardTitle>
                <CardDescription className="line-clamp-1">{selectedVideo ? `Attach to ${selectedVideo.title}` : "Select a reference first."}</CardDescription>
              </div>
              <FileVideo className="h-5 w-5 text-blue-600" />
            </CardHeader>
            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
              <label className="flex h-10 cursor-pointer items-center gap-2 rounded-md border border-dashed border-black/15 bg-[#f5f5f7] px-3 text-sm font-medium text-slate-700 transition hover:border-blue-300">
                <FileVideo className="h-4 w-4 shrink-0" />
                <span className="min-w-0 truncate">{verificationFile ? verificationFile.name : "Choose MP4 for the selected viral reference"}</span>
                <input
                  className="sr-only"
                  type="file"
                  accept="video/mp4,video/*"
                  onChange={(event) => {
                    const file = event.target.files?.[0] ?? null;
                    if (file && !file.type.startsWith("video/")) {
                      setError("Only video files can be uploaded here.");
                      setVerificationFile(null);
                      return;
                    }
                    setError(null);
                    setVerificationFile(file);
                  }}
                />
              </label>
              <Button variant="secondary" onClick={attachSourceVideo} disabled={verifying || !selectedVideo || !verificationFile}>
                {verifying ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileVideo className="h-4 w-4" />}
                Upload
              </Button>
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-500">
              MP4s are used as visual evidence for high-value references; regular FastMoss records stay structured-only until a video is attached.
            </p>
          </Card>

          <Card className="p-4">
            <CardHeader className="mb-3">
              <div>
                <CardTitle>Template Clusters</CardTitle>
                <CardDescription>Enter reference UIDs directly to cluster a reusable pattern.</CardDescription>
              </div>
              <Sparkles className="h-5 w-5 text-amber-600" />
            </CardHeader>
            <div className="grid gap-3 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
              <div className="grid gap-2">
                <input className={inputClass} value={templateName} onChange={(event) => setTemplateName(event.target.value)} placeholder="Template name" />
                <textarea className="h-16 w-full resize-none rounded-md border border-black/10 bg-white px-3 py-2 text-sm leading-5 outline-none focus:border-blue-400 focus:ring-4 focus:ring-blue-100" value={templateNotes} onChange={(event) => setTemplateNotes(event.target.value)} placeholder="Cluster notes" />
                <Button variant="secondary" onClick={createTemplate} disabled={buildingTemplate || templateReferenceMatches.length < 2}>
                  {buildingTemplate ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  Create
                </Button>
              </div>
              <div className="grid gap-2">
                <textarea
                  className="h-24 w-full resize-none rounded-md border border-black/10 bg-white px-3 py-2 font-mono text-xs leading-5 outline-none focus:border-blue-400 focus:ring-4 focus:ring-blue-100"
                  value={templateReferenceUidInput}
                  onChange={(event) => setTemplateReferenceUidInput(event.target.value)}
                  placeholder="Paste 2-5 UIDs, e.g. 7198465808404581638, 7248672888021355822"
                />
                <div className="min-h-10 rounded-md bg-[#f5f5f7] p-2">
                  <div className="flex flex-wrap gap-1">
                    {templateReferenceMatches.slice(0, 5).map((video) => (
                      <Badge key={video.id} className="max-w-full border-emerald-200 bg-emerald-50 text-emerald-700">
                        <span className="truncate">UID {referenceUid(video) || video.id.slice(0, 8)}</span>
                      </Badge>
                    ))}
                    {!templateReferenceMatches.length ? <span className="px-1 text-xs leading-6 text-slate-500">No UID matched yet.</span> : null}
                  </div>
                  {unmatchedTemplateUids.length ? (
                    <p className="mt-2 line-clamp-2 text-xs leading-5 text-amber-700">Not found: {unmatchedTemplateUids.slice(0, 4).join(", ")}</p>
                  ) : null}
                </div>
              </div>
            </div>
            {templates.length ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {templates.slice(0, 4).map((template) => (
                  <Badge key={template.id}>{template.name}</Badge>
                ))}
                {templates.length > 4 ? <Badge>+{templates.length - 4}</Badge> : null}
              </div>
            ) : null}
          </Card>
        </section>

        <Card className="p-4">
          <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_140px_140px_auto_90px_90px_90px]">
            <input className={inputClass} value={libraryQuery} onChange={(event) => setLibraryQuery(event.target.value)} placeholder="Search references, factors, templates..." />
            <input className={inputClass} value={libraryCategory} onChange={(event) => setLibraryCategory(event.target.value)} placeholder="Category" />
            <select className={inputClass} value={factorCategory} onChange={(event) => setFactorCategory(event.target.value)}>
              <option value="">Any factor</option>
              {factorOrder.map((item) => (
                <option key={item} value={item}>
                  {titleCase(item)}
                </option>
              ))}
            </select>
            <Button variant="secondary" onClick={refresh} disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              Search
            </Button>
            <Metric label="Refs" value={videos.length} />
            <Metric label="Factors" value={factors.length} />
            <Metric label="Templates" value={templates.length} />
          </div>
          {error ? <p className="mt-3 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</p> : null}
        </Card>

        <section className="grid items-start gap-4 xl:grid-cols-[260px_minmax(0,1fr)_280px] 2xl:grid-cols-[300px_minmax(0,1fr)_320px]">
          <Card className="p-4">
            <CardHeader className="mb-3">
              <div>
                <CardTitle>References</CardTitle>
                <CardDescription>Pick one case; details stay in the center.</CardDescription>
              </div>
              <Library className="h-5 w-5 text-slate-800" />
            </CardHeader>
            <div className="grid gap-2">
              {videos.slice(0, 8).map((video) => {
                const source = video.analysis.source ?? {};
                const active = selectedVideo?.id === video.id;
                return (
                  <button
                    key={video.id}
                    className={`rounded-md border p-3 text-left transition ${
                      active ? "border-blue-200 bg-blue-50" : "border-black/10 bg-[#f5f5f7] hover:border-blue-200"
                    }`}
                    onClick={() => setSelectedVideoId(video.id)}
                    type="button"
                  >
                    <div className="grid grid-cols-[42px_minmax(0,1fr)] gap-3">
                      <MediaCover src={referenceCoverUrl(video)} title={video.title} className="h-14 rounded-md" />
                      <div className="min-w-0">
                        <p className="line-clamp-2 text-sm font-medium leading-5 text-slate-950">{video.title}</p>
                        <div className="mt-1 flex flex-wrap gap-1">
                          <SourceModeBadge video={video} />
                          {referenceUid(video) ? <Badge>UID {referenceUid(video)?.slice(-8)}</Badge> : null}
                        </div>
                      </div>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1">
                      <Badge>{video.category}</Badge>
                      <Badge>{String(source.platform ?? "external")}</Badge>
                      {source.country ? <Badge>{String(source.country)}</Badge> : null}
                    </div>
                  </button>
                );
              })}
              {videos.length > 8 ? <p className="rounded-md bg-[#f5f5f7] p-3 text-xs leading-5 text-slate-500">Showing 8 of {videos.length}. Use search to narrow the reference list.</p> : null}
              {!videos.length ? <Empty text="No external references yet." /> : null}
            </div>
          </Card>

          <main className="min-w-0">
            <ReferenceDetail video={selectedVideo} />
          </main>

          <aside className="grid gap-4">
            <Card className="p-4">
              <CardHeader className="mb-3">
                <div>
                  <CardTitle>8-Factor Board</CardTitle>
                  <CardDescription>One category at a time.</CardDescription>
                </div>
                <Sparkles className="h-5 w-5 text-blue-600" />
              </CardHeader>
              <div className="flex flex-wrap gap-1">
                {factorGroups.map(([group, items]) => (
                  <button
                    key={group}
                    className={`rounded-md border px-3 py-2 text-xs font-medium transition ${
                      (activeFactorGroup?.[0] ?? "") === group ? "border-blue-200 bg-blue-50 text-blue-700" : "border-black/10 bg-white text-slate-600"
                    }`}
                    onClick={() => {
                      setActiveFactorCategory(group);
                      setSelectedFactorId("");
                    }}
                    type="button"
                  >
                    {titleCase(group)} {items.length}
                  </button>
                ))}
              </div>
              <div className="mt-2 grid gap-2">
                {activeFactors.slice(0, 5).map((factor) => (
                  <button
                    key={factor.id}
                    className={`grid grid-cols-[54px_minmax(0,1fr)] gap-3 rounded-md border p-2 text-left transition ${
                      selectedFactor?.id === factor.id ? "border-blue-200 bg-blue-50" : "border-black/10 bg-[#f5f5f7] hover:border-blue-200"
                    }`}
                    onClick={() => setSelectedFactorId(factor.id)}
                    type="button"
                  >
                    <MediaCover src={factorCoverUrl(factor, videos)} title={factor.name} className="h-20 rounded-md" />
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-1">
                        <Badge className="border-slate-200 bg-slate-50 text-slate-600">{factor.category}</Badge>
                        {factorMetadataVideoChecked(factor.metadata_payload) ? (
                          <Badge className="border-emerald-200 bg-emerald-50 text-emerald-700">video</Badge>
                        ) : null}
                      </div>
                      <p className="mt-2 line-clamp-2 text-sm font-medium leading-5 text-slate-950">{factor.name}</p>
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{factor.description}</p>
                    </div>
                  </button>
                ))}
                {activeFactors.length > 5 ? <p className="rounded-md bg-[#f5f5f7] p-3 text-xs leading-5 text-slate-500">+{activeFactors.length - 5} more {activeFactorGroup?.[0] ?? "factor"} factors. Search or switch categories to narrow.</p> : null}
                {!factorGroups.length ? <Empty text="No factors yet." /> : null}
              </div>
              <SelectedFactorPanel factor={selectedFactor} videos={videos} />
            </Card>

          </aside>
        </section>
      </section>

      <section className="mt-6 rounded-lg border border-black/10 bg-white p-4 shadow-sm shadow-black/[0.03]">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-950">Next: run Studio agents</p>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              Generate an editable draft with the selected factor library and your private product evidence.
            </p>
          </div>
          <Link href="/studio">
            <Button variant="secondary">
              Run agents
              <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
        </div>
      </section>
    </>
  );
}

function ReferenceDetail({ video }: { video: ViralVideoAnalysis | null }) {
  if (!video) {
    return <Empty text="Select or analyze a reference to inspect the playbook." />;
  }
  const source = video.analysis.source ?? {};
  const metrics = source.metrics ?? {};
  const factors = video.analysis.factor_board ?? [];
  const storyboard = storyboardItems(video);
  const coverUrl = referenceCoverUrl(video);
  const uid = referenceUid(video);
  return (
    <Card className="overflow-hidden p-0">
      <div className="grid gap-0 lg:grid-cols-[180px_minmax(0,1fr)]">
        <div className="bg-[#f5f5f7] p-4">
          <MediaCover src={coverUrl} title={video.title} className="aspect-[9/16] w-full rounded-md" />
        </div>
        <div className="min-w-0 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <CardTitle className="line-clamp-2">{video.title}</CardTitle>
              <CardDescription className="line-clamp-1">{video.source_url}</CardDescription>
            </div>
            <div className="flex shrink-0 flex-wrap gap-1">
              <SourceModeBadge video={video} />
              <Badge>{String(source.platform ?? "external")}</Badge>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-1">
            {uid ? <Badge>UID {uid}</Badge> : null}
            <Badge>{String(source.product_type ?? video.category)}</Badge>
            {source.country ? <Badge>{String(source.country)}</Badge> : null}
            {isSliceVerified(video) && video.analysis.frame_count ? <Badge>{String(video.analysis.frame_count)} slices</Badge> : null}
          </div>
          <div className="mt-4 grid grid-cols-4 gap-2">
            {["views", "likes", "comments", "shares"].map((key) => (
              <MetricMini key={key} label={key} value={metrics[key]} />
            ))}
          </div>
        </div>
      </div>

      <div className="grid gap-3 border-t border-black/10 p-4 xl:grid-cols-[minmax(0,1fr)_260px]">
        <div className="grid gap-3">
          <div className="grid gap-3 md:grid-cols-2">
            <Panel title="Hook" text={String(video.analysis.hook_method ?? "No hook analysis yet.")} />
            <Panel title="Selling Order" text={stringList(video.analysis.selling_point_order).join(" -> ") || "No selling point order yet."} />
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <Panel title="Visual Direction" text={String(video.analysis.visual_style ?? video.analysis.style ?? "")} />
            <Panel title="CTA Pattern" text={String(video.analysis.cta_pattern ?? "")} />
          </div>
          <DetailsSection title={`Storyboard Structure (${storyboard.length || 0})`}>
            <div className="grid max-h-64 gap-2 overflow-auto pr-1">
              {storyboard.slice(0, 8).map((shot, index) => (
                <div key={`${video.id}-${index}`} className="rounded-md bg-white p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="line-clamp-1 text-sm font-medium text-slate-950">{String(shot.beat ?? `Shot ${index + 1}`)}</p>
                    <Badge>{String(shot.duration ?? 3)}s</Badge>
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{String(shot.purpose ?? "")}</p>
                </div>
              ))}
              {!storyboard.length ? <p className="rounded-md bg-white p-3 text-xs leading-5 text-slate-500">No storyboard beats yet.</p> : null}
            </div>
          </DetailsSection>
        </div>

        <div className="grid gap-3">
          <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-3">
            <p className="text-xs font-medium text-slate-500">Evidence Status</p>
            <p className="mt-2 text-xs leading-5 text-slate-700">{sourceEvidenceText(video)}</p>
            {isSliceVerified(video) ? <p className="mt-2 text-xs leading-5 text-slate-500">{videoMetadataText(video)}</p> : null}
          </div>
          <DetailsSection title="Content Analysis">
            <div className="grid gap-2">
              <Panel title="Caption Style" text={String(video.analysis.caption_style ?? "")} />
              <Panel title="Audio Direction" text={String(video.analysis.audio_style ?? "")} />
              <Panel title="Source Note" text={video.source_statement} />
            </div>
          </DetailsSection>
        </div>
      </div>

      <ExtractedFactorsPanel factors={factors} />
    </Card>
  );
}

function ExtractedFactorsPanel({ factors }: { factors: NonNullable<ViralVideoAnalysis["analysis"]["factor_board"]> }) {
  return (
    <div className="border-t border-black/10 bg-[#f5f5f7] p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-slate-500">Extracted Factors</p>
        <Badge>{factors.length}</Badge>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-2">
        {factors.slice(0, 4).map((factor) => (
          <div key={factor.factor_key} className="min-w-0 rounded-md bg-white p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge className="border-slate-200 bg-slate-50 text-slate-600">{factor.category}</Badge>
              {factor.visual_verified && factor.category !== "audio" ? (
                <Badge className="border-emerald-200 bg-emerald-50 text-emerald-700">video checked</Badge>
              ) : null}
              {factor.category === "audio" && !factor.audio_verified ? <Badge className="border-slate-200 bg-slate-50 text-slate-600">audio inferred</Badge> : null}
            </div>
            <p className="mt-2 break-words text-sm font-medium text-slate-950">{factor.name}</p>
            <p className="mt-1 line-clamp-2 break-words text-xs leading-5 text-slate-500">{factor.reason}</p>
            {factor.evidence_text ? <p className="mt-2 line-clamp-2 break-words text-xs leading-5 text-slate-500">{factor.evidence_text}</p> : null}
          </div>
        ))}
        {factors.length > 4 ? <p className="rounded-md bg-white p-3 text-xs leading-5 text-slate-500 md:col-span-2">+{factors.length - 4} more factors. Use the factor board on the right to browse by category.</p> : null}
        {!factors.length ? <p className="rounded-md bg-white p-3 text-xs leading-5 text-slate-500">No factors extracted yet.</p> : null}
      </div>
    </div>
  );
}

function SelectedFactorPanel({ factor, videos }: { factor: ViralFactor | null; videos: ViralVideoAnalysis[] }) {
  if (!factor) {
    return null;
  }
  const reference = factorReferenceVideo(factor, videos);
  const uid = factorUid(factor) || (reference ? referenceUid(reference) : "");
  const coverUrl = factorCoverUrl(factor, videos);
  const metadata = factor.metadata_payload ?? {};
  return (
    <div className="mt-3 rounded-lg border border-black/10 bg-white p-3">
      <MediaCover src={coverUrl} title={factor.name} className="aspect-[9/16] w-full rounded-md" />
      <div className="mt-3 flex flex-wrap gap-1">
        <Badge>{factor.category}</Badge>
        {uid ? <Badge>UID {uid}</Badge> : null}
        {factorMetadataVideoChecked(metadata) ? <Badge className="border-emerald-200 bg-emerald-50 text-emerald-700">video checked</Badge> : null}
      </div>
      <p className="mt-2 line-clamp-2 text-sm font-semibold leading-5 text-slate-950">{factor.name}</p>
      {reference ? <p className="mt-1 line-clamp-1 text-xs text-slate-500">{reference.title}</p> : null}
      <p className="mt-2 line-clamp-4 text-xs leading-5 text-slate-600">{String(metadata.evidence_text || factor.description || "")}</p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-2 font-mono text-2xl text-slate-950">{value}</p>
    </div>
  );
}

function MetricMini({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="min-w-0 rounded-md bg-[#f5f5f7] p-2">
      <p className="truncate text-[10px] uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-1 truncate font-mono text-xs text-slate-950">{compactNumber(value)}</p>
    </div>
  );
}

function Panel({ title, text }: { title: string; text: string }) {
  return (
    <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
      <p className="text-xs font-medium text-slate-500">{title}</p>
      <p className="mt-2 line-clamp-3 break-words text-xs leading-5 text-slate-700">{text || "Not analyzed yet."}</p>
    </div>
  );
}

function DetailsSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="group rounded-lg border border-black/10 bg-[#f5f5f7] p-3" open={false}>
      <summary className="cursor-pointer select-none text-xs font-medium text-slate-600 marker:text-slate-400">{title}</summary>
      <div className="mt-3">{children}</div>
    </details>
  );
}

function MediaCover({ src, title, className = "" }: { src?: string; title: string; className?: string }) {
  if (!src) {
    return (
      <div className={`flex items-center justify-center bg-slate-100 text-[10px] font-medium uppercase tracking-wide text-slate-400 ${className}`}>
        No cover
      </div>
    );
  }
  return (
    <div className={`overflow-hidden bg-slate-100 ${className}`}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img className="h-full w-full object-cover" src={src} alt={`${title} cover`} loading="lazy" />
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
      {text}
    </div>
  );
}

function titleCase(value: string) {
  return value.slice(0, 1).toUpperCase() + value.slice(1);
}

function stringList(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

function storyboardItems(video: ViralVideoAnalysis) {
  const storyboard = video.analysis.storyboard_structure ?? [];
  if (storyboard.length) {
    return storyboard;
  }
  return (video.analysis.verified_frame_evidence ?? []).map((frame, index) => ({
    beat: String(frame.summary ?? frame.product_subject ?? `Frame ${index + 1}`),
    duration: 3,
    purpose: frame.visible_details ? String(frame.visible_details) : String(frame.usage_scenes ?? "Keyframe evidence from uploaded MP4."),
  }));
}

function sourceEvidenceText(video: ViralVideoAnalysis) {
  const mode = String(video.analysis.source_mode ?? video.analysis.source?.source_mode ?? "fastmoss_structured_only");
  if (mode === "owner_viral_verified") {
    return "This reference has market signals plus owner-uploaded MP4 keyframe slices. Visual, scene, proof, trust, hook, CTA, and risk factors can cite frame evidence.";
  }
  if (mode === "owner_viral_uploaded_unverified") {
    return "An MP4 has been attached, but keyframe slicing did not complete, so factors should still be treated as unverified.";
  }
  return "This reference has structured market data only. The original footage has not been checked with keyframe slices.";
}

function videoMetadataText(video: ViralVideoAnalysis) {
  const metadata = video.analysis.video_metadata ?? {};
  const width = Number(metadata.width ?? 0);
  const height = Number(metadata.height ?? 0);
  const duration = Number(metadata.duration_seconds ?? 0);
  const frames = Number(video.analysis.frame_count ?? 0);
  const parts = [];
  if (width > 0 && height > 0) {
    parts.push(`${width}x${height}`);
  }
  if (duration > 0) {
    parts.push(`${duration.toFixed(1)}s`);
  }
  if (frames > 0) {
    parts.push(`${frames} frames`);
  }
  return parts.length ? parts.join(" / ") : "No MP4 metadata";
}

function SourceModeBadge({ video }: { video: ViralVideoAnalysis }) {
  const mode = String(video.analysis.source_mode ?? video.analysis.source?.source_mode ?? "fastmoss_structured_only");
  const verified = isSliceVerified(video);
  if (verified || mode === "owner_viral_verified") {
    return <Badge className="border-emerald-200 bg-emerald-50 text-emerald-700">Video checked</Badge>;
  }
  if (mode === "owner_viral_uploaded_unverified") {
    return <Badge className="border-amber-200 bg-amber-50 text-amber-700">Video pending</Badge>;
  }
  return <Badge className="border-slate-200 bg-slate-50 text-slate-600">Structured only</Badge>;
}

function isSliceVerified(video: ViralVideoAnalysis) {
  return Boolean(video.analysis.visual_verified ?? video.analysis.source?.visual_verified);
}

function factorMetadataVideoChecked(metadata: Record<string, unknown>) {
  return Boolean(metadata.visual_verified);
}

function compactNumber(value: unknown) {
  const number = Number(value ?? 0);
  if (!Number.isFinite(number) || number <= 0) {
    return "0";
  }
  if (number >= 1000000) {
    return `${(number / 1000000).toFixed(number >= 10000000 ? 0 : 1)}M`;
  }
  if (number >= 1000) {
    return `${(number / 1000).toFixed(number >= 10000 ? 0 : 1)}K`;
  }
  return String(number);
}

function uidTokens(value: string) {
  return Array.from(new Set(value.split(/[\s,;，、]+/).map((item) => item.trim()).filter(Boolean))).slice(0, 8);
}

function resolveTemplateReferenceMatches(videos: ViralVideoAnalysis[], value: string) {
  const matches: ViralVideoAnalysis[] = [];
  for (const token of uidTokens(value)) {
    const match = videos.find((video) => referenceMatchesUid(video, token));
    if (match && !matches.some((video) => video.id === match.id)) {
      matches.push(match);
    }
    if (matches.length >= 5) {
      break;
    }
  }
  return matches;
}

function referenceMatchesUid(video: ViralVideoAnalysis, uid: string) {
  const token = uid.trim();
  if (!token) {
    return false;
  }
  const candidates = [video.id, referenceUid(video), video.source_url].filter(Boolean).map(String);
  return candidates.some((candidate) => candidate === token || candidate.includes(token));
}

function referenceUid(video: ViralVideoAnalysis) {
  const analysis = safeRecord(video.analysis);
  const source = safeRecord(analysis.source);
  const fastmoss = safeRecord(source.fastmoss || analysis.fastmoss);
  return firstString(fastmoss.video_id, fastmoss.id, source.video_id, source.fastmoss_video_id, video.source_url.match(/video\/(\d+)/)?.[1]);
}

function referenceCoverUrl(video: ViralVideoAnalysis) {
  const analysis = safeRecord(video.analysis);
  const source = safeRecord(analysis.source);
  const fastmoss = safeRecord(source.fastmoss || analysis.fastmoss);
  const localCoverPath = firstString(analysis.cover_path, source.cover_path, analysis.local_cover_path, source.local_cover_path);
  const localCoverUrl = localCoverPath ? apiUrl(firstString(analysis.local_cover_url, source.local_cover_url)) : "";
  return firstUrl(
    localCoverUrl,
    firstString(analysis.cover_url, source.cover_url, analysis.thumbnail_url, source.thumbnail_url),
    firstString(fastmoss.cover, fastmoss.thumbnail_url, fastmoss.cover_url),
  );
}

function factorReferenceVideo(factor: ViralFactor, videos: ViralVideoAnalysis[]) {
  const metadata = safeRecord(factor.metadata_payload);
  const referenceId = firstString(metadata.source_reference_id, metadata.reference_id);
  if (referenceId) {
    const reference = videos.find((video) => video.id === referenceId);
    if (reference) {
      return reference;
    }
  }
  const uid = factorUid(factor);
  if (!uid) {
    return null;
  }
  return videos.find((video) => referenceMatchesUid(video, uid)) ?? null;
}

function factorCoverUrl(factor: ViralFactor, videos: ViralVideoAnalysis[]) {
  const reference = factorReferenceVideo(factor, videos);
  if (reference) {
    return referenceCoverUrl(reference);
  }
  const metadata = safeRecord(factor.metadata_payload);
  const fastmoss = safeRecord(metadata.fastmoss);
  return firstUrl(firstString(fastmoss.cover, fastmoss.thumbnail_url, fastmoss.cover_url));
}

function factorUid(factor: ViralFactor) {
  const metadata = safeRecord(factor.metadata_payload);
  const fastmoss = safeRecord(metadata.fastmoss);
  const sourceMatch = factor.source.match(/fastmoss:([^:]+)$/);
  return firstString(fastmoss.video_id, fastmoss.id, metadata.video_id, sourceMatch?.[1]);
}

function safeRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function firstString(...values: unknown[]) {
  for (const value of values) {
    const text = String(value ?? "").trim();
    if (text) {
      return text;
    }
  }
  return "";
}

function firstUrl(...values: unknown[]) {
  for (const value of values) {
    const text = String(value ?? "").trim();
    if (text) {
      return text;
    }
  }
  return "";
}

function apiUrl(value: string) {
  if (!value) {
    return "";
  }
  if (/^https?:\/\//i.test(value)) {
    return value;
  }
  return value.startsWith("/") ? `${API_BASE}${value}` : `${API_BASE}/${value}`;
}
