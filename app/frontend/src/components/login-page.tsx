import { useEffect, useState } from "react"
import { Loader2Icon, LockIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ApiError, api, type AuthConfig, type User } from "@/lib/api"

// Set by the API when the Microsoft round trip ends without a session.
const LOGIN_ERRORS: Record<string, string> = {
  entra_cancelled: "Microsoft sign-in was cancelled.",
  entra_tenant: "This Microsoft account's organization is not allowed to use this app.",
  entra_failed: "Microsoft sign-in failed. Please try again.",
  account_disabled: "This account has been disabled by an administrator.",
}

function takeLoginError(): string | null {
  const params = new URLSearchParams(window.location.search)
  const code = params.get("login_error")
  if (!code) return null
  params.delete("login_error")
  const qs = params.toString()
  window.history.replaceState(null, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`)
  return LOGIN_ERRORS[code] ?? LOGIN_ERRORS.entra_failed
}

function MicrosoftLogo() {
  return (
    <svg viewBox="0 0 21 21" className="size-4" aria-hidden>
      <rect x="1" y="1" width="9" height="9" fill="currentColor" />
      <rect x="11" y="1" width="9" height="9" fill="currentColor" opacity=".75" />
      <rect x="1" y="11" width="9" height="9" fill="currentColor" opacity=".75" />
      <rect x="11" y="11" width="9" height="9" fill="currentColor" opacity=".5" />
    </svg>
  )
}

export function LoginPage({ onLogin, expired }: { onLogin: (user: User) => void; expired: boolean }) {
  const [config, setConfig] = useState<AuthConfig | null>(null)
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(
    () => takeLoginError() ?? (expired ? "Your session has ended. Please sign in again." : null)
  )
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.authConfig().then(setConfig, () => setConfig({ password: true, entra: false }))
  }, [])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!username.trim() || !password) return
    setBusy(true)
    setError(null)
    try {
      onLogin(await api.login(username.trim(), password))
    } catch (err) {
      setPassword("")
      setError(
        err instanceof ApiError && err.status === 429
          ? "Too many failed attempts. Wait a few minutes and try again."
          : err instanceof Error
            ? err.message
            : "Sign-in failed"
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="bg-muted/40 flex min-h-svh items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-3">
          <div className="bg-primary text-primary-foreground grid size-9 place-items-center rounded-lg">
            <svg viewBox="0 0 32 32" className="size-5" fill="none" aria-hidden>
              <path d="M6 24h5v-5h5v-5h5V9h5" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <span className="text-lg font-semibold tracking-tight">LearningSteps</span>
        </div>
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Sign in</CardTitle>
            <CardDescription>Your journal is private to your account.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            {!config ? (
              <div className="grid h-24 place-items-center">
                <Loader2Icon className="text-muted-foreground size-5 animate-spin" aria-label="Loading" />
              </div>
            ) : (
              <>
                {config.entra && (
                  <Button asChild variant={config.password ? "outline" : "default"} size="lg">
                    {/* A full-page navigation: the API redirects to Microsoft and back. */}
                    <a href="/api/auth/entra/login">
                      <MicrosoftLogo /> Sign in with Microsoft
                    </a>
                  </Button>
                )}

                {config.entra && config.password && (
                  <div className="text-muted-foreground flex items-center gap-3 text-xs">
                    <div className="bg-border h-px flex-1" /> or <div className="bg-border h-px flex-1" />
                  </div>
                )}

                {config.password && (
                  <form onSubmit={submit} className="grid gap-4">
                    <div className="grid gap-2">
                      <Label htmlFor="username">Username</Label>
                      <Input
                        id="username"
                        autoComplete="username"
                        autoFocus={!config.entra}
                        maxLength={64}
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="password">Password</Label>
                      <Input
                        id="password"
                        type="password"
                        autoComplete="current-password"
                        maxLength={256}
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                      />
                    </div>
                    <Button type="submit" disabled={busy || !username.trim() || !password}>
                      {busy ? <Loader2Icon className="animate-spin" /> : <LockIcon />}
                      Sign in
                    </Button>
                  </form>
                )}

                {error && (
                  <p role="alert" className="bg-muted rounded-md px-3 py-2 text-sm font-medium">
                    {error}
                  </p>
                )}

                {!config.entra && !config.password && (
                  <p className="text-muted-foreground text-sm">No sign-in method is configured.</p>
                )}
              </>
            )}
          </CardContent>
        </Card>
        <p className="text-muted-foreground mt-4 text-center text-xs">
          {config?.entra ? "Use your university or work Microsoft account." : "Accounts are created by an administrator."}
        </p>
      </div>
    </div>
  )
}
