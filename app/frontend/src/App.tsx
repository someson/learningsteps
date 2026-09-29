import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  ArrowDownIcon,
  ArrowUpDownIcon,
  ArrowUpIcon,
  BookOpenIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ChevronsLeftIcon,
  ChevronsRightIcon,
  EyeIcon,
  FileTextIcon,
  MoonIcon,
  MoreHorizontalIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  SunIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/confirm-dialog"
import { EntryDetailsDialog } from "@/components/entry-details-dialog"
import { EntryFormDialog } from "@/components/entry-form-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Toaster } from "@/components/ui/sonner"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { ApiError, FIELDS, api, formatDate, type Entry } from "@/lib/api"
import { useTheme } from "@/lib/theme"
import { PAGE_SIZES, useViewState, type SortKey } from "@/lib/url-state"
import { cn } from "@/lib/utils"

const COLUMNS: { key: SortKey; label: string; className?: string }[] = [
  ...FIELDS.map(({ key, label }) => ({ key, label, className: "min-w-48" })),
  { key: "created_at", label: "Created", className: "w-40" },
  { key: "updated_at", label: "Updated", className: "w-40" },
]

export default function App() {
  const { theme, toggle } = useTheme()
  const [view, setView] = useViewState()

  const [entries, setEntries] = useState<Entry[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Entry | null>(null)
  const [deleting, setDeleting] = useState<Entry | null>(null)
  const [deleteAllOpen, setDeleteAllOpen] = useState(false)
  const [detailsVersion, setDetailsVersion] = useState(0)
  const searchRef = useRef<HTMLInputElement>(null)

  // GET /api/entries
  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true)
    try {
      const { entries } = await api.list()
      setEntries(entries)
      setLoadError(null)
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not load entries"
      setLoadError(message)
      if (quiet) toast.error(message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // "/" focuses search, "n" opens the create form.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (e.target instanceof HTMLElement && e.target.closest("input, textarea, [role=dialog]")) return
      if (e.key === "/") {
        e.preventDefault()
        searchRef.current?.focus()
      } else if (e.key === "n") {
        e.preventDefault()
        openCreate()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  const filtered = useMemo(() => {
    const q = view.q.trim().toLowerCase()
    const list = q
      ? entries.filter((e) => FIELDS.some(({ key }) => e[key].toLowerCase().includes(q)) || e.id.startsWith(q))
      : entries.slice()
    const sign = view.dir === "asc" ? 1 : -1
    list.sort((a, b) => {
      const av = a[view.sort]
      const bv = b[view.sort]
      const cmp = view.sort.endsWith("_at")
        ? new Date(av).getTime() - new Date(bv).getTime()
        : av.localeCompare(bv, undefined, { sensitivity: "base" })
      return cmp * sign || a.id.localeCompare(b.id)
    })
    return list
  }, [entries, view.q, view.sort, view.dir])

  const pageCount = Math.max(1, Math.ceil(filtered.length / view.size))
  const page = Math.min(view.page, pageCount)
  const pageRows = filtered.slice((page - 1) * view.size, page * view.size)
  const from = filtered.length ? (page - 1) * view.size + 1 : 0
  const to = Math.min(page * view.size, filtered.length)

  const position = useMemo(() => {
    if (!view.entry) return undefined
    const index = filtered.findIndex((e) => e.id === view.entry)
    return {
      index,
      total: filtered.length,
      prevId: index > 0 ? filtered[index - 1].id : undefined,
      nextId: index >= 0 && index < filtered.length - 1 ? filtered[index + 1].id : undefined,
    }
  }, [filtered, view.entry])

  const latest = useMemo(
    () =>
      entries.reduce<Entry | null>(
        (acc, e) => (!acc || new Date(e.created_at) > new Date(acc.created_at) ? e : acc),
        null
      ),
    [entries]
  )

  function openCreate() {
    setEditing(null)
    setFormOpen(true)
  }

  function openEdit(entry: Entry) {
    setEditing(entry)
    setFormOpen(true)
  }

  const openEntry = useCallback(
    (id: string | null) => {
      // Keep the table on the page that holds the entry being viewed.
      if (id) {
        const index = filtered.findIndex((e) => e.id === id)
        const target = index >= 0 ? Math.floor(index / view.size) + 1 : view.page
        setView({ entry: id, page: target }, { replace: !!view.entry })
      } else {
        setView({ entry: null })
      }
    },
    [filtered, view.size, view.page, view.entry, setView]
  )

  const dropMissing = useCallback((id: string) => {
    setEntries((list) => list.filter((e) => e.id !== id))
  }, [])

  function onSaved(saved: Entry) {
    setEntries((list) => {
      const i = list.findIndex((e) => e.id === saved.id)
      if (i === -1) return [saved, ...list]
      const next = list.slice()
      next[i] = saved
      return next
    })
    setDetailsVersion((v) => v + 1)
    if (!editing) {
      // Show the new entry: newest first, first page, no filter hiding it.
      setView({ q: "", sort: "created_at", dir: "desc", page: 1 })
    }
  }

  // DELETE /api/entries/{id}
  async function deleteOne(entry: Entry) {
    try {
      await api.remove(entry.id)
      toast.success("Entry deleted")
    } catch (err) {
      // 404: someone else already deleted it — the goal is reached.
      if (!(err instanceof ApiError && err.status === 404)) {
        toast.error(err instanceof Error ? err.message : "Could not delete the entry")
        throw err
      }
      toast.info("Entry was already deleted")
    }
    dropMissing(entry.id)
    if (view.entry === entry.id) setView({ entry: null }, { replace: true })
  }

  // DELETE /api/entries
  async function deleteAll() {
    try {
      await api.removeAll()
      setEntries([])
      setView({ page: 1, entry: null })
      toast.success("All entries deleted")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete entries")
      throw err
    }
  }

  function toggleSort(key: SortKey) {
    if (view.sort === key) setView({ dir: view.dir === "asc" ? "desc" : "asc", page: 1 })
    else setView({ sort: key, dir: key.endsWith("_at") ? "desc" : "asc", page: 1 })
  }

  return (
    <TooltipProvider>
      <div className="flex min-h-svh flex-col">
        <header className="bg-background/80 sticky top-0 z-40 border-b backdrop-blur">
          <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4 sm:px-6">
            <div className="bg-primary text-primary-foreground grid size-8 place-items-center rounded-lg">
              <svg viewBox="0 0 32 32" className="size-5" fill="none" aria-hidden>
                <path
                  d="M6 24h5v-5h5v-5h5V9h5"
                  stroke="currentColor"
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
            <div className="leading-tight">
              <div className="font-semibold tracking-tight">LearningSteps</div>
              <div className="text-muted-foreground hidden text-xs sm:block">Learning journal</div>
            </div>
            <nav className="ml-auto flex items-center gap-1">
              <Button variant="ghost" size="sm" asChild>
                <a href="/docs" target="_blank" rel="noreferrer">
                  <BookOpenIcon /> <span className="hidden sm:inline">API docs</span>
                </a>
              </Button>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">
                    {theme === "dark" ? <SunIcon /> : <MoonIcon />}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{theme === "dark" ? "Light mode" : "Dark mode"}</TooltipContent>
              </Tooltip>
            </nav>
          </div>
        </header>

        <main className="mx-auto grid w-full max-w-7xl flex-1 grid-cols-[minmax(0,1fr)] content-start gap-6 px-4 py-8 sm:px-6">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">Journal entries</h1>
              <p className="text-muted-foreground text-sm">
                What you worked on, what you struggled with, and what comes next.
              </p>
            </div>
            <Button onClick={openCreate}>
              <PlusIcon /> New entry
            </Button>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <Stat title="Total entries" value={loading ? null : String(entries.length)} />
            <Stat
              title={view.q ? "Matching search" : "Shown"}
              value={loading ? null : String(filtered.length)}
            />
            <Stat title="Latest entry" value={loading ? null : latest ? formatDate(latest.created_at) : "—"} />
          </div>

          <Card className="gap-0 py-0">
            <CardHeader className="border-b py-4 [.border-b]:pb-4">
              <CardTitle className="sr-only">Entries</CardTitle>
              <CardDescription className="sr-only">Search, sort and page through entries</CardDescription>
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative w-full sm:w-80">
                  <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
                  <Input
                    ref={searchRef}
                    value={view.q}
                    onChange={(e) => setView({ q: e.target.value, page: 1 }, { replace: true })}
                    placeholder="Search entries…"
                    className="pr-8 pl-8"
                    aria-label="Search entries"
                  />
                  {view.q ? (
                    <button
                      className="text-muted-foreground hover:text-foreground absolute top-1/2 right-2 -translate-y-1/2"
                      onClick={() => setView({ q: "", page: 1 })}
                      aria-label="Clear search"
                    >
                      <XIcon className="size-4" />
                    </button>
                  ) : (
                    <kbd className="text-muted-foreground pointer-events-none absolute top-1/2 right-2 hidden -translate-y-1/2 rounded border px-1.5 font-mono text-[10px] sm:block">
                      /
                    </kbd>
                  )}
                </div>
              </div>
              <CardAction className="flex gap-2">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="outline" size="icon" onClick={() => load(true)} aria-label="Refresh">
                      <RefreshCwIcon className={cn(loading && "animate-spin")} />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Refresh</TooltipContent>
                </Tooltip>
                <Button
                  variant="outline"
                  disabled={!entries.length}
                  onClick={() => setDeleteAllOpen(true)}
                >
                  <Trash2Icon /> <span className="hidden sm:inline">Delete all</span>
                </Button>
              </CardAction>
            </CardHeader>

            <CardContent className="px-0">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    {COLUMNS.map((col) => (
                      <TableHead key={col.key} className={cn("first:pl-6", col.className)}>
                        <button
                          className="hover:text-foreground -ml-2 inline-flex items-center gap-1.5 rounded-md px-2 py-1"
                          onClick={() => toggleSort(col.key)}
                          aria-label={`Sort by ${col.label}`}
                        >
                          {col.label}
                          {view.sort === col.key ? (
                            view.dir === "asc" ? (
                              <ArrowUpIcon className="text-foreground size-3.5" />
                            ) : (
                              <ArrowDownIcon className="text-foreground size-3.5" />
                            )
                          ) : (
                            <ArrowUpDownIcon className="size-3.5 opacity-40" />
                          )}
                        </button>
                      </TableHead>
                    ))}
                    <TableHead className="w-32 pr-6 text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {loading ? (
                    Array.from({ length: 5 }, (_, i) => (
                      <TableRow key={i}>
                        {COLUMNS.map((c) => (
                          <TableCell key={c.key} className="first:pl-6">
                            <Skeleton className="h-4 w-full max-w-40" />
                          </TableCell>
                        ))}
                        <TableCell className="pr-6">
                          <Skeleton className="ml-auto h-8 w-24" />
                        </TableCell>
                      </TableRow>
                    ))
                  ) : loadError ? (
                    <EmptyRow>
                      <p className="font-medium">Could not load entries</p>
                      <p className="text-muted-foreground text-sm">{loadError}</p>
                      <Button variant="outline" size="sm" className="mt-3" onClick={() => load()}>
                        <RefreshCwIcon /> Try again
                      </Button>
                    </EmptyRow>
                  ) : pageRows.length === 0 ? (
                    <EmptyRow>
                      <FileTextIcon className="text-muted-foreground mb-2 size-8" />
                      {view.q ? (
                        <>
                          <p className="font-medium">No entries match “{view.q}”</p>
                          <Button variant="outline" size="sm" className="mt-3" onClick={() => setView({ q: "" })}>
                            Clear search
                          </Button>
                        </>
                      ) : (
                        <>
                          <p className="font-medium">No entries yet</p>
                          <p className="text-muted-foreground text-sm">Write down what you learned today.</p>
                          <Button size="sm" className="mt-3" onClick={openCreate}>
                            <PlusIcon /> New entry
                          </Button>
                        </>
                      )}
                    </EmptyRow>
                  ) : (
                    pageRows.map((entry) => (
                      <TableRow
                        key={entry.id}
                        data-state={view.entry === entry.id ? "selected" : undefined}
                        className="cursor-pointer"
                        onClick={() => openEntry(entry.id)}
                      >
                        {FIELDS.map(({ key }) => (
                          <TableCell key={key} className="max-w-72 first:pl-6">
                            <span className="line-clamp-2 break-words" title={entry[key]}>
                              <Highlight text={entry[key]} query={view.q} />
                            </span>
                          </TableCell>
                        ))}
                        <TableCell className="text-muted-foreground whitespace-nowrap">
                          {formatDate(entry.created_at)}
                        </TableCell>
                        <TableCell className="text-muted-foreground whitespace-nowrap">
                          {entry.updated_at !== entry.created_at ? (
                            formatDate(entry.updated_at)
                          ) : (
                            <Badge variant="outline" className="text-muted-foreground font-normal">
                              never
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell className="pr-6" onClick={(e) => e.stopPropagation()}>
                          <RowActions
                            onView={() => openEntry(entry.id)}
                            onEdit={() => openEdit(entry)}
                            onDelete={() => setDeleting(entry)}
                          />
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>

            <div className="flex flex-col-reverse items-center justify-between gap-3 border-t px-6 py-3 sm:flex-row">
              <p className="text-muted-foreground text-sm tabular-nums">
                {filtered.length ? `${from}–${to} of ${filtered.length}` : "0 entries"}
                {view.q && entries.length !== filtered.length && ` (filtered from ${entries.length})`}
              </p>
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground hidden text-sm sm:inline">Rows</span>
                  <Select value={String(view.size)} onValueChange={(v) => setView({ size: Number(v), page: 1 })}>
                    <SelectTrigger size="sm" className="w-18" aria-label="Rows per page">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PAGE_SIZES.map((s) => (
                        <SelectItem key={s} value={String(s)}>
                          {s}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <span className="text-sm font-medium tabular-nums">
                  Page {page} of {pageCount}
                </span>
                <div className="flex gap-1">
                  <PagerButton label="First page" disabled={page <= 1} onClick={() => setView({ page: 1 })}>
                    <ChevronsLeftIcon />
                  </PagerButton>
                  <PagerButton label="Previous page" disabled={page <= 1} onClick={() => setView({ page: page - 1 })}>
                    <ChevronLeftIcon />
                  </PagerButton>
                  <PagerButton
                    label="Next page"
                    disabled={page >= pageCount}
                    onClick={() => setView({ page: page + 1 })}
                  >
                    <ChevronRightIcon />
                  </PagerButton>
                  <PagerButton
                    label="Last page"
                    disabled={page >= pageCount}
                    onClick={() => setView({ page: pageCount })}
                  >
                    <ChevronsRightIcon />
                  </PagerButton>
                </div>
              </div>
            </div>
          </Card>
        </main>

        <footer className="text-muted-foreground mx-auto w-full max-w-7xl px-4 pb-8 text-xs sm:px-6">
          JSON API under <code className="font-mono">/api</code> · interactive reference at{" "}
          <a href="/docs" className="hover:text-foreground underline underline-offset-4">
            /docs
          </a>
        </footer>
      </div>

      {/* Hidden, not closed, while editing or deleting: it comes back afterwards. */}
      <EntryDetailsDialog
        entryId={view.entry}
        hidden={formOpen || !!deleting}
        position={position}
        version={detailsVersion}
        onNavigate={openEntry}
        onMissing={dropMissing}
        onEdit={openEdit}
        onDelete={setDeleting}
      />

      <EntryFormDialog open={formOpen} onOpenChange={setFormOpen} entry={editing} onSaved={onSaved} />

      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title="Delete this entry?"
        description={
          <>
            <span className="text-foreground line-clamp-2 font-medium">“{deleting?.work}”</span>
            <span className="mt-2 block">This permanently removes the entry. It cannot be undone.</span>
          </>
        }
        confirmLabel="Delete"
        onConfirm={() => (deleting ? deleteOne(deleting) : Promise.resolve())}
      />

      <ConfirmDialog
        open={deleteAllOpen}
        onOpenChange={setDeleteAllOpen}
        title={`Delete all ${entries.length} entries?`}
        description="Every entry in the journal is permanently removed, not only the ones on this page or matching the search. This cannot be undone."
        confirmLabel="Delete all"
        confirmWord="delete"
        onConfirm={deleteAll}
      />

      <Toaster theme={theme} position="bottom-right" />
    </TooltipProvider>
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

function EmptyRow({ children }: { children: React.ReactNode }) {
  return (
    <TableRow className="hover:bg-transparent">
      <TableCell colSpan={COLUMNS.length + 1} className="h-64">
        <div className="flex flex-col items-center justify-center text-center">{children}</div>
      </TableCell>
    </TableRow>
  )
}

function PagerButton({
  label,
  children,
  ...props
}: React.ComponentProps<typeof Button> & { label: string }) {
  return (
    <Button variant="outline" size="icon-sm" aria-label={label} {...props}>
      {children}
    </Button>
  )
}

function RowActions({ onView, onEdit, onDelete }: { onView: () => void; onEdit: () => void; onDelete: () => void }) {
  return (
    <div className="flex justify-end gap-1">
      <div className="hidden gap-1 md:flex">
        <IconAction label="View" onClick={onView}>
          <EyeIcon />
        </IconAction>
        <IconAction label="Edit" onClick={onEdit}>
          <PencilIcon />
        </IconAction>
        <IconAction label="Delete" onClick={onDelete}>
          <Trash2Icon />
        </IconAction>
      </div>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-sm" className="md:hidden" aria-label="Actions">
            <MoreHorizontalIcon />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={onView}>
            <EyeIcon /> View
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={onEdit}>
            <PencilIcon /> Edit
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" onSelect={onDelete}>
            <Trash2Icon /> Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

function IconAction({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={label} onClick={onClick}>
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}

function Highlight({ text, query }: { text: string; query: string }) {
  const q = query.trim()
  if (!q) return <>{text}</>
  const i = text.toLowerCase().indexOf(q.toLowerCase())
  if (i === -1) return <>{text}</>
  return (
    <>
      {text.slice(0, i)}
      <mark className="bg-foreground text-background rounded-sm px-0.5">{text.slice(i, i + q.length)}</mark>
      {text.slice(i + q.length)}
    </>
  )
}
