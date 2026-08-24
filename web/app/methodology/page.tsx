import { Shell } from "@/components/Shell";
import { TopBar } from "@/components/TopBar";
import { MethodologyContent } from "@/components/methodology/MethodologyContent";
import { MethodologyToc } from "@/components/methodology/MethodologyToc";

export default function MethodologyPage() {
  return (
    <Shell>
      <TopBar activeNav="methodology" />
      <div className="lg:grid lg:grid-cols-[180px_1fr] lg:gap-12">
        <MethodologyToc />
        <div className="min-w-0">
          <MethodologyContent />
        </div>
      </div>
    </Shell>
  );
}
