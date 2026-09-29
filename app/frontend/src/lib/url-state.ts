import { useCallback, useEffect, useState } from "react"

// Table navigation (page, size, sort, search, open entry) lives in the query
// string, so a view can be bookmarked, shared and walked with back/forward.

export type SortKey = "created_at" | "updated_at" | "work" | "struggle" | "intention"
export type SortDir = "asc" | "desc"

export type ViewState = {
  q: string
  page: number
  size: number
  sort: SortKey
  dir: SortDir
  entry: string | null
  // "admin" shows the administration page instead of the journal.
  view: "admin" | null
}

export const PAGE_SIZES = [10, 20, 50, 100]
const SORT_KEYS: SortKey[] = ["created_at", "updated_at", "work", "struggle", "intention"]
const DEFAULTS: ViewState = { q: "", page: 1, size: 10, sort: "created_at", dir: "desc", entry: null, view: null }

function read(): ViewState {
  const p = new URLSearchParams(window.location.search)
  const page = Number(p.get("page"))
  const size = Number(p.get("size"))
  const sort = p.get("sort") as SortKey
  const dir = p.get("dir")
  return {
    q: p.get("q") ?? DEFAULTS.q,
    page: Number.isInteger(page) && page > 0 ? page : DEFAULTS.page,
    size: PAGE_SIZES.includes(size) ? size : DEFAULTS.size,
    sort: SORT_KEYS.includes(sort) ? sort : DEFAULTS.sort,
    dir: dir === "asc" || dir === "desc" ? dir : DEFAULTS.dir,
    entry: p.get("entry"),
    view: p.get("view") === "admin" ? "admin" : null,
  }
}

function write(state: ViewState, push: boolean) {
  const p = new URLSearchParams()
  if (state.q) p.set("q", state.q)
  if (state.page !== DEFAULTS.page) p.set("page", String(state.page))
  if (state.size !== DEFAULTS.size) p.set("size", String(state.size))
  if (state.sort !== DEFAULTS.sort) p.set("sort", state.sort)
  if (state.dir !== DEFAULTS.dir) p.set("dir", state.dir)
  if (state.entry) p.set("entry", state.entry)
  if (state.view) p.set("view", state.view)
  const qs = p.toString()
  const url = `${window.location.pathname}${qs ? `?${qs}` : ""}`
  if (url === `${window.location.pathname}${window.location.search}`) return
  if (push) window.history.pushState(null, "", url)
  else window.history.replaceState(null, "", url)
}

export function useViewState() {
  const [state, setState] = useState<ViewState>(read)

  useEffect(() => {
    const onPop = () => setState(read())
    window.addEventListener("popstate", onPop)
    return () => window.removeEventListener("popstate", onPop)
  }, [])

  // Typing in search replaces the history entry; everything else pushes one.
  const update = useCallback((patch: Partial<ViewState>, opts: { replace?: boolean } = {}) => {
    setState((prev) => {
      const next = { ...prev, ...patch }
      write(next, !opts.replace)
      return next
    })
  }, [])

  return [state, update] as const
}
