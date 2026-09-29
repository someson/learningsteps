// Thin client for the JSON API under /api. Every call returns parsed JSON or
// throws ApiError, which carries field-level messages from FastAPI's 422s.

export type Entry = {
  id: string
  work: string
  struggle: string
  intention: string
  created_at: string
  updated_at: string
}

export type EntryFields = Pick<Entry, "work" | "struggle" | "intention">

export const FIELDS: { key: keyof EntryFields; label: string; question: string }[] = [
  { key: "work", label: "Work", question: "What did you work on today?" },
  { key: "struggle", label: "Struggle", question: "What's one thing you struggled with today?" },
  { key: "intention", label: "Intention", question: "What will you study/work on tomorrow?" },
]

export const MIN_LENGTH = 3
export const MAX_LENGTH = 256

type ValidationItem = { loc: (string | number)[]; msg: string }

export class ApiError extends Error {
  status: number
  fieldErrors: Partial<Record<keyof EntryFields, string>>

  constructor(status: number, message: string, fieldErrors: ApiError["fieldErrors"] = {}) {
    super(message)
    this.status = status
    this.fieldErrors = fieldErrors
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, "Cannot reach the API")
  }

  const data = await res.json().catch(() => null)
  if (res.ok) return data as T

  const detail = data?.detail
  if (Array.isArray(detail)) {
    const fieldErrors: ApiError["fieldErrors"] = {}
    for (const item of detail as ValidationItem[]) {
      const field = item.loc[item.loc.length - 1] as keyof EntryFields
      fieldErrors[field] = item.msg.replace(/^Value error, /, "")
    }
    throw new ApiError(res.status, "Validation failed", fieldErrors)
  }
  throw new ApiError(res.status, typeof detail === "string" ? detail : `Request failed (${res.status})`)
}

export const api = {
  list: () => request<{ entries: Entry[]; count: number }>("GET", "/entries"),
  get: (id: string) => request<Entry>("GET", `/entries/${encodeURIComponent(id)}`),
  create: (fields: EntryFields) =>
    request<{ detail: string; entry: Entry }>("POST", "/entries", fields),
  update: (id: string, changes: Partial<EntryFields>) =>
    request<Entry>("PATCH", `/entries/${encodeURIComponent(id)}`, changes),
  remove: (id: string) =>
    request<{ detail: string; entry_id: string }>("DELETE", `/entries/${encodeURIComponent(id)}`),
  removeAll: () => request<{ detail: string }>("DELETE", "/entries"),
}

// Mirrors the server rules (trimmed, 3–256 chars) so most errors show before a
// round trip; the server stays the authority and its 422s are shown too.
export function validateField(value: string): string | undefined {
  const v = value.trim()
  if (!v) return "Field cannot be empty"
  if (v.length < MIN_LENGTH) return `At least ${MIN_LENGTH} characters`
  if (v.length > MAX_LENGTH) return `At most ${MAX_LENGTH} characters`
  return undefined
}

export function formatDate(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
}
