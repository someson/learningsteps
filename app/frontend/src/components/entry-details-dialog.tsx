import { useEffect, useState } from "react"
import { ChevronLeftIcon, ChevronRightIcon, CopyIcon, PencilIcon, Trash2Icon } from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { ApiError, FIELDS, api, formatDate, type Entry } from "@/lib/api"

type Props = {
  entryId: string | null
  // Position in the current (filtered, sorted) list, for prev/next.
  position?: { index: number; total: number; prevId?: string; nextId?: string }
  onNavigate: (id: string | null) => void
  onEdit: (entry: Entry) => void
  onDelete: (entry: Entry) => void
  onMissing: (id: string) => void
  // Bumped by the parent after an edit so the dialog refetches.
  version: number
  hidden?: boolean
}

export function EntryDetailsDialog({
  entryId,
  position,
  onNavigate,
  onEdit,
  onDelete,
  onMissing,
  version,
  hidden = false,
}: Props) {
  const [entry, setEntry] = useState<Entry | null>(null)
  const [loading, setLoading] = useState(false)

  // Always GET /api/entries/{id}: the details view shows the server's current
  // state, not the possibly stale row from the list.
  useEffect(() => {
    if (!entryId) return
    let cancelled = false
    setLoading(true)
    api
      .get(entryId)
      .then((e) => !cancelled && setEntry(e))
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 404) {
          toast.error("Entry not found", { description: "It may have been deleted." })
          onMissing(entryId)
        } else {
          toast.error(err instanceof Error ? err.message : "Could not load the entry")
        }
        onNavigate(null)
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [entryId, version, onNavigate, onMissing])

  useEffect(() => {
    if (!entryId || hidden) return
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && e.target.closest("input, textarea")) return
      if (e.key === "ArrowLeft" && position?.prevId) onNavigate(position.prevId)
      if (e.key === "ArrowRight" && position?.nextId) onNavigate(position.nextId)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [entryId, hidden, position, onNavigate])

  const shown = entry && entry.id === entryId ? entry : null

  return (
    <Dialog open={!!entryId && !hidden} onOpenChange={(o) => !o && onNavigate(null)}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <DialogTitle>Entry</DialogTitle>
            {position && position.index >= 0 && (
              <Badge variant="secondary" className="tabular-nums">
                {position.index + 1} of {position.total}
              </Badge>
            )}
          </div>
          <DialogDescription asChild>
            <div className="flex items-center gap-1 font-mono text-xs">
              <span className="truncate">{entryId}</span>
              <Button
                variant="ghost"
                size="icon-sm"
                className="size-6"
                aria-label="Copy ID"
                onClick={() => {
                  if (!entryId) return
                  navigator.clipboard?.writeText(entryId).then(
                    () => toast.success("ID copied"),
                    () => toast.error("Could not copy")
                  )
                }}
              >
                <CopyIcon className="size-3" />
              </Button>
            </div>
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-5">
          {FIELDS.map(({ key, label, question }) => (
            <section key={key} className="grid gap-1.5">
              <h3 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">{label}</h3>
              {shown && !loading ? (
                <p className="text-sm leading-relaxed break-words whitespace-pre-wrap">{shown[key]}</p>
              ) : (
                <Skeleton className="h-5 w-3/4" />
              )}
              <p className="text-muted-foreground/70 text-xs">{question}</p>
            </section>
          ))}

          <dl className="grid grid-cols-2 gap-4 border-t pt-4 text-sm">
            <div className="grid gap-1">
              <dt className="text-muted-foreground text-xs">Created</dt>
              <dd>{shown ? formatDate(shown.created_at) : <Skeleton className="h-5 w-32" />}</dd>
            </div>
            <div className="grid gap-1">
              <dt className="text-muted-foreground text-xs">Updated</dt>
              <dd>{shown ? formatDate(shown.updated_at) : <Skeleton className="h-5 w-32" />}</dd>
            </div>
          </dl>
        </div>

        <DialogFooter className="sm:justify-between">
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="icon"
              aria-label="Previous entry"
              disabled={!position?.prevId}
              onClick={() => position?.prevId && onNavigate(position.prevId)}
            >
              <ChevronLeftIcon />
            </Button>
            <Button
              variant="outline"
              size="icon"
              aria-label="Next entry"
              disabled={!position?.nextId}
              onClick={() => position?.nextId && onNavigate(position.nextId)}
            >
              <ChevronRightIcon />
            </Button>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" disabled={!shown} onClick={() => shown && onDelete(shown)}>
              <Trash2Icon /> Delete
            </Button>
            <Button disabled={!shown} onClick={() => shown && onEdit(shown)}>
              <PencilIcon /> Edit
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
