import { Shell } from "@/components/Shell";
import { IndeterminateBar } from "@/components/furniture/IndeterminateBar";

export default function Loading() {
  return <Shell><p className="mb-4 text-prose text-dim">Loading scoring leaders…</p><IndeterminateBar /></Shell>;
}
