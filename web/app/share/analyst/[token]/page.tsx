import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Article } from "@/components/AnalystArchive";
import { AnalystSources } from "@/components/AnalystSources";
import { publicAnalyst } from "@/lib/public-analyst";
import { RecapMedia } from "@/components/RecapMedia";
import { recapMediaBase } from "@/lib/recap-media";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function generateMetadata({ params }: { params: { token: string } }): Promise<Metadata> {
  let edition;
  try { edition = await publicAnalyst(params.token); } catch { /* Page displays the retry state. */ }
  const title = edition ? `Weekly recap · Week ${edition.week} · ${edition.league_name}` : "Shared recap unavailable";
  const description = edition?.media ? "Watch the weekly league recap with Cal Mercer, or read the full article. No sign-in required." : "Read the weekly league recap. No sign-in required.";
  const images = edition?.media ? [{ url: `${recapMediaBase(params.token, edition.media.id)}/poster.jpg`, alt: title }] : [];
  return { title, description,
    robots: { index: false, follow: false, nocache: true }, referrer: "no-referrer",
    openGraph: { title, description, type: "article", images },
    twitter: { card: edition?.media ? "summary_large_image" : "summary", title, description, images } };
}

export default async function SharedAnalyst({ params }: { params: { token: string } }) {
  let edition;
  try { edition = await publicAnalyst(params.token); }
  catch { return <main className="mx-auto max-w-[72ch] px-5 py-12"><h1 className="font-display text-title font-bold">The recap could not be loaded.</h1><p className="mt-4">Please reload this page to try again.</p></main>; }
  if (!edition) notFound();
  return <main className="mx-auto max-w-[76ch] px-5 py-8 sm:px-8 sm:py-12">
    <header className="mb-8 border-b border-rule pb-6">
      <p className="text-sm text-dim">Weekly recap · {edition.season}</p>
      <h1 className="mt-2 font-display text-lead font-extrabold">Week {edition.week} recap</h1>
      <p className="mt-3 text-body">{edition.league_name}</p>
      {edition.edition_type === "results" && <p className="mt-3 text-sm text-dim">Results edition from verified league scores</p>}
      {edition.correction_note && <p className="mt-3 text-sm text-body"><strong>Corrected edition.</strong> This page shows the latest corrected article.</p>}
    </header>
    {edition.media && <RecapMedia token={params.token} media={edition.media} week={edition.week} />}
    <article><Article markdown={edition.markdown} /></article>
    <AnalystSources sources={edition.sources} note={edition.context_note} />
    <footer className="mt-10 border-t border-rule pt-5 text-sm text-dim">Shared from Weekly recap. This link gives access to this recap only.</footer>
  </main>;
}
