import { useEffect, useMemo, useState } from "react"
import { Loader2Icon } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { ApiError, FIELDS, MAX_LENGTH, api, validateField, type Entry, type EntryFields } from "@/lib/api"
import { cn } from "@/lib/utils"

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  // No entry: create. With an entry: edit, sending only the changed fields.
  entry?: Entry | null
  onSaved: (entry: Entry) => void
}

type Errors = Partial<Record<keyof EntryFields, string>>

const EMPTY: EntryFields = { work: "", struggle: "", intention: "" }

export function EntryFormDialog({ open, onOpenChange, entry, onSaved }: Props) {
  const editing = !!entry
  const [values, setValues] = useState<EntryFields>(EMPTY)
  const [errors, setErrors] = useState<Errors>({})
  const [touched, setTouched] = useState<Partial<Record<keyof EntryFields, boolean>>>({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    setValues(entry ? { work: entry.work, struggle: entry.struggle, intention: entry.intention } : EMPTY)
    setErrors({})
    setTouched({})
  }, [open, entry])

  // PATCH is partial: only fields whose trimmed value differs are sent.
  const changes = useMemo(() => {
    if (!entry) return values
    const diff: Partial<EntryFields> = {}
    for (const { key } of FIELDS) {
      if (values[key].trim() !== entry[key]) diff[key] = values[key]
    }
    return diff
  }, [values, entry])
  const hasChanges = Object.keys(changes).length > 0

  const clientErrors = useMemo(() => {
    const out: Errors = {}
    for (const { key } of FIELDS) {
      const e = validateField(values[key])
      if (e) out[key] = e
    }
    return out
  }, [values])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setTouched({ work: true, struggle: true, intention: true })
    if (Object.keys(clientErrors).length) return
    if (editing && !hasChanges) return

    setSaving(true)
    try {
      const saved = editing ? await api.update(entry!.id, changes) : (await api.create(values)).entry
      toast.success(editing ? "Entry updated" : "Entry created")
      onSaved(saved)
      onOpenChange(false)
    } catch (err) {
      if (err instanceof ApiError && Object.keys(err.fieldErrors).length) {
        setErrors(err.fieldErrors)
      } else {
        toast.error(err instanceof Error ? err.message : "Something went wrong")
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !saving && onOpenChange(o)}>
      <DialogContent className="sm:max-w-xl">
        <form onSubmit={submit} className="grid gap-6" noValidate>
          <DialogHeader>
            <DialogTitle>{editing ? "Edit entry" : "New entry"}</DialogTitle>
            <DialogDescription>
              {editing
                ? "Only the fields you change are sent; the others are kept."
                : "Each field is required, 3–256 characters. Leading and trailing spaces are trimmed."}
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-5">
            {FIELDS.map(({ key, label, question }, i) => {
              const error = errors[key] ?? (touched[key] ? clientErrors[key] : undefined)
              const length = values[key].trim().length
              const changed = editing && key in changes
              return (
                <div key={key} className="grid gap-2">
                  <div className="flex items-baseline justify-between gap-2">
                    <Label htmlFor={`field-${key}`}>
                      {label}
                      {changed && (
                        <span className="text-muted-foreground text-xs font-normal">· modified</span>
                      )}
                    </Label>
                    <span
                      className={cn(
                        "text-xs tabular-nums",
                        length > MAX_LENGTH ? "text-foreground font-semibold" : "text-muted-foreground"
                      )}
                    >
                      {length}/{MAX_LENGTH}
                    </span>
                  </div>
                  <Textarea
                    id={`field-${key}`}
                    autoFocus={i === 0}
                    placeholder={question}
                    value={values[key]}
                    aria-invalid={!!error}
                    aria-describedby={error ? `error-${key}` : undefined}
                    className="max-h-40 min-h-20 resize-none"
                    onChange={(e) => {
                      setValues((v) => ({ ...v, [key]: e.target.value }))
                      setErrors((er) => ({ ...er, [key]: undefined }))
                    }}
                    onBlur={() => setTouched((t) => ({ ...t, [key]: true }))}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) e.currentTarget.form?.requestSubmit()
                    }}
                  />
                  {error ? (
                    <p id={`error-${key}`} className="text-foreground text-xs font-medium">
                      {error}
                    </p>
                  ) : (
                    <p className="text-muted-foreground text-xs">{question}</p>
                  )}
                </div>
              )
            })}
          </div>

          <DialogFooter className="items-center">
            <span className="text-muted-foreground mr-auto hidden text-xs sm:inline">
              <kbd className="font-sans">Ctrl</kbd> + <kbd className="font-sans">Enter</kbd> to save
            </span>
            <Button type="button" variant="outline" disabled={saving} onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving || (editing && !hasChanges)}>
              {saving && <Loader2Icon className="animate-spin" />}
              {editing ? (hasChanges ? "Save changes" : "No changes") : "Create entry"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
