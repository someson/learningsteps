import { useCallback, useEffect, useState } from "react"
import { ArrowLeftIcon, BanIcon, InboxIcon, Loader2Icon, RefreshCwIcon, ShieldIcon, UndoIcon } from "lucide-react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/confirm-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { api, formatDate, type AdminUser, type User } from "@/lib/api"
import { cn } from "@/lib/utils"

// Administration: who uses the app, and blocking accounts. Journal contents
// of other users are intentionally not shown here (or anywhere).
export function AdminPage({ me, onBack, onEntriesChanged }: { me: User; onBack: () => void; onEntriesChanged: () => void }) {
  const [users, setUsers] = useState<AdminUser[] | null>(null)
  const [orphans, setOrphans] = useState(0)
  const [loading, setLoading] = useState(true)
  const [blocking, setBlocking] = useState<AdminUser | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [adopting, setAdopting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.admin.users()
      setUsers(data.users)
      setOrphans(data.orphan_entries)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not load users")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function unblock(user: AdminUser) {
    setBusyId(user.id)
    try {
      await api.admin.unblock(user.id)
      toast.success(`${user.name} can sign in again`)
      await load()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not unblock")
    } finally {
      setBusyId(null)
    }
  }

  async function block(user: AdminUser) {
    try {
      await api.admin.block(user.id)
      toast.success(`${user.name} is blocked and signed out`)
      await load()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not block")
      throw err
    }
  }

  async function adopt() {
    setAdopting(true)
    try {
      const { adopted } = await api.admin.adoptOrphans()
      toast.success(`${adopted} ${adopted === 1 ? "entry" : "entries"} moved to your journal`)
      onEntriesChanged()
      await load()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not assign entries")
    } finally {
      setAdopting(false)
    }
  }

  const admins = users?.filter((u) => u.is_admin).length ?? 0
  const blocked = users?.filter((u) => u.disabled_at).length ?? 0

  return (
    <main className="mx-auto grid w-full max-w-7xl flex-1 grid-cols-[minmax(0,1fr)] content-start gap-6 px-4 py-8 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Button variant="ghost" size="sm" className="-ml-3 mb-2" onClick={onBack}>
            <ArrowLeftIcon /> Back to journal
          </Button>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <ShieldIcon className="size-6" /> Administration
          </h1>
          <p className="text-muted-foreground text-sm">
            Who uses LearningSteps. Journal contents stay private to their authors.
          </p>
        </div>
        <Button variant="outline" size="icon" onClick={load} aria-label="Refresh">
          <RefreshCwIcon className={cn(loading && "animate-spin")} />
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-4">
        <Stat title="Users" value={users ? String(users.length) : null} />
        <Stat title="Administrators" value={users ? String(admins) : null} />
        <Stat title="Blocked" value={users ? String(blocked) : null} />
        <Card className="gap-2 py-4">
          <CardHeader className="px-5">
            <CardDescription>Entries without owner</CardDescription>
            <CardTitle className="text-2xl font-semibold tabular-nums">
              {users ? orphans : <Skeleton className="h-8 w-20" />}
            </CardTitle>
            {orphans > 0 && (
              <CardAction>
                <Button size="sm" variant="outline" disabled={adopting} onClick={adopt}>
                  {adopting ? <Loader2Icon className="animate-spin" /> : <InboxIcon />} Assign to me
                </Button>
              </CardAction>
            )}
          </CardHeader>
        </Card>
      </div>

      <Card className="gap-0 py-0">
        <CardHeader className="border-b py-4 [.border-b]:pb-4">
          <CardTitle>Users</CardTitle>
          <CardDescription>
            Blocking signs a user out everywhere and refuses their next sign-in. Admin rights are granted in
            Microsoft Entra (app role “Administrator”).
          </CardDescription>
        </CardHeader>
        <CardContent className="px-0">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-6">Name</TableHead>
                <TableHead>Sign-in</TableHead>
                <TableHead className="text-right">Entries</TableHead>
                <TableHead>Joined</TableHead>
                <TableHead>Last sign-in</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="pr-6 text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {!users
                ? Array.from({ length: 3 }, (_, i) => (
                    <TableRow key={i}>
                      {Array.from({ length: 7 }, (_, j) => (
                        <TableCell key={j} className="first:pl-6">
                          <Skeleton className="h-4 w-full max-w-32" />
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                : users.map((u) => {
                    const self = u.id === me.id
                    return (
                      <TableRow key={u.id} className={cn(u.disabled_at && "text-muted-foreground")}>
                        <TableCell className="pl-6 font-medium">
                          <span className="flex flex-wrap items-center gap-1.5">
                            {u.name}
                            {self && <Badge variant="secondary">you</Badge>}
                            {u.is_admin && <Badge>Admin</Badge>}
                          </span>
                        </TableCell>
                        <TableCell>
                          <span className="flex flex-wrap items-center gap-1.5">
                            <span className="max-w-64 truncate" title={u.login}>
                              {u.login}
                            </span>
                            <Badge variant="outline" className="font-normal">
                              {u.kind === "entra" ? "Microsoft" : "Local"}
                            </Badge>
                          </span>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{u.entries}</TableCell>
                        <TableCell className="whitespace-nowrap">{formatDate(u.created_at)}</TableCell>
                        <TableCell className="whitespace-nowrap">
                          {u.last_login_at ? formatDate(u.last_login_at) : "—"}
                        </TableCell>
                        <TableCell>
                          {u.disabled_at ? (
                            <Badge variant="outline" title={`Since ${formatDate(u.disabled_at)}`}>
                              Blocked
                            </Badge>
                          ) : (
                            <Badge variant="secondary">Active</Badge>
                          )}
                        </TableCell>
                        <TableCell className="pr-6 text-right">
                          {self ? (
                            <span className="text-muted-foreground text-xs">—</span>
                          ) : u.disabled_at ? (
                            <Button size="sm" variant="outline" disabled={busyId === u.id} onClick={() => unblock(u)}>
                              {busyId === u.id ? <Loader2Icon className="animate-spin" /> : <UndoIcon />} Unblock
                            </Button>
                          ) : (
                            <Button size="sm" variant="outline" onClick={() => setBlocking(u)}>
                              <BanIcon /> Block
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    )
                  })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={!!blocking}
        onOpenChange={(o) => !o && setBlocking(null)}
        title={`Block ${blocking?.name ?? "this user"}?`}
        description="They are signed out on all devices and cannot sign in until unblocked. Their entries are kept."
        confirmLabel="Block"
        onConfirm={() => (blocking ? block(blocking) : Promise.resolve())}
      />
    </main>
  )
}

function Stat({ title, value }: { title: string; value: string | null }) {
  return (
    <Card className="gap-2 py-4">
      <CardHeader className="px-5">
        <CardDescription>{title}</CardDescription>
        <CardTitle className="text-2xl font-semibold tabular-nums">
          {value ?? <Skeleton className="h-8 w-20" />}
        </CardTitle>
      </CardHeader>
    </Card>
  )
}
