import { useEffect, useState } from "react"
import { Loader2Icon } from "lucide-react"

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: React.ReactNode
  confirmLabel: string
  // When set, the user must type this word before the action is enabled.
  confirmWord?: string
  onConfirm: () => Promise<void>
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  confirmWord,
  onConfirm,
}: Props) {
  const [busy, setBusy] = useState(false)
  const [typed, setTyped] = useState("")

  useEffect(() => {
    if (open) setTyped("")
  }, [open])

  const armed = !confirmWord || typed.trim().toLowerCase() === confirmWord.toLowerCase()

  async function run() {
    setBusy(true)
    try {
      await onConfirm()
      onOpenChange(false)
    } catch {
      // The caller reports the error; the dialog stays open to retry.
    } finally {
      setBusy(false)
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription asChild>
            <div>{description}</div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        {confirmWord && (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              if (armed && !busy) run()
            }}
          >
            <label className="text-muted-foreground mb-2 block text-sm">
              Type <span className="text-foreground font-mono font-semibold">{confirmWord}</span> to confirm
            </label>
            <Input autoFocus value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
          </form>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
          {/* Not AlertDialogAction: that closes the dialog before the request finishes. */}
          <Button variant="destructive" disabled={!armed || busy} onClick={run}>
            {busy && <Loader2Icon className="animate-spin" />}
            {confirmLabel}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
