import { signIn } from "@/auth";
import { Button } from "@/components/furniture/Button";
import { PRODUCT_NAME } from "@/lib/brand";
import { Wordmark } from "@/components/furniture/Wordmark";

export const dynamic = "force-dynamic";

export const metadata = {
  title: `Sign in · ${PRODUCT_NAME}`,
};

/**
 * Agate — the front door (design_handoff_agate/DESIGN.md § "Depth": "Cards are
 * gone as a concept"). The sign-in copy sits directly on `--bg` in a left-
 * aligned column, opened by a 1px `--ink` rule: Archivo headline → one line of
 * body → the primary button. No box, no radius, no fill, nothing centered. The
 * mono kicker that used to precede the headline is gone — it named the product
 * something the product is no longer called.
 */
export default function LoginPage() {
  return (
    <main className="min-h-screen bg-bg px-6 pt-[22vh] text-ink">
      <div className="mx-auto w-full max-w-sm">
        {/* The `--ink` rule that opens the column moves onto the headline. It
            used to sit above a mono kicker reading "Sleeper dynasty trade
            grader" — a name the product no longer goes by, printed one line
            above the name it does go by. The rule is the opening gesture, not
            the kicker, so it survives the line it used to introduce. */}
        <h1 className="flex items-center gap-2.5 border-t border-ink pt-3 font-display text-lead font-extrabold tracking-[-0.03em]">
          <Wordmark size={30} showName={false} />
          {PRODUCT_NAME}
        </h1>
        <p className="mt-3 max-w-[46ch] text-prose leading-relaxed text-body">
          Sign in to view your leagues and analyze your performance.
        </p>

        <form
          action={async () => {
            "use server";
            await signIn("google", { redirectTo: "/" });
          }}
          className="mt-6"
        >
          <Button as="button" type="submit" className="w-full px-4 py-2.5">
            Continue with Google
          </Button>
        </form>
      </div>
    </main>
  );
}
