"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { ArrowRight, FileUp, Film, ImageIcon, Loader2, PlusCircle, RefreshCcw, Search } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  addAssetsToCollection,
  assetFileUrl,
  createAssetCollection,
  listAssetCollections,
  type AssetCollection,
  type AssetLibraryItem,
} from "@/lib/api";

const inputClass =
  "h-10 w-full rounded-md border border-black/10 bg-white px-3 text-sm outline-none transition focus:border-blue-400 focus:ring-4 focus:ring-blue-100";
const textareaClass =
  "min-h-24 w-full resize-none rounded-md border border-black/10 bg-white px-3 py-2 text-sm leading-6 outline-none transition focus:border-blue-400 focus:ring-4 focus:ring-blue-100";

export default function AssetsPage() {
  const [collections, setCollections] = useState<AssetCollection[]>([]);
  const [selectedCollectionId, setSelectedCollectionId] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [productName, setProductName] = useState("");
  const [category, setCategory] = useState("");
  const [targetAudience, setTargetAudience] = useState("");
  const [sellingPoints, setSellingPoints] = useState("");
  const [description, setDescription] = useState("");
  const [usageNotes, setUsageNotes] = useState("");
  const [mediaNotes, setMediaNotes] = useState("");
  const [libraryQuery, setLibraryQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selectedCollection = useMemo(
    () => collections.find((collection) => collection.id === selectedCollectionId) ?? collections[0] ?? null,
    [collections, selectedCollectionId],
  );
  const visibleCollections = useMemo(() => {
    const query = libraryQuery.trim().toLowerCase();
    if (!query) {
      return collections;
    }
    return collections.filter((collection) => {
      const assetText = collection.assets
        .flatMap((asset) => [
          asset.filename,
          asset.description,
          asset.analysis.summary,
          ...asset.tags.map((tag) => tag.name),
          ...asset.slices.map((slice) => `${slice.usable_for} ${slice.summary}`),
        ])
        .join(" ");
      return [
        collection.product_name,
        collection.category,
        collection.description,
        collection.usage_notes,
        collection.summary,
        collection.tags.join(" "),
        assetText,
      ]
        .join(" ")
        .toLowerCase()
        .includes(query);
    });
  }, [collections, libraryQuery]);

  const refresh = useCallback(async (nextSelectedId?: string) => {
    await Promise.resolve();
    setLoading(true);
    setError(null);
    try {
      const nextCollections = await listAssetCollections();
      setCollections(nextCollections);
      setSelectedCollectionId((current) => nextSelectedId || current || nextCollections[0]?.id || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load assets");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => {
      void listAssetCollections()
        .then((nextCollections) => {
          if (!active) {
            return;
          }
          setCollections(nextCollections);
          setSelectedCollectionId(nextCollections[0]?.id || "");
        })
        .catch((err: unknown) => {
          if (active) {
            setError(err instanceof Error ? err.message : "Failed to load assets");
          }
        })
        .finally(() => {
          if (active) {
            setLoading(false);
          }
        });
    }, 0);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, []);

  async function uploadFiles(collectionId: string, collectionCategory: string) {
    for (const file of files) {
      const assetKind = file.type.startsWith("video/") ? "user_video_decomposition" : "image";
      await addAssetsToCollection(collectionId, { category: collectionCategory, description: mediaNotes, asset_kind: assetKind }, [file]);
    }
  }

  async function createAssetSet() {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const collection = await createAssetCollection({
        product_name: productName,
        category: category.trim() || "general",
        description: [
          description.trim(),
          targetAudience.trim() ? `Target audience: ${targetAudience.trim()}` : "",
          sellingPoints.trim() ? `Key selling points: ${sellingPoints.trim()}` : "",
        ]
          .filter(Boolean)
          .join("\n"),
        usage_notes: usageNotes.trim(),
      });
      if (files.length) {
        await uploadFiles(collection.id, collection.category);
      }
      setFiles([]);
      setNotice(`${collection.product_name} created${files.length ? ` with ${files.length} media file${files.length === 1 ? "" : "s"}` : ""}.`);
      await refresh(collection.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Asset creation failed");
    } finally {
      setSaving(false);
    }
  }

  async function addMediaToSelected() {
    if (!selectedCollection || !files.length) {
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await uploadFiles(selectedCollection.id, selectedCollection.category);
      setFiles([]);
      setNotice(`Added media to ${selectedCollection.product_name}.`);
      await refresh(selectedCollection.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Media upload failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Step 1 / Assets"
        title="Product asset library"
        description="Each asset set contains product images, optional videos, and notes. Studio uses this material as product evidence for generation."
        badges={["images", "videos", "notes"]}
      />

      <section className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <Card className="p-4 xl:self-start">
          <CardHeader className="mb-4">
            <div>
              <CardTitle>Create asset set</CardTitle>
              <CardDescription>Upload product media and explain what it is.</CardDescription>
            </div>
            <FileUp className="h-5 w-5 text-blue-600" />
          </CardHeader>

          <div className="space-y-3">
            <Field label="Product title">
              <input className={inputClass} value={productName} onChange={(event) => setProductName(event.target.value)} placeholder="Aurora Glow Bottle" />
            </Field>
            <Field label="Category">
              <input className={inputClass} value={category} onChange={(event) => setCategory(event.target.value)} placeholder="beauty & personal care" />
            </Field>
            <Field label="Target audience">
              <input className={inputClass} value={targetAudience} onChange={(event) => setTargetAudience(event.target.value)} placeholder="Who will buy this?" />
            </Field>
            <Field label="Key selling points">
              <textarea className={textareaClass} value={sellingPoints} onChange={(event) => setSellingPoints(event.target.value)} placeholder="Color-shift finish, premium 100ml packaging, giftable look" />
            </Field>
            <Field label="Product description">
              <textarea className={textareaClass} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Appearance, material, package, scale relationship..." />
            </Field>
            <Field label="Generation notes">
              <textarea className={textareaClass} value={usageNotes} onChange={(event) => setUsageNotes(event.target.value)} placeholder="How should scripts and video prompts use this material?" />
            </Field>

            <label className="flex cursor-pointer items-center justify-center gap-2 rounded-md border border-dashed border-black/15 bg-[#f5f5f7] px-3 py-5 text-sm font-medium text-slate-700 transition hover:border-blue-300">
              <PlusCircle className="h-4 w-4" />
              {files.length ? `${files.length} media file${files.length === 1 ? "" : "s"} selected` : "Choose images or videos"}
              <input
                className="sr-only"
                multiple
                type="file"
                accept="image/*,video/*"
                onChange={(event) => setFiles(Array.from(event.target.files ?? []).filter((file) => file.type.startsWith("image/") || file.type.startsWith("video/")))}
              />
            </label>

            <Field label="Media notes">
              <textarea className={textareaClass} value={mediaNotes} onChange={(event) => setMediaNotes(event.target.value)} placeholder="What do the uploaded images/videos show?" />
            </Field>

            {files.length ? (
              <div className="grid gap-2">
                {files.map((file) => (
                  <div key={`${file.name}-${file.size}`} className="flex items-center justify-between gap-3 rounded-md bg-[#f5f5f7] px-3 py-2">
                    <span className="min-w-0 truncate text-xs text-slate-700">{file.name}</span>
                    <Badge>{file.type.startsWith("video/") ? "video" : "image"}</Badge>
                  </div>
                ))}
              </div>
            ) : null}

            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
              <Button variant="secondary" onClick={createAssetSet} disabled={saving || !productName.trim() || !files.length}>
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileUp className="h-4 w-4" />}
                Create asset
              </Button>
              <Button variant="outline" onClick={addMediaToSelected} disabled={saving || !selectedCollection || !files.length}>
                Add to selected
              </Button>
            </div>

            {notice ? <p className="rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">{notice}</p> : null}
            {error ? <p className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</p> : null}
          </div>
        </Card>

        <main className="grid gap-4">
          <Card className="p-4">
            <CardHeader className="mb-3">
              <div>
                <CardTitle>Library</CardTitle>
                <CardDescription>{collections.length ? `${collections.length} asset set${collections.length === 1 ? "" : "s"} available.` : "No asset sets yet."}</CardDescription>
              </div>
              <Button size="icon" variant="outline" onClick={() => void refresh(selectedCollection?.id)} aria-label="Refresh assets">
                <RefreshCcw className="h-4 w-4" />
              </Button>
            </CardHeader>

            <div className="mb-4 flex items-center gap-2 rounded-md border border-black/10 bg-white px-3 py-2">
              <Search className="h-4 w-4 shrink-0 text-slate-400" />
              <input
                className="h-8 min-w-0 flex-1 bg-transparent text-sm outline-none"
                value={libraryQuery}
                onChange={(event) => setLibraryQuery(event.target.value)}
                placeholder="Search product, tag, detail, scene..."
              />
              {libraryQuery ? <Badge>{visibleCollections.length} result{visibleCollections.length === 1 ? "" : "s"}</Badge> : null}
            </div>

            <div className="grid gap-3 lg:grid-cols-2">
              {visibleCollections.map((collection) => (
                <button
                  key={collection.id}
                  className={`rounded-lg border bg-white p-4 text-left transition hover:border-blue-200 ${
                    selectedCollection?.id === collection.id ? "border-blue-300 ring-4 ring-blue-50" : "border-black/10"
                  }`}
                  onClick={() => setSelectedCollectionId(collection.id)}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate text-sm font-semibold text-slate-950">{collection.product_name}</p>
                        {isDemoCollection(collection) ? <Badge className="border-blue-200 bg-blue-50 text-blue-700">Demo</Badge> : null}
                      </div>
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{collection.description || collection.summary}</p>
                    </div>
                    <Badge>{collection.assets.length} media</Badge>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Badge>{collection.category}</Badge>
                    {collection.coverage.video_slices ? <Badge>video</Badge> : null}
                    {collection.coverage.appearance ? <Badge>images</Badge> : null}
                  </div>
                </button>
              ))}
              {!visibleCollections.length && !loading ? (
                <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500 lg:col-span-2">
                  {collections.length ? "No asset set matches this keyword." : "Upload product images or videos to create the first asset set."}
                </div>
              ) : null}
            </div>
          </Card>

          {selectedCollection ? <CollectionDetail collection={selectedCollection} /> : null}
        </main>
      </section>

      <section className="mt-6 rounded-lg border border-black/10 bg-white p-4 shadow-sm shadow-black/[0.03]">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-950">Next: select viral factors</p>
            <p className="mt-1 text-xs leading-5 text-slate-500">Use this product asset set together with the viral factor library before running Studio.</p>
          </div>
          <Link href="/viral-library">
            <Button variant="secondary">
              Select factors
              <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
        </div>
      </section>
    </>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-600">{label}</span>
      {children}
    </label>
  );
}

function CollectionDetail({ collection }: { collection: AssetCollection }) {
  return (
    <Card className="p-4">
      <CardHeader className="mb-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>{collection.product_name}</CardTitle>
            {isDemoCollection(collection) ? <Badge className="border-blue-200 bg-blue-50 text-blue-700">Demo</Badge> : null}
          </div>
          <CardDescription>{collection.category}</CardDescription>
        </div>
        <Badge>{collection.status}</Badge>
      </CardHeader>

      <div className="mb-4 rounded-lg border border-black/10 bg-[#f5f5f7] p-4">
        <p className="text-sm leading-6 text-slate-700">{collection.description}</p>
        {collection.usage_notes ? <p className="mt-2 text-sm leading-6 text-slate-500">{collection.usage_notes}</p> : null}
      </div>

      <div className="grid gap-4">
        {collection.assets.map((asset) => (
          <AssetRow key={asset.id} asset={asset} />
        ))}
        {!collection.assets.length ? <p className="rounded-md bg-[#f5f5f7] p-6 text-center text-sm text-slate-500">No media in this asset set yet.</p> : null}
      </div>
    </Card>
  );
}

function AssetRow({ asset }: { asset: AssetLibraryItem }) {
  return (
    <article className="grid gap-4 rounded-lg border border-black/10 bg-white p-4 shadow-sm shadow-black/[0.03] md:grid-cols-[180px_minmax(0,1fr)]">
      <MediaPreview asset={asset} />
      <div className="min-w-0">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-slate-950">{asset.filename}</p>
            <p className="mt-1 text-sm leading-6 text-slate-600">{asset.analysis.summary ?? asset.description}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge>{asset.content_type.startsWith("video/") ? "video" : "image"}</Badge>
            {asset.provider_status === "preset" ? <Badge className="border-blue-200 bg-blue-50 text-blue-700">Demo</Badge> : null}
            <Badge>{asset.analysis_status}</Badge>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          {asset.tags.slice(0, 8).map((tag) => (
            <Badge key={tag.id}>{tag.name}</Badge>
          ))}
        </div>

        <div className="mt-4 grid gap-2">
          {asset.slices.slice(0, 4).map((slice) => (
            <div key={slice.id} className="rounded-md border border-black/10 bg-[#f5f5f7] px-3 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs font-medium text-slate-950">{slice.usable_for || slice.slice_type}</p>
                {slice.is_pinned ? <Badge>pinned</Badge> : null}
              </div>
              <p className="mt-1 text-xs leading-5 text-slate-500">{slice.summary}</p>
            </div>
          ))}
        </div>
      </div>
    </article>
  );
}

function MediaPreview({ asset }: { asset: AssetLibraryItem }) {
  const isImage = asset.content_type.startsWith("image/");
  const isVideo = asset.content_type.startsWith("video/");
  return (
    <div className="w-full overflow-hidden rounded-lg border border-black/10 bg-[#f5f5f7]">
      <div className="aspect-[9/16] w-full">
        {isImage ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img className="h-full w-full object-contain" src={assetFileUrl(asset.id)} alt={asset.filename} />
        ) : isVideo ? (
          <video className="h-full w-full object-cover" src={assetFileUrl(asset.id)} controls muted playsInline />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-slate-500">
            {isVideo ? <Film className="h-7 w-7" /> : <ImageIcon className="h-7 w-7" />}
            <p className="text-xs">Media</p>
          </div>
        )}
      </div>
    </div>
  );
}

function isDemoCollection(collection: AssetCollection) {
  return collection.product_name === "Aurora Glow Bottle" && collection.assets.some((asset) => asset.provider_status === "preset");
}
