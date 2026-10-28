import NextAuth from "next-auth";
import AzureADProvider from "next-auth/providers/azure-ad";
import CredentialsProvider from "next-auth/providers/credentials";

const handler = NextAuth({
  providers: [
    AzureADProvider({
      clientId: process.env.AZURE_AD_CLIENT_ID as string,
      clientSecret: process.env.AZURE_AD_CLIENT_SECRET as string,
      tenantId: process.env.AZURE_AD_TENANT_ID as string,
    }),
    CredentialsProvider({
      id: "demo",
      name: "Demo",
      credentials: {
        username: { label: "Username", type: "text" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        if (
          credentials?.username === "admin" &&
          credentials?.password === "admin"
        ) {
          return {
            id: "1",
            name: "Admin",
            email: "admin@zaddp.io",
          };
        }
        return null;
      },
    }),
  ],
  pages: {
    signIn: "/login",
  },
  session: {
    strategy: "jwt",
  },
  callbacks: {
    async jwt({ token, account, profile }) {
      if (account) {
        token.accessToken = account.access_token;
        if (account.provider === "demo") {
          token.role = "admin";
        } else {
          const admins = (process.env.ML_ADMIN_EMAILS || "admin@zaddp.io")
            .split(",")
            .map((email) => email.trim().toLowerCase())
            .filter(Boolean);
          const email = String(profile?.email || token.email || "").toLowerCase();
          token.role = admins.includes(email) ? "admin" : "viewer";
        }
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        (session.user as any).role = token.role || "viewer";
      }
      return session;
    },
  },
});

export { handler as GET, handler as POST };
