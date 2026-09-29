import { useState } from "react"
import { Loader2Icon, LockIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ApiError, api, type User } from "@/lib/api"

export function LoginPage({ onLogin, expired }: { onLogin: (user: User) => void; expired: boolean }) {
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(expired ? "Your session has ended. Please sign in again." : null)
  const [busy, setBusy] = useState(false)

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
          <CardContent>
            <form onSubmit={submit} className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="username">Username</Label>
                <Input
                  id="username"
                  autoComplete="username"
                  autoFocus
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
              {error && (
                <p role="alert" className="bg-muted rounded-md px-3 py-2 text-sm font-medium">
                  {error}
                </p>
              )}
              <Button type="submit" disabled={busy || !username.trim() || !password}>
                {busy ? <Loader2Icon className="animate-spin" /> : <LockIcon />}
                Sign in
              </Button>
            </form>
          </CardContent>
        </Card>
        <p className="text-muted-foreground mt-4 text-center text-xs">
          Accounts are created by an administrator.
        </p>
      </div>
    </div>
  )
}
