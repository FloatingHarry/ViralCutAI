"use client";

import { useEffect, useMemo, useState } from "react";
import { FileSpreadsheet, Library, Loader2, RefreshCcw, Search, Sparkles, Wand2 } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  analyzeViralVideo,
  buildCreativeTemplate,
  listCreativeTemplates,
  listViralFactors,
  listViralVideos,
  type CreativeTemplate,
  type ViralFactor,
  type ViralVideoAnalysis,
} from "@/lib/api";

const inputClass =
  "h-10 w-full rounded-md border border-black/10 bg-white px-3 text-sm outline-none transition focus:border-blue-400 focus:ring-4 focus:ring-blue-100";
const textareaClass =
  "min-h-24 w-full resize-none rounded-md border border-black/10 bg-white px-3 py-2 text-sm leading-6 outline-none transition focus:border-blue-400 focus:ring-4 focus:ring-blue-100";

const factorOrder = ["hook", "proof", "scene", "trust", "visual", "audio", "cta", "risk"];

export default function ViralLibraryPage() {
  const [videos, setVideos] = useState<ViralVideoAnalysis[]>([]);
  const [factors, setFactors] = useState<ViralFactor[]>([]);
  const [templates, setTemplates] = useState<CreativeTemplate[]>([]);
  const [selectedVideoId, setSelectedVideoId] = useState("");
  const [selectedTemplateReferenceIds, setSelectedTemplateReferenceIds] = useState<string[]>([]);
  const [title, setTitle] = useState("Desk bottle proof demo");
  const [sourceUrl, setSourceUrl] = useState("https://example.com/public-reference");
  const [platform, setPlatform] = useState("TikTok");
  const [category, setCategory] = useState("drinkware");
  const [productType, setProductType] = useState("insulated bottle");
  const [country, setCountry] = useState("US");
  const [language, setLanguage] = useState("English");
  const [views, setViews] = useState("120000");
  const [likes, setLikes] = useState("8400");
  const [comments, setComments] = useState("260");
  const [shares, setShares] = useState("510");
  const [publishedAt, setPublishedAt] = useState("");
  const [thumbnailUrl, setThumbnailUrl] = useState("");
  const [notes, setNotes] = useState("Fast hook, close tactile proof, desk scene, simple offer close");
  const [sourceStatement, setSourceStatement] = useState("Public reference used for structured analysis only; footage is not copied.");
  const [templateName, setTemplateName] = useState("");
  const [templateNotes, setTemplateNotes] = useState("");
  const [libraryQuery, setLibraryQuery] = useState("");
  const [libraryCategory, setLibraryCategory] = useState("");
  const [factorCategory, setFactorCategory] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
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

  async function analyze() {
    setSaving(true);
    setError(null);
    try {
      const record = await analyzeViralVideo({
        title,
        source_url: sourceUrl,
        platform,
        category,
        product_type: productType,
        country,
        language,
        metrics: {
          views: toNumber(views),
          likes: toNumber(likes),
          comments: toNumber(comments),
          shares: toNumber(shares),
        },
        published_at: publishedAt,
        thumbnail_url: thumbnailUrl,
        notes,
        source_statement: sourceStatement,
      });
      await refresh();
      setSelectedVideoId(record.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reference analysis failed");
    } finally {
      setSaving(false);
    }
  }

  async function createTemplate() {
    setBuildingTemplate(true);
    setError(null);
    try {
      const template = await buildCreativeTemplate({
        name: templateName,
        category: libraryCategory || category,
        reference_ids: selectedTemplateReferenceIds,
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

  function toggleTemplateReference(id: string, checked: boolean) {
    setSelectedTemplateReferenceIds((current) => (checked ? Array.from(new Set([...current, id])).slice(0, 5) : current.filter((item) => item !== id)));
  }

  return (
    <>
      <PageHeader
        eyebrow="Viral Library"
        title="External playbook for script generation"
        description="Import public references, extract structured playbook analysis, build reusable factors, and cluster references into templates for Studio generation modes."
        badges={["reference intake", "8-factor board", "template builder"]}
      />

      <section className="grid gap-6 2xl:grid-cols-[360px_minmax(0,1fr)_360px]">
        <aside className="grid gap-6 2xl:sticky 2xl:top-24 2xl:self-start">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Reference Intake</CardTitle>
                <CardDescription>Store source metadata and structured analysis only.</CardDescription>
              </div>
              <Wand2 className="h-5 w-5 text-blue-600" />
            </CardHeader>
            <div className="space-y-3">
              <input className={inputClass} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Reference title" />
              <input className={inputClass} value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="Public source URL" />
              <div className="grid gap-2 sm:grid-cols-2 2xl:grid-cols-1">
                <input className={inputClass} value={platform} onChange={(event) => setPlatform(event.target.value)} placeholder="Platform" />
                <input className={inputClass} value={category} onChange={(event) => setCategory(event.target.value)} placeholder="Category" />
                <input className={inputClass} value={productType} onChange={(event) => setProductType(event.target.value)} placeholder="Product type" />
                <input className={inputClass} value={country} onChange={(event) => setCountry(event.target.value)} placeholder="Country" />
                <input className={inputClass} value={language} onChange={(event) => setLanguage(event.target.value)} placeholder="Language" />
                <input className={inputClass} value={publishedAt} onChange={(event) => setPublishedAt(event.target.value)} placeholder="Published date" />
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <input className={inputClass} value={views} onChange={(event) => setViews(event.target.value)} placeholder="Views" />
                <input className={inputClass} value={likes} onChange={(event) => setLikes(event.target.value)} placeholder="Likes" />
                <input className={inputClass} value={comments} onChange={(event) => setComments(event.target.value)} placeholder="Comments" />
                <input className={inputClass} value={shares} onChange={(event) => setShares(event.target.value)} placeholder="Shares" />
              </div>
              <input className={inputClass} value={thumbnailUrl} onChange={(event) => setThumbnailUrl(event.target.value)} placeholder="Thumbnail URL" />
              <textarea className={textareaClass} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Observed viral pattern" />
              <textarea className={textareaClass} value={sourceStatement} onChange={(event) => setSourceStatement(event.target.value)} placeholder="Source and compliance statement" />
              <Button className="w-full" variant="secondary" onClick={analyze} disabled={saving}>
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                Analyze into playbook
              </Button>
              {error ? <p className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</p> : null}
            </div>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>CSV Import</CardTitle>
                <CardDescription>Reserved for batch URL import after source sites are chosen.</CardDescription>
              </div>
              <FileSpreadsheet className="h-5 w-5 text-slate-700" />
            </CardHeader>
            <div className="rounded-md border border-dashed border-black/15 bg-[#f5f5f7] p-4 text-sm leading-6 text-slate-500">
              CSV should contain URL, platform, category, product type, region, language, metrics, and source statement. Batch parsing is provider pending.
            </div>
          </Card>
        </aside>

        <main className="grid gap-6">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Retrieval</CardTitle>
                <CardDescription>Search references, factors, and templates before Studio uses them.</CardDescription>
              </div>
              <Search className="h-5 w-5 text-slate-800" />
            </CardHeader>
            <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_160px_160px_auto]">
              <input className={inputClass} value={libraryQuery} onChange={(event) => setLibraryQuery(event.target.value)} placeholder="hook, proof, trust..." />
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
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
                Search
              </Button>
            </div>
          </Card>

          <section className="grid gap-4 lg:grid-cols-3">
            <Metric label="References" value={videos.length} />
            <Metric label="External Factors" value={factors.length} />
            <Metric label="Templates" value={templates.length} />
          </section>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Reference Library</CardTitle>
                <CardDescription>Click a public reference to inspect its script playbook analysis.</CardDescription>
              </div>
              <Library className="h-5 w-5 text-slate-800" />
            </CardHeader>
            <div className="grid gap-3 xl:grid-cols-2">
              {videos.map((video) => {
                const source = video.analysis.source ?? {};
                const active = selectedVideo?.id === video.id;
                return (
                  <button
                    key={video.id}
                    className={`rounded-lg border p-4 text-left transition ${
                      active ? "border-blue-200 bg-blue-50" : "border-black/10 bg-[#f5f5f7] hover:border-blue-200"
                    }`}
                    onClick={() => setSelectedVideoId(video.id)}
                    type="button"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="font-medium text-slate-950">{video.title}</p>
                      <Badge>{video.category}</Badge>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Badge>{String(source.platform ?? "external")}</Badge>
                      {source.product_type ? <Badge>{String(source.product_type)}</Badge> : null}
                      {source.country ? <Badge>{String(source.country)}</Badge> : null}
                    </div>
                    <p className="mt-3 text-xs leading-5 text-slate-500">{video.source_statement}</p>
                  </button>
                );
              })}
              {!videos.length ? <Empty text="No external references yet." /> : null}
            </div>
          </Card>

          <ReferenceDetail video={selectedVideo} />

          <Card>
            <CardHeader>
              <div>
                <CardTitle>8-Factor Board</CardTitle>
                <CardDescription>Reusable viral factors extracted from external references only.</CardDescription>
              </div>
              <Sparkles className="h-5 w-5 text-blue-600" />
            </CardHeader>
            <div className="grid gap-4">
              {factorGroups.map(([group, items]) => (
                <div key={group} className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
                  <div className="flex items-center justify-between">
                    <p className="font-medium text-slate-950">{titleCase(group)}</p>
                    <Badge>{items.length}</Badge>
                  </div>
                  <div className="mt-3 grid gap-2 md:grid-cols-2">
                    {items.slice(0, 8).map((factor) => (
                      <div key={factor.id} className="rounded-md border border-black/10 bg-white p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge>{factor.category}</Badge>
                          {factor.metadata_payload.platform ? <Badge>{String(factor.metadata_payload.platform)}</Badge> : null}
                        </div>
                        <p className="mt-2 text-sm font-medium text-slate-950">{factor.name}</p>
                        <p className="mt-1 text-xs leading-5 text-slate-500">{factor.description}</p>
                        {factor.metadata_payload.expected_effect ? (
                          <p className="mt-2 text-xs leading-5 text-blue-700">{factor.metadata_payload.expected_effect}</p>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
              {!factorGroups.length ? <Empty text="Analyze an external reference to create factors." /> : null}
            </div>
          </Card>
        </main>

        <aside className="grid gap-6 2xl:sticky 2xl:top-24 2xl:self-start">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Template Builder</CardTitle>
                <CardDescription>Cluster 2-5 references into one n:1 creative playbook.</CardDescription>
              </div>
              <Sparkles className="h-5 w-5 text-amber-600" />
            </CardHeader>
            <div className="space-y-3">
              <input className={inputClass} value={templateName} onChange={(event) => setTemplateName(event.target.value)} placeholder="Template name" />
              <textarea className={textareaClass} value={templateNotes} onChange={(event) => setTemplateNotes(event.target.value)} placeholder="Clustering notes" />
              <div className="grid max-h-64 gap-2 overflow-auto rounded-md bg-[#f5f5f7] p-2">
                {videos.map((video) => (
                  <label key={video.id} className="flex items-start gap-2 rounded-md bg-white p-2 text-xs text-slate-700">
                    <input
                      className="mt-1"
                      type="checkbox"
                      checked={selectedTemplateReferenceIds.includes(video.id)}
                      onChange={(event) => toggleTemplateReference(video.id, event.target.checked)}
                    />
                    <span className="min-w-0">
                      <span className="block font-medium text-slate-950">{video.title}</span>
                      <span className="mt-1 block leading-5 text-slate-500">{video.category}</span>
                    </span>
                  </label>
                ))}
                {!videos.length ? <p className="p-3 text-xs text-slate-500">Add references before building templates.</p> : null}
              </div>
              <Button className="w-full" variant="secondary" onClick={createTemplate} disabled={buildingTemplate || selectedTemplateReferenceIds.length < 2}>
                {buildingTemplate ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                Create template
              </Button>
            </div>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Template Library</CardTitle>
                <CardDescription>Templates can be selected in Studio Template Fusion mode.</CardDescription>
              </div>
              <Library className="h-5 w-5 text-amber-600" />
            </CardHeader>
            <div className="space-y-3">
              {templates.map((template) => (
                <div key={template.id} className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium text-slate-950">{template.name}</p>
                    <Badge>{template.category}</Badge>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-slate-500">{template.strategy}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {(template.structure.source_reference_ids as string[] | undefined)?.slice(0, 5).map((id) => <Badge key={id}>{id.slice(0, 8)}</Badge>)}
                  </div>
                </div>
              ))}
              {!templates.length ? <Empty text="No templates yet." /> : null}
            </div>
          </Card>
        </aside>
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
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{video.title}</CardTitle>
          <CardDescription>{video.source_url}</CardDescription>
        </div>
        <Badge>{String(source.platform ?? "external")}</Badge>
      </CardHeader>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px]">
        <div className="space-y-4">
          <Panel title="Hook Method" text={String(video.analysis.hook_method ?? "No hook analysis yet.")} />
          <Panel title="Selling Point Order" text={stringList(video.analysis.selling_point_order).join(" -> ") || "No selling point order yet."} />
          <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
            <p className="text-xs font-medium text-slate-500">Storyboard Structure</p>
            <div className="mt-3 grid gap-2">
              {(video.analysis.storyboard_structure ?? []).map((shot, index) => (
                <div key={`${video.id}-${index}`} className="rounded-md bg-white p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium text-slate-950">{String(shot.beat ?? `Shot ${index + 1}`)}</p>
                    <Badge>{String(shot.duration ?? 3)}s</Badge>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-slate-500">{String(shot.purpose ?? "")}</p>
                </div>
              ))}
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <Panel title="Visual Style" text={String(video.analysis.visual_style ?? video.analysis.style ?? "")} />
            <Panel title="Caption Style" text={String(video.analysis.caption_style ?? "")} />
            <Panel title="Audio Style" text={String(video.analysis.audio_style ?? "")} />
            <Panel title="CTA Pattern" text={String(video.analysis.cta_pattern ?? "")} />
          </div>
        </div>
        <div className="space-y-4">
          <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
            <p className="text-xs font-medium text-slate-500">Source Metadata</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge>{String(source.product_type ?? video.category)}</Badge>
              {source.country ? <Badge>{String(source.country)}</Badge> : null}
              {source.language ? <Badge>{String(source.language)}</Badge> : null}
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2">
              {["views", "likes", "comments", "shares"].map((key) => (
                <div key={key} className="rounded-md bg-white p-3">
                  <p className="text-[11px] uppercase tracking-wide text-slate-400">{key}</p>
                  <p className="mt-1 font-mono text-sm text-slate-950">{String(metrics[key] ?? 0)}</p>
                </div>
              ))}
            </div>
            <p className="mt-4 text-xs leading-5 text-slate-500">{video.source_statement}</p>
          </div>
          <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
            <p className="text-xs font-medium text-slate-500">Extracted Factors</p>
            <div className="mt-3 space-y-2">
              {factors.map((factor) => (
                <div key={factor.factor_key} className="rounded-md bg-white p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium text-slate-950">{factor.name}</p>
                    <Badge>{factor.category}</Badge>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-slate-500">{factor.reason}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </Card>
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

function Panel({ title, text }: { title: string; text: string }) {
  return (
    <div className="rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
      <p className="text-xs font-medium text-slate-500">{title}</p>
      <p className="mt-2 break-words text-sm leading-6 text-slate-700">{text || "Not analyzed yet."}</p>
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

function toNumber(value: string) {
  const parsed = Number(value.replace(/,/g, ""));
  return Number.isFinite(parsed) ? parsed : 0;
}
