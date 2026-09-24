import type { AnalystSource } from "@/lib/api";

function sourceUrl(value?: string | null): string | null {
  if (!value || /[\s\\]/.test(value)) return null;
  try {
    const url = new URL(value);
    const approved = ["rotowire.com", "rotoballer.com", "fantasypros.com", "nflverse.com"];
    return url.protocol === "https:" && !url.username && !url.password && !url.port
      && approved.some((host) => url.hostname === host || url.hostname.endsWith(`.${host}`)) ? value : null;
  } catch { return null; }
}

export function AnalystSources({ sources = [], note }: { sources?: AnalystSource[]; note?: string | null }) {
  if (!sources.length && !note) return null;
  return <aside aria-label="Recap sources" className="mt-8 border-t border-rule pt-5 text-sm text-body break-words">
    {note && <p className="mb-3 text-dim">{note}</p>}
    {sources.length > 0 && <details>
      <summary className="min-h-tap cursor-pointer font-bold text-ink">Sources and player context ({sources.length})</summary>
      <p className="mb-3 text-dim">Reporting and usage supplied for this edition. Publication dates are shown when available.</p>
      <ul className="space-y-3">
        {sources.map((source, index) => {
          const href = sourceUrl(source.url);
          const date = source.published_at ? new Date(source.published_at) : null;
          return <li key={`${source.title}-${index}`}>
            {href ? <a href={href} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer"
              className="inline-flex min-h-tap items-center text-stamp underline underline-offset-4 hover:text-ink">{source.title}</a>
              : <span>{source.title}</span>}
            <p className="text-dim">{source.publisher}{date && Number.isFinite(date.getTime())
              ? ` · ${date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" })}` : ""}</p>
          </li>;
        })}
      </ul>
    </details>}
  </aside>;
}
