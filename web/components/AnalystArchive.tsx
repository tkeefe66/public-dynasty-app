import Link from "next/link";
import { Panel } from "./furniture/Panel";
import type { AnalystEdition } from "@/lib/api";
import { AnalystShare } from "./AnalystShare";
import { AnalystSources } from "./AnalystSources";
import { AnalystMasthead } from "./AnalystMasthead";
import { RecapMedia } from "./RecapMedia";
import type { RecapMediaInfo } from "@/lib/recap-media";

// A small, deliberately text-only Markdown subset. Model output never becomes
// HTML, executable links, images, or embedded content.
function inline(text: string) {
  return text.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g).map((part, i) =>
    part.startsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong>
      : part.startsWith("*") ? <em key={i}>{part.slice(1, -1)}</em> : part,
  );
}

export function Article({ markdown }: { markdown: string }) {
  const blocks = markdown.trim().split(/\n\s*\n/);
  return <div className="space-y-5 text-prose leading-relaxed text-body break-words">
    {blocks.map((block, i) => {
      const lines = block.split("\n");
      if (/^#{1,6}\s/.test(lines[0])) {
        const title = lines[0].replace(/^#{1,6}\s+/, "");
        return <section key={i} className="pt-5 first:pt-0">
          <h3 className="mb-3 font-display text-title font-bold text-ink">{inline(title)}</h3>
          {lines.length > 1 && <p>{inline(lines.slice(1).join(" "))}</p>}
        </section>;
      }
      if (lines.every((line) => /^[-*]\s/.test(line))) {
        return <ul key={i} className="list-disc space-y-2 pl-5">
          {lines.map((line, j) => <li key={j}>{inline(line.replace(/^[-*]\s+/, ""))}</li>)}
        </ul>;
      }
      if (/^[-*_]{3,}$/.test(block.trim())) return <hr key={i} className="border-rule" />;
      return <p key={i}>{inline(lines.join(" "))}</p>;
    })}
  </div>;
}

export function AnalystArchive({ leagueId, editions, selected, media, mediaError }: {
  leagueId: string; editions: AnalystEdition[]; selected?: string;
  media?: { token: string; info: RecapMediaInfo }; mediaError?: boolean;
}) {
  editions = editions.filter((item) => item.edition_type !== "results");
  const edition = selected
    ? editions.find((item) => `${item.season}-${item.week}` === selected)
    : editions[0];
  return <section className="pb-12">
    <Link href={`/league/${leagueId}`} className="inline-flex min-h-tap items-center text-dim hover:text-ink">
      ← League homepage
    </Link>
    <header className="mt-4 mb-8">
      <AnalystMasthead />
    </header>
    <div className="grid items-start gap-8 lg:grid-cols-[220px_minmax(0,1fr)]">
      <nav aria-label="Saved editions" className="min-w-0">
        <h2 className="mb-3 font-display text-title font-bold">Saved editions</h2>
        {editions.length ? <div className="flex flex-wrap gap-2 lg:flex-col">
          {editions.map((item) => {
            const active = item === edition;
            return <Link key={`${item.season}-${item.week}`}
              href={`/league/${leagueId}/analyst?edition=${item.season}-${item.week}`}
              aria-current={active ? "page" : undefined}
              className={`inline-flex min-h-tap items-center rounded-pill px-4 py-2 text-sm transition-colors ${active ? "bg-stamp text-stamp-ink" : "text-body hover:bg-surface-sunk"}`}>
              {item.season} · Week {item.week}
            </Link>;
          })}
        </div> : <p className="text-sm text-dim">No editions yet.</p>}
      </nav>
      <Panel className="min-w-0">
        <article className="mx-auto max-w-[72ch] px-5 py-6 sm:px-8 sm:py-8">
          {edition ? <>
            <header className="mb-7 border-b border-rule pb-6">
              <h2 className="font-display text-title font-bold">Week {edition.week} · {edition.season}</h2>
              <p className="mt-2 text-body">{edition.league_name}</p>
              <p className="mt-3 text-sm text-dim">Published {new Date(edition.generated_at).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric", timeZone: "UTC" })} · AI-written from league results</p>
              {edition.correction_note && <p className="mt-3 text-sm text-body"><strong>Corrected edition:</strong> {edition.correction_note}</p>}
              <AnalystShare key={`${edition.season}-${edition.week}`} leagueId={leagueId} season={edition.season} week={edition.week} />
            </header>
            {media && <RecapMedia token={media.token} media={media.info} week={edition.week} />}
            {mediaError && <p role="status" className="mb-6 text-sm text-dim">Video and audio could not be loaded. Reload this page to try again. The article is still available.</p>}
            <Article markdown={edition.markdown} />
            <AnalystSources sources={edition.sources} note={edition.context_note} />
            {edition.original_markdown && <details className="mt-8 border-t border-rule pt-4">
              <summary className="min-h-tap cursor-pointer text-sm text-dim">View original edition</summary>
              <Article markdown={edition.original_markdown} />
            </details>}
          </> : <>
            <h2 className="font-display text-title font-bold">{selected ? "That edition is not available yet." : "The first edition is on its way."}</h2>
            <p className="mt-4 text-prose leading-relaxed text-body">Completed weeks become saved editions after the writing and factual review are finished. Each published recap stays here for the season and beyond.</p>
            <p className="mt-3 text-sm text-dim">If writing is paused or factual review fails, the next recap stays unpublished until it is ready.</p>
          </>}
        </article>
      </Panel>
    </div>
  </section>;
}
