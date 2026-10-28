# Login Requirements — Azure AD (Microsoft Entra ID) Integration

## Overview

This document covers everything needed to make the **Azure AD / Microsoft Entra ID** login button on the ZADDP login page actually work. Currently, both login buttons are mock implementations that just redirect to the dashboard after a 1-second delay.

---

## 1. Azure Portal — App Registration

Go to **[Azure Portal → Microsoft Entra ID → App registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)** and create a new registration.

### Required Configuration

| Setting | Value |
|---|---|
| **Name** | `ZADDP` (or any name) |
| **Supported account types** | Choose one: |
| | • *"Accounts in this organizational directory only"* — single-tenant (your company only) |
| | • *"Accounts in any organizational directory"* — multi-tenant |
| | • *"Personal Microsoft accounts"* — if needed |
| **Platform type** | Choose **"Single-page application (SPA)"** (NOT "Web") |
| **Redirect URI** | `http://localhost:3000/api/auth/callback/azure-ad` |

> **Note:** Azure AD enforces HTTPS for most redirect URIs, but allows `http://localhost` under the **SPA** platform type. If you still get an HTTPS-only error, use [ngrok](https://ngrok.com) to create an HTTPS tunnel:
> ```bash
> ngrok http 3000
> ```
> Then set the redirect URI to `https://your-ngrok-url.ngrok-free.app/api/auth/callback/azure-ad`

### Credentials to Collect

Once the app is created, you'll need these 3 values:

| Variable | Where to Find It |
|---|---|
| **Client ID** | *Overview* page → **Application (client) ID** |
| **Tenant ID** | *Overview* page → **Directory (tenant) ID** |
| **Client Secret** | *Certificates & secrets* → **Client secrets** → *New client secret* → copy the **Value** |

---

## 2. Environment Variables

### Needed in `docker-compose.yml` (under `frontend` service)

```yaml
environment:
  AZURE_AD_CLIENT_ID: <your_client_id>
  AZURE_AD_CLIENT_SECRET: <your_client_secret>
  AZURE_AD_TENANT_ID: <your_tenant_id>
  # Already present:
  NEXTAUTH_SECRET: hackathon-demo-nextauth-secret
  NEXTAUTH_URL: http://localhost:3000
```

### Also add to `.env.local` (for local dev without Docker)

```bash
AZURE_AD_CLIENT_ID=your_client_id
AZURE_AD_CLIENT_SECRET=your_client_secret
AZURE_AD_TENANT_ID=your_tenant_id
NEXTAUTH_SECRET=hackathon-demo-nextauth-secret
NEXTAUTH_URL=http://localhost:3000
```

---

## 3. Files to Create / Modify

### 3a. Create: `frontend/app/api/auth/[...nextauth]/route.ts`

The NextAuth route handler that processes Azure AD OAuth callbacks.

```typescript
import NextAuth from "next-auth";
import AzureADProvider from "next-auth/providers/azure-ad";

const handler = NextAuth({
  providers: [
    AzureADProvider({
      clientId: process.env.AZURE_AD_CLIENT_ID as string,
      clientSecret: process.env.AZURE_AD_CLIENT_SECRET as string,
      tenantId: process.env.AZURE_AD_TENANT_ID as string,
    }),
  ],
  session: { strategy: "jwt" },
  callbacks: {
    async jwt({ token, account, profile }) {
      if (account) {
        token.accessToken = account.access_token;
      }
      return token;
    },
    async session({ session, token }) {
      return session;
    },
  },
});

export { handler as GET, handler as POST };
```

### 3b. Modify: `frontend/app/login/page.tsx`

Replace the mock `handleLogin` function with real NextAuth sign-in.

**Import:**
```tsx
import { signIn } from 'next-auth/react';
```

**Azure AD button's onClick:**
```tsx
onClick={() => signIn('azure-ad', { callbackUrl: '/dashboard' })}
```

**Demo Login button** — can either:
- Keep as-is (mock) for quick demo access
- Change to `signIn('azure-ad')` as well
- Add a separate credentials provider if desired

### 3c. Modify: `frontend/app/providers.tsx`

Wrap the app with NextAuth's `SessionProvider`:

```tsx
import { SessionProvider } from 'next-auth/react';

export function Providers({ children, session }: { children: React.ReactNode; session?: any }) {
  return (
    <SessionProvider session={session}>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          {children}
          <Toaster ... />
        </ThemeProvider>
      </QueryClientProvider>
    </SessionProvider>
  );
}
```

### 3d. Modify: `frontend/app/(authenticated)/layout.tsx`

Add session check — redirect to `/login` if not authenticated:

```tsx
import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

export default function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  const { data: session, status } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (status === 'unauthenticated') {
      router.replace('/login');
    }
  }, [status, router]);

  if (status === 'loading') {
    return <div>Loading...</div>;
  }

  if (!session) return null;

  return (
    <div className="flex h-screen ...">
      ...
    </div>
  );
}
```

### 3e. (Optional) Update the Dockerfile

Ensure the NextAuth route handler is included in the Docker build. No change needed — the `next build` command picks up all routes automatically.

---

## 4. Naming Note

| Old Name | New Name | Used In |
|---|---|---|
| **Azure Active Directory (Azure AD)** | **Microsoft Entra ID** | Azure Portal |
| `next-auth/providers/azure-ad` | (still `azure-ad` in NextAuth v4) | Code |
| `next-auth/providers/microsoft-entra-id` | (new name in NextAuth v5 / Auth.js) | Code (if upgraded) |

The app is on **NextAuth v4**, so the import remains `azure-ad` even though the portal now calls it Microsoft Entra ID.

---

## 5. Verification Checklist

- [ ] App Registration created in Microsoft Entra ID
- [ ] Redirect URI set to `http://localhost:3000/api/auth/callback/azure-ad`
- [ ] Client ID, Client Secret, and Tenant ID collected
- [ ] Environment variables added to `docker-compose.yml`
- [ ] `[...nextauth]/route.ts` created
- [ ] Login page updated with `signIn('azure-ad')`
- [ ] `SessionProvider` added to `providers.tsx`
- [ ] Authenticated layout checks for session
- [ ] App restarted and tested end-to-end

---

## 6. Testing Flow

1. Start the app: `docker compose up` (or `npm run dev` in frontend)
2. Navigate to `http://localhost:3000`
3. Click **"Sign in with Azure AD"**
4. You'll be redirected to Microsoft's login page
5. Sign in with your corporate Microsoft account
6. After successful auth, you'll be redirected back to `/dashboard`
7. The sidebar should show your name and role from Azure AD
