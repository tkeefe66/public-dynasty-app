import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

/**
 * First-party auth for the web app. NextAuth owns the Google OAuth dance and a
 * same-origin httpOnly session cookie. The backend-facing HS256 token is minted
 * on demand in lib/auth-server.ts (Node-only), NOT here — this module is also
 * imported by middleware (edge runtime), so it must stay free of `jose` /
 * `server-only` / Node APIs.
 */
export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Google],
  session: { strategy: "jwt" },
  callbacks: {
    async jwt({ token, profile }) {
      // Capture the Google subject + profile on sign-in; persists on the JWT.
      if (profile) {
        token.sub = (profile.sub as string) ?? token.sub;
        token.email = profile.email ?? token.email;
        token.name = profile.name ?? token.name;
        token.picture = (profile.picture as string) ?? token.picture;
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user && token.sub) {
        (session.user as { id?: string }).id = token.sub;
      }
      return session;
    },
  },
});
