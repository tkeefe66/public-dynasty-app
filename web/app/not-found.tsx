import Link from "next/link";
import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";

export default function NotFound() {
  return (
    <Shell>
      <TopBar />
      {/* Nothing in Agate is centered, and a 404 is a headline like any other
          failure (DESIGN.md § "Failure Is A Headline"). */}
      <section className="mt-24 max-w-[52ch]">
        <div className="border-b border-rule pb-1.5 font-mono text-label uppercase tracking-[0.16em] text-dim">
          404
        </div>
        <h1 className="mt-3 font-display text-lead font-extrabold tracking-[-0.03em] text-ink">
          That URL is offsides.
        </h1>
        <p className="mt-2 text-prose leading-relaxed text-body">
          Nothing lives at this address. Your leagues are all one hop away.
        </p>
        <Link
          href="/"
          className="mt-6 inline-block font-mono text-label uppercase tracking-[0.1em] text-dim hover:text-ink"
        >
          ← Home
        </Link>
      </section>
    </Shell>
  );
}
