"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, FileUp, Film, ImageIcon, Loader2, Pin, RefreshCcw, Search, Tags } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  addAssetsToCollection,
  assetFileUrl,
  createAssetCollection,
  listAssetCollections,
  patchAssetSlice,
  searchAssets,
  type AssetCollection,
  type AssetLibraryItem,
  type AssetSearchResult,
  type AssetSlice,
} from "@/lib/api";

const inputClass =
  "h-10 w-full rounded-md border border-black/10 bg-white px-3 text-sm outline-none transition focus:border-blue-400 focus:ring-4 focus:ring-blue-100";
const textareaClass =
  "min-h-20 w-full resize-none rounded-md border border-black/10 bg-white px-3 py-2 text-sm leading-6 outline-none transition focus:border-blue-400 focus:ring-4 focus:ring-blue-100";

export default function AssetsPage() {
  const [collections, setCollections] = useState<AssetCollection[]>([]);
  const [selectedCollectionId, setSelectedCollectionId] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [productName, setProductName] = useState("Aurora Glow Bottle");
  const [category, setCategory] = useState("drinkware");
  const [description, setDescription] = useState("Insulated bottle with soft gradient finish, leak-proof lid, and desk-to-commute usage.");
  const [usageNotes, setUsageNotes] = useState("Need product appearance, close-up proof, scale relationship, and correct usage evidence.");
  const [uploadDescription, setUploadDescription] = useState("Product image/video evidence for appearance, proof, details, and usage scenes.");
  const [query, setQuery] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [assetKindFilter, setAssetKindFilter] = useState("");
  const [searchMode, setSearchMode] = useState<"keyword" | "tag" | "vector" | "hybrid">("hybrid");
  const [searchResults, setSearchResults] = useState<AssetSearchResult[]>([]);
  const [hasSearched, setHasSearched] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedCollection = useMemo(
    () => collections.find((collection) => collection.id === selectedCollectionId) ?? collections[0] ?? null,
    [collections, selectedCollectionId],
  );

  const collectionAssets = selectedCollection?.assets ?? [];
  const visibleAssets = hasSearched ? searchResults.map((result) => result.asset) : collectionAssets;

  const topTags = useMemo(() => {
    const values = new Map<string, number>();
    for (const collection of collections) {
      for (const tag of collection.tags) {
        values.set(tag, (values.get(tag) ?? 0) + 1);
      }
    }
    return [...values.entries()].sort((a, b) => b[1] - a[1]).slice(0, 14);
  }, [collections]);

  useEffect(() => {
    let active = true;
    async function loadInitialCollections() {
      setLoading(true);
      setError(null);
      try {
        const nextCollections = await listAssetCollections();
        if (!active) {
          return;
        }
        setCollections(nextCollections);
        setSelectedCollectionId(nextCollections[0]?.id || "");
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : "Failed to load asset collections");
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadInitialCollections();
    return () => {
      active = false;
    };
  }, []);

  async function refresh(nextSelectedId?: string) {
    setLoading(true);
    setError(null);
    try {
      const nextCollections = await listAssetCollections();
      setCollections(nextCollections);
      const nextId = nextSelectedId || selectedCollectionId || nextCollections[0]?.id || "";
      setSelectedCollectionId(nextId);
      setSearchResults([]);
      setHasSearched(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load asset collections");
    } finally {
      setLoading(false);
    }
  }

  async function createCollection() {
    setSaving(true);
    setError(null);
    try {
      const collection = await createAssetCollection({
        product_name: productName,
        category,
        description,
        usage_notes: usageNotes,
      });
      await refresh(collection.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Collection creation failed");
    } finally {
      setSaving(false);
    }
  }

  async function uploadAssets() {
    if (!selectedCollection) {
      setError("Create or select a collection first.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await addAssetsToCollection(
        selectedCollection.id,
        {
          category: selectedCollection.category,
          description: uploadDescription,
        },
        files,
      );
      setFiles([]);
      await refresh(selectedCollection.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Asset upload failed");
    } finally {
      setSaving(false);
    }
  }

  async function runSearch() {
    setSearching(true);
    setError(null);
    try {
      const results = await searchAssets({
        query,
        tag: tagFilter,
        category: selectedCollection?.category,
        asset_kind: assetKindFilter,
        collection_id: selectedCollection?.id,
        mode: searchMode,
        include_slices: true,
        limit: 20,
      });
      setSearchResults(results);
      setHasSearched(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setSearching(false);
    }
  }

  async function updateSlice(slice: AssetSlice, updates: Partial<Pick<AssetSlice, "summary" | "usable_for" | "is_pinned">>) {
    setError(null);
    try {
      await patchAssetSlice(slice.id, updates);
      await refresh(selectedCollection?.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Slice update failed");
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="My Assets"
        title="Private product material library"
        description="Build callable asset collections from product images and videos. Multimodal understanding turns files into tags, slices, and retrieval evidence for Studio agents."
        badges={["asset collections", "multimodal understanding", "slice retrieval"]}
      />

      <section className="grid gap-6 2xl:grid-cols-[340px_minmax(0,1fr)_360px]">
        <aside className="grid gap-6 2xl:sticky 2xl:top-24 2xl:self-start">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Create collection</CardTitle>
                <CardDescription>Group all private evidence for one product or creative project.</CardDescription>
              </div>
              <FileUp className="h-5 w-5 text-blue-600" />
            </CardHeader>
            <div className="space-y-3">
              <input className={inputClass} value={productName} onChange={(event) => setProductName(event.target.value)} placeholder="Product name" />
              <input className={inputClass} value={category} onChange={(event) => setCategory(event.target.value)} placeholder="Category" />
              <textarea className={textareaClass} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Product description" />
              <textarea className={textareaClass} value={usageNotes} onChange={(event) => setUsageNotes(event.target.value)} placeholder="Usage notes" />
              <Button className="w-full" variant="secondary" onClick={createCollection} disabled={saving}>
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileUp className="h-4 w-4" />}
                Create collection
              </Button>
            </div>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Upload assets</CardTitle>
                <CardDescription>Images are understood directly. Videos are converted into keyframe slices.</CardDescription>
              </div>
              <ImageIcon className="h-5 w-5 text-slate-700" />
            </CardHeader>
            <div className="space-y-3">
              <label className="flex cursor-pointer items-center justify-center gap-2 rounded-md border border-dashed border-black/15 bg-[#f5f5f7] px-3 py-4 text-sm font-medium text-slate-700 transition hover:border-blue-300">
                <FileUp className="h-4 w-4" />
                {files.length ? `${files.length} files selected` : "Choose images or videos"}
                <input
                  className="sr-only"
                  multiple
                  type="file"
                  accept="image/*,video/*"
                  onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
                />
              </label>
              <textarea className={textareaClass} value={uploadDescription} onChange={(event) => setUploadDescription(event.target.value)} />
              <Button className="w-full" variant="secondary" onClick={uploadAssets} disabled={saving || !selectedCollection || !files.length}>
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileUp className="h-4 w-4" />}
                Upload and analyze
              </Button>
              <div className="grid gap-2">
                {files.map((file) => (
                  <div key={`${file.name}-${file.size}`} className="flex items-center justify-between gap-3 rounded-md bg-[#f5f5f7] px-3 py-2">
                    <span className="min-w-0 truncate text-xs text-slate-700">{file.name}</span>
                    <Badge>{Math.max(1, Math.round(file.size / 1024))} KB</Badge>
                  </div>
                ))}
              </div>
              {error ? <p className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</p> : null}
            </div>
          </Card>
        </aside>

        <main className="grid gap-6">
          <section className="grid gap-3 md:grid-cols-3">
            <Metric label="Collections" value={String(collections.length)} />
            <Metric label="Assets" value={String(collections.reduce((sum, collection) => sum + collection.assets.length, 0))} />
            <Metric label="Tags" value={String(topTags.length)} />
          </section>

          <div className="grid gap-4">
            {collections.map((collection) => (
              <button
                key={collection.id}
                className={`rounded-lg border bg-white p-4 text-left shadow-sm shadow-black/[0.03] transition hover:border-blue-200 ${
                  selectedCollection?.id === collection.id ? "border-blue-300 ring-4 ring-blue-50" : "border-black/10"
                }`}
                onClick={() => {
                  setSelectedCollectionId(collection.id);
                  setSearchResults([]);
                  setHasSearched(false);
                }}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-slate-950">{collection.product_name}</p>
                    <p className="mt-1 text-xs leading-5 text-slate-500">{collection.summary}</p>
                  </div>
                  <StatusBadge status={collection.status} />
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Badge>{collection.category}</Badge>
                  <Badge>{collection.assets.length} assets</Badge>
                  {Object.entries(collection.coverage)
                    .filter(([, value]) => value === true)
                    .slice(0, 4)
                    .map(([key]) => (
                      <Badge key={key}>{key}</Badge>
                    ))}
                </div>
              </button>
            ))}
            {!collections.length && !loading ? (
              <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-10 text-center text-sm text-slate-500">
                Create your first private asset collection, then upload product images or videos.
              </div>
            ) : null}
          </div>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Collection assets</CardTitle>
                <CardDescription>
                  {selectedCollection ? `${selectedCollection.product_name} / ${selectedCollection.category}` : "Select a collection to inspect its assets."}
                </CardDescription>
              </div>
              <RefreshCcw className="h-5 w-5 text-slate-700" />
            </CardHeader>
            <div className="grid gap-4">
              {visibleAssets.map((asset) => (
                <AssetCard key={asset.id} asset={asset} onUpdateSlice={updateSlice} />
              ))}
              {!visibleAssets.length ? <p className="rounded-md bg-[#f5f5f7] p-6 text-center text-sm text-slate-500">No assets to show yet.</p> : null}
            </div>
          </Card>
        </main>

        <aside className="grid gap-6 2xl:sticky 2xl:top-24 2xl:self-start">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Search assets</CardTitle>
                <CardDescription>Search collection, asset, and slice evidence for downstream scripts.</CardDescription>
              </div>
              <Search className="h-5 w-5 text-slate-700" />
            </CardHeader>
            <div className="space-y-3">
              <input className={inputClass} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="close-up proof, desk scale..." />
              <div className="grid gap-2 sm:grid-cols-2 2xl:grid-cols-1">
                <input className={inputClass} value={tagFilter} onChange={(event) => setTagFilter(event.target.value)} placeholder="Tag filter" />
                <select className={inputClass} value={assetKindFilter} onChange={(event) => setAssetKindFilter(event.target.value)}>
                  <option value="">Any asset type</option>
                  <option value="image">Image</option>
                  <option value="video">Video</option>
                  <option value="reference">Reference</option>
                </select>
                <select className={inputClass} value={searchMode} onChange={(event) => setSearchMode(event.target.value as typeof searchMode)}>
                  <option value="hybrid">Hybrid</option>
                  <option value="keyword">Keyword</option>
                  <option value="tag">Tag</option>
                  <option value="vector">Vector-like</option>
                </select>
              </div>
              <div className="flex gap-2">
                <Button className="flex-1" variant="secondary" onClick={runSearch} disabled={searching || !selectedCollection}>
                  {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                  Search
                </Button>
                <Button size="icon" variant="outline" onClick={() => refresh(selectedCollection?.id)} aria-label="Refresh assets">
                  <RefreshCcw className="h-4 w-4" />
                </Button>
              </div>
              {hasSearched ? <p className="text-xs text-slate-500">{searchResults.length} collection-aware results</p> : null}
            </div>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Tags</CardTitle>
                <CardDescription>Provider and system tags from private material.</CardDescription>
              </div>
              <Tags className="h-5 w-5 text-slate-700" />
            </CardHeader>
            <div className="flex flex-wrap gap-2">
              {topTags.map(([tag, count]) => (
                <Badge key={tag}>
                  {tag} {count}
                </Badge>
              ))}
              {!topTags.length ? <p className="text-sm text-slate-500">No tags yet.</p> : null}
            </div>
          </Card>
        </aside>
      </section>
    </>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-black/10 bg-white p-4 shadow-sm shadow-black/[0.03]">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-slate-950">{value}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const color =
    status === "analyzed"
      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
      : status === "failed"
        ? "border-rose-200 bg-rose-50 text-rose-700"
        : "border-slate-200 bg-slate-50 text-slate-600";
  return <Badge className={color}>{status}</Badge>;
}

function ProviderBadge({ asset }: { asset: AssetLibraryItem }) {
  if (asset.provider_status === "configured") {
    return <Badge className="border-emerald-200 bg-emerald-50 text-emerald-700">Real understanding</Badge>;
  }
  if (asset.provider_status === "error") {
    return <Badge className="border-rose-200 bg-rose-50 text-rose-700">Provider failed</Badge>;
  }
  return <Badge className="border-slate-200 bg-slate-50 text-slate-600">Not connected</Badge>;
}

function AssetCard({ asset, onUpdateSlice }: { asset: AssetLibraryItem; onUpdateSlice: (slice: AssetSlice, updates: Partial<AssetSlice>) => void }) {
  const isImage = asset.content_type.startsWith("image/");
  const isVideo = asset.content_type.startsWith("video/");
  return (
    <div className="rounded-lg border border-black/10 bg-white p-4 shadow-sm shadow-black/[0.03]">
      <div className="grid gap-4 xl:grid-cols-[220px_minmax(0,1fr)]">
        <div className="overflow-hidden rounded-lg border border-black/10 bg-[#f5f5f7]">
          {isImage ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img className="aspect-video w-full object-cover" src={assetFileUrl(asset.id)} alt={asset.filename} />
          ) : isVideo ? (
            <div className="flex aspect-video flex-col items-center justify-center gap-2 text-slate-500">
              <Film className="h-8 w-8" />
              <p className="text-xs">Video file saved</p>
            </div>
          ) : (
            <div className="flex aspect-video flex-col items-center justify-center gap-2 text-slate-500">
              <FileUp className="h-8 w-8" />
              <p className="text-xs">Reference material</p>
            </div>
          )}
        </div>

        <div className="min-w-0">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-slate-950">{asset.filename}</p>
              <p className="mt-1 text-xs leading-5 text-slate-500">{asset.analysis.summary ?? asset.description}</p>
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              <ProviderBadge asset={asset} />
              <StatusBadge status={asset.analysis_status} />
            </div>
          </div>

          {asset.provider_message ? <p className="mt-2 break-words text-xs leading-5 text-slate-500">{asset.provider_message}</p> : null}

          <div className="mt-3 flex flex-wrap gap-2">
            {asset.tags.slice(0, 10).map((tag) => (
              <Badge key={tag.id}>{tag.name}</Badge>
            ))}
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {asset.slices.map((slice) => (
              <div key={slice.id} className="rounded-md border border-black/10 bg-[#f5f5f7] p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    {slice.is_pinned ? <Pin className="h-4 w-4 text-blue-600" /> : <CheckCircle2 className="h-4 w-4 text-slate-400" />}
                    <p className="text-xs font-medium text-slate-950">Slice {slice.order_index}</p>
                  </div>
                  <Badge>{slice.usable_for || slice.slice_type}</Badge>
                </div>
                <textarea
                  className="mt-2 min-h-20 w-full resize-none rounded-md border border-black/10 bg-white p-2 text-xs leading-5 text-slate-700 outline-none focus:border-blue-300"
                  defaultValue={slice.summary}
                  onBlur={(event) => {
                    if (event.currentTarget.value !== slice.summary) {
                      onUpdateSlice(slice, { summary: event.currentTarget.value });
                    }
                  }}
                />
                <div className="mt-2 flex flex-wrap gap-2">
                  <select
                    className="h-8 flex-1 rounded-md border border-black/10 bg-white px-2 text-xs outline-none"
                    defaultValue={slice.usable_for}
                    onChange={(event) => onUpdateSlice(slice, { usable_for: event.target.value })}
                  >
                    {["hook", "proof", "detail", "usage", "cta"].map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                  <Button size="sm" variant={slice.is_pinned ? "secondary" : "outline"} onClick={() => onUpdateSlice(slice, { is_pinned: !slice.is_pinned })}>
                    <Pin className="h-4 w-4" />
                    {slice.is_pinned ? "Pinned" : "Pin"}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
