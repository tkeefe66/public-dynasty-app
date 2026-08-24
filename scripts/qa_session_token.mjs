/**
 * Mint a NextAuth session JWT for local QA, so headless Chrome can drive the
 * app past the login gate.
 *
 * Dev-only, and local-only by construction: it signs with the `AUTH_SECRET` in
 * `web/.env.local`, which is not the production secret, so the token it prints
 * is worthless against anything but your own dev server. It reads secrets and
 * never contains one.
 *
 * Why this exists rather than driving the real sign-in: the app is gated by
 * NextAuth + Google OAuth, and a consent screen is not drivable headlessly.
 * Three details make this work and none of them are guessable:
 *
 *   - the salt is the literal cookie name, "authjs.session-token"
 *   - the encoder must be `@auth/core/jwt`'s `encode` — a token signed with
 *     `jsonwebtoken` is rejected, because Auth.js v5 encrypts (JWE) rather
 *     than merely signing
 *   - `@auth/core` is a dependency of `web/`, not of the repo root, so this
 *     file resolves it by absolute path instead of a bare import
 *
 * THE EMAIL DECIDES WHAT THE SESSION CAN SEE, and getting it wrong looks like
 * a broken app rather than a bad token: the backend resolves the user from this
 * claim, so a made-up address yields a real session with no league memberships
 * and every league 403s. Pass `--email` for the address that actually owns the
 * leagues you are testing. The default only works for a league named by
 * `TRADE_GRADER_ALLOWLISTED_LEAGUE_ID`, which any signed-in user may view.
 *
 * Usage:
 *
 *     node scripts/qa_session_token.mjs --email you@example.com
 *     node scripts/qa_session_token.mjs --ttl 7200          # allowlisted league only
 *
 * Or set QA_SESSION_EMAIL once instead of passing it every run. Then hand the
 * value to the browser as the `authjs.session-token` cookie on `localhost`
 * (see the `headless-viewport-qa` skill).
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ENV_FILE = path.join(ROOT, "web", ".env.local");
const JWT_MODULE = path.join(ROOT, "web", "node_modules", "@auth", "core", "jwt.js");

function die(what, why, fix) {
  console.error(`qa_session_token: ${what}\n  why: ${why}\n  try: ${fix}`);
  process.exit(1);
}

const args = new Map();
for (let i = 2; i < process.argv.length; i += 2) {
  args.set(process.argv[i].replace(/^--/, ""), process.argv[i + 1]);
}

if (!fs.existsSync(ENV_FILE)) {
  die(`cannot read ${path.relative(ROOT, ENV_FILE)}`,
      "the signing secret lives there and there is no default worth guessing",
      "copy web/.env.example to web/.env.local and set AUTH_SECRET");
}
if (!fs.existsSync(JWT_MODULE)) {
  die("@auth/core is not installed",
      "it is a dependency of web/, which has no node_modules yet",
      "cd web && npm install");
}

/* Deliberately not a dotenv parse: `.env.local` here is flat KEY=VALUE with no
   quoting or interpolation, and splitting on the FIRST '=' is what keeps a
   base64 secret containing '=' padding intact. */
const env = Object.fromEntries(
  fs.readFileSync(ENV_FILE, "utf8")
    .split("\n")
    .filter((l) => l.trim() && !l.trimStart().startsWith("#") && l.includes("="))
    .map((l) => {
      const i = l.indexOf("=");
      return [l.slice(0, i).trim(), l.slice(i + 1).trim()];
    }),
);

if (!env.AUTH_SECRET) {
  die("AUTH_SECRET is not set in web/.env.local",
      "the token is signed with it, and an unsigned token is refused by middleware",
      "add AUTH_SECRET=... (any value your dev server also uses)");
}

const { encode } = await import(pathToFileURL(JWT_MODULE).href);
const now = Math.floor(Date.now() / 1000);
const ttl = Number(args.get("ttl") ?? 3600);
const email = args.get("email") ?? process.env.QA_SESSION_EMAIL ?? "qa@localhost";
if (!args.has("email") && !process.env.QA_SESSION_EMAIL) {
  console.error(
    "qa_session_token: no --email given, using qa@localhost.\n" +
    "  This session has NO league memberships. It can only view the league in\n" +
    "  TRADE_GRADER_ALLOWLISTED_LEAGUE_ID; anything else will 403.");
}

console.log(await encode({
  token: {
    name: args.get("name") ?? "QA",
    email,
    sub: args.get("sub") ?? "qa-visual-pass",
    iat: now,
    exp: now + ttl,
  },
  secret: env.AUTH_SECRET,
  salt: "authjs.session-token",
}));
