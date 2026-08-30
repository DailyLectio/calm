import * as React from "react"
import { addPropertyControls, ControlType } from "framer"

type Entry = {
    date: string; quote: string; quoteCitation: string; synthesis: string
    tags: string[]; refs: string[]; feast: string; cycle: string
    weekdayCycle: string; path: string; sha256: string
}
type Index = { schemaVersion: number; revision: string; count: number; latestDate: string | null; entries: Entry[] }
type Props = {
    indexUrl?: string; showStatus?: boolean; placeholder?: string
    maxResults?: number; showFilters?: boolean; smartSearch?: boolean
    style?: React.CSSProperties
}
const DEFAULT_INDEX = "https://www.dailylectio.org/past_reflections/search-v1.json"
const LEGACY_KEY = "dlx_devotions_archive_v1"
const CACHE_PREFIX = "lectiolinks.archive.search.v1:"
const HASH = /^[0-9a-f]{64}$/
const surface = "var(--token-c052246b-7349-47f4-98d2-d23dbe774dd9, #fefefe)"
const muted = "var(--token-976d8519-4529-425a-83b6-fc169b0e21bc, #616161)"
const control: React.CSSProperties = { font: "inherit", color: "inherit", background: surface,
    border: "1px solid #ccc", borderRadius: 10, minHeight: 44, padding: "8px 12px", boxSizing: "border-box", maxWidth: "100%" }
const button: React.CSSProperties = { ...control, cursor: "pointer" }

function validDate(value: unknown): value is string {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
    const parsed = new Date(value + "T12:00:00Z")
    return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}
function todayEastern() {
    const parts = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date())
    const get = (type: string) => parts.find(p => p.type === type)?.value
    return `${get("year")}-${get("month")}-${get("day")}`
}
function cycles(day: string) {
    const parsed = new Date(day + "T12:00:00Z")
    const year = parsed.getUTCFullYear()
    const advent = new Date(Date.UTC(year, 10, 27, 12))
    advent.setUTCDate(27 + (7 - advent.getUTCDay()) % 7)
    const liturgicalYear = year + Number(parsed >= advent)
    return { cycle: ["Year A", "Year B", "Year C"][((liturgicalYear - 2020) % 3 + 3) % 3],
        weekdayCycle: liturgicalYear % 2 ? "Cycle I" : "Cycle II" }
}
function validateIndex(value: unknown): Index {
    const data = value as Index
    if (!data || data.schemaVersion !== 1 || !HASH.test(data.revision) || !Array.isArray(data.entries)
        || data.count !== data.entries.length || data.entries.length > 50000) throw new Error("The archive index format is invalid.")
    const seen = new Set<string>()
    for (const row of data.entries) {
        if (!row || !validDate(row.date) || seen.has(row.date) || !HASH.test(row.sha256)
            || row.path !== `/past_reflections/${row.date.slice(0, 4)}/${row.date.slice(5, 7)}/${row.date}.json`
            || ![row.quote, row.quoteCitation, row.synthesis, row.feast, row.cycle, row.weekdayCycle].every(v => typeof v === "string")
            || !Array.isArray(row.tags) || !Array.isArray(row.refs) || ![...row.tags, ...row.refs].every(v => typeof v === "string")) {
            throw new Error("An archive record is invalid. The last verified copy has been retained.")
        }
        seen.add(row.date)
    }
    const entries = data.entries.map(row => ({ ...row, ...cycles(row.date) })).sort((a, b) => b.date.localeCompare(a.date))
    if (data.latestDate !== (entries[0]?.date ?? null)) throw new Error("The archive date range is inconsistent.")
    return { ...data, entries }
}
function normalize(text: string) {
    return text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim()
}
function nearWord(a: string, b: string) {
    // At most one insertion, deletion or replacement; no remote search dependency.
    if (a.length < 5 || Math.abs(a.length - b.length) > 1) return false
    let i = 0, j = 0, edits = 0
    while (i < a.length && j < b.length) {
        if (a[i] === b[j]) { i++; j++; continue }
        if (++edits > 1) return false
        if (a.length >= b.length) i++
        if (a.length <= b.length) j++
    }
    return edits + (a.length - i) + (b.length - j) <= 1
}
function searchText(row: Entry) {
    return normalize([row.date, new Date(row.date + "T12:00:00Z").toLocaleDateString("en-US", { timeZone: "UTC", month: "long", day: "numeric", year: "numeric" }),
        row.quote, row.quoteCitation, row.synthesis, row.feast, row.cycle, row.weekdayCycle, ...row.tags, ...row.refs].join(" "))
}
function matches(text: string, query: string, smart: boolean) {
    if (validDate(query.trim())) return text.startsWith(normalize(query.trim()) + " ")
    const tokens = normalize(query).split(" ").filter(Boolean).slice(0, 24)
    const words = text.split(" ")
    return tokens.every(token => text.includes(token) || (smart && words.some(word => nearWord(token, word))))
}
function exportJSON(value: unknown, name: string) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }))
    const link = document.createElement("a")
    link.href = url; link.download = name; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
}
async function getIndex(url: string, signal: AbortSignal) {
    const response = await fetch(url, { cache: "no-store", signal })
    if (!response.ok) throw new Error(`Archive server returned HTTP ${response.status}.`)
    return validateIndex(await response.json())
}
function Reflection({ entry, archiveBase }: { entry: Entry; archiveBase: string }) {
    const [open, setOpen] = React.useState(false)
    const [record, setRecord] = React.useState<Record<string, unknown> | null>(null)
    const [error, setError] = React.useState("")
    const [attempt, retry] = React.useState(0)
    const id = React.useId()
    React.useEffect(() => {
        if (!open) return
        const controller = new AbortController()
        const timeout = setTimeout(() => controller.abort(), 15000)
        let active = true
        setRecord(null); setError("")
        ;(async () => {
            try {
                const url = new URL(entry.path.replace(/^\/past_reflections\//, ""), archiveBase)
                url.searchParams.set("v", entry.sha256)
                const response = await fetch(url.href, { cache: "no-store", signal: controller.signal })
                if (!response.ok) throw new Error(`Reflection returned HTTP ${response.status}.`)
                const raw = await response.text()
                const bytes = new TextEncoder().encode(raw.replace(/\r\n/g, "\n"))
                const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), b => b.toString(16).padStart(2, "0")).join("")
                if (hash !== entry.sha256) throw new Error("This reflection has changed. Refresh the archive to load the latest reviewed version.")
                const data = JSON.parse(raw)
                if (!data || Array.isArray(data) || data.date !== entry.date) throw new Error("The reflection date does not match the archive.")
                if (active) setRecord(data)
            } catch (e) {
                if (active) setError(e instanceof Error && e.name !== "AbortError" ? e.message : "The reflection request timed out. Please retry.")
            } finally { clearTimeout(timeout) }
        })()
        return () => { active = false; clearTimeout(timeout); controller.abort() }
    }, [open, entry.sha256, entry.path, entry.date, archiveBase, attempt])
    const sections = [["firstReading", "First reading"], ["secondReading", "Second reading"], ["psalmSummary", "Psalm"],
        ["gospelSummary", "Gospel"], ["saintReflection", "Saint"], ["theologicalSynthesis", "Reflection"],
        ["dailyPrayer", "Prayer"], ["exegesis", "Exegesis"]]
    return <>
        <button type="button" style={button} aria-expanded={open} aria-controls={id} onClick={() => setOpen(v => !v)}>
            {open ? "Close reflection" : "Read full reflection"}
        </button>
        {open && <div id={id} aria-live="polite">
            {!record && !error && <p role="status">Loading reflection…</p>}
            {error && <div role="alert"><p>{error}</p><button type="button" style={button} onClick={() => retry(v => v + 1)}>Retry reflection</button></div>}
            {record && sections.map(([key, title]) => typeof record[key] === "string" && (record[key] as string).trim() ?
                <section key={key}><h3 style={{ fontSize: 20, margin: "24px 0 8px" }}>{title}</h3><p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{record[key] as string}</p></section> : null)}
            {record && <p><button type="button" style={button} onClick={() => exportJSON(record, `reflection-${entry.date}.json`)}>Download this reflection</button></p>}
        </div>}
    </>
}

/**
 * @framerSupportedLayoutWidth any
 * @framerSupportedLayoutHeight auto
 * @framerIntrinsicWidth 848
 * @framerIntrinsicHeight 600
 */
export default function DevotionsArchive(props: Props) {
    const { indexUrl = DEFAULT_INDEX, showStatus = true, placeholder = "Search dates, quotes, summaries, tags, references…",
        maxResults = 25, showFilters = true, smartSearch = true, style } = props
    const [data, setData] = React.useState<Index | null>(null)
    const [loading, setLoading] = React.useState(true)
    const [error, setError] = React.useState("")
    const [verified, setVerified] = React.useState(false)
    const [checkedAt, setCheckedAt] = React.useState("")
    const [request, refresh] = React.useState(0)
    const [query, setQuery] = React.useState("")
    const [cycle, setCycle] = React.useState("")
    const [weekday, setWeekday] = React.useState("")
    const [tag, setTag] = React.useState("")
    const [start, setStart] = React.useState("")
    const [end, setEnd] = React.useState("")
    const [today, setToday] = React.useState("")
    const [legacy, setLegacy] = React.useState<unknown[] | null>(null)
    const pageSize = Math.max(1, Math.min(50, Number(maxResults) || 25))
    const [limit, setLimit] = React.useState(pageSize)
    const archiveBase = React.useMemo(() => { try { return new URL(".", indexUrl).href } catch { return "" } }, [indexUrl])
    const lastUrl = React.useRef("")
    const id = React.useId()
    React.useEffect(() => {
        const tick = () => setToday(todayEastern())
        tick()
        const interval = setInterval(tick, 60000)
        try { const old = JSON.parse(localStorage.getItem(LEGACY_KEY) || "null"); if (Array.isArray(old) && old.length) setLegacy(old) } catch { /* Personal data is never altered. */ }
        return () => clearInterval(interval)
    }, [])
    React.useEffect(() => {
        const controller = new AbortController()
        let active = true
        setLoading(true); setError(""); setVerified(false)
        if (lastUrl.current !== indexUrl) {
            setData(null); setCheckedAt(""); lastUrl.current = indexUrl
            try { const cached = localStorage.getItem(CACHE_PREFIX + indexUrl); if (cached) setData(validateIndex(JSON.parse(cached))) } catch { /* Invalid/unavailable cache is not authoritative. */ }
        }
        const timer = setTimeout(() => controller.abort(), 15000)
        getIndex(indexUrl, controller.signal).then(fresh => {
            if (!active) return
            setData(fresh); setVerified(true)
            setCheckedAt(new Date().toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" }))
            try { localStorage.setItem(CACHE_PREFIX + indexUrl, JSON.stringify(fresh)) } catch { /* Storage denial/quota must not break live data. */ }
        }).catch(e => {
            if (active) setError(e instanceof Error && e.name !== "AbortError" ? e.message : "The archive request timed out.")
        }).finally(() => { clearTimeout(timer); if (active) setLoading(false) })
        return () => { active = false; clearTimeout(timer); controller.abort() }
    }, [indexUrl, request])
    React.useEffect(() => { setLimit(pageSize) }, [query, cycle, weekday, tag, start, end, pageSize])
    const searchable = React.useMemo(() => (data?.entries ?? []).map(entry => ({ entry, text: searchText(entry) })), [data])
    const tags = React.useMemo(() => [...new Set((data?.entries ?? []).flatMap(r => r.tags))].sort(), [data])
    const invalidRange = Boolean(start && end && start > end)
    const results = React.useMemo(() => invalidRange ? [] : searchable.filter(({ entry: row, text }) =>
        (!cycle || row.cycle === cycle) && (!weekday || row.weekdayCycle === weekday) && (!tag || row.tags.includes(tag))
        && (!start || row.date >= start) && (!end || row.date <= end) && matches(text, query, smartSearch)).map(r => r.entry),
        [searchable, cycle, weekday, tag, start, end, query, smartSearch, invalidRange])
    function clear() { setQuery(""); setCycle(""); setWeekday(""); setTag(""); setStart(""); setEnd("") }
    return <div style={{ position: "relative", width: "100%", minWidth: 0, boxSizing: "border-box", fontFamily: "Urbanist, sans-serif",
        fontWeight: 600, fontSize: 16, lineHeight: 1.5, color: "#111", overflowWrap: "anywhere", textAlign: "left", ...style }}>
        <style>{`.ll-archive-${id.replace(/:/g, "")} input:focus-visible,.ll-archive-${id.replace(/:/g, "")} select:focus-visible,.ll-archive-${id.replace(/:/g, "")} button:focus-visible{outline:2px solid currentColor;outline-offset:3px}`}</style>
        <div className={`ll-archive-${id.replace(/:/g, "")}`}>
            <div style={{ border: "1px solid #ccc", borderRadius: 10, padding: 12, background: "#f6f6f6", marginBottom: 16 }}>
                {showStatus && <div role="status" style={{ color: muted, fontSize: 14, marginBottom: 12 }}>
                    {loading ? "Checking the shared archive…" : verified ? `Shared server archive · ${data?.count ?? 0} saved reflections` : data ? "Saved copy — current server version not verified" : "Shared archive unavailable"}
                    {data?.latestDate && <div>Latest saved date: {data.latestDate}{today ? ` · Today: ${today} (Eastern)` : ""}</div>}
                    {verified && <div>Checked {checkedAt} Eastern · Version {data?.revision.slice(0, 12)}</div>}
                    {!loading && verified && today && data?.latestDate && data.latestDate < today && <div>Today’s reflection is not in the archive yet.</div>}
                </div>}
                {error && <p role="alert" style={{ margin: "0 0 12px" }}>{error} {data ? "Showing a saved copy; it may be out of date." : "Please try Refresh again."}</p>}
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                    <button type="button" style={button} disabled={loading} onClick={() => refresh(v => v + 1)}>{loading ? "Refreshing…" : "Refresh"}</button>
                    <button type="button" style={button} disabled={!data} onClick={() => exportJSON(data, "lectiolinks-archive-search.json")}>Download search index</button>
                    {legacy && <button type="button" style={button} onClick={() => exportJSON(legacy, "lectiolinks-personal-archive-backup.json")}>Download previous personal archive</button>}
                </div>
            </div>
            <label htmlFor={id + "search"} style={{ display: "block", marginBottom: 6 }}>Search reflections</label>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
                <input id={id + "search"} type="search" value={query} maxLength={200} placeholder={placeholder} onChange={e => setQuery(e.target.value)} style={{ ...control, flex: "1 1 220px", minWidth: 0 }} />
                <button type="button" style={button} onClick={clear}>Clear filters</button>
            </div>
            {showFilters && <fieldset style={{ border: 0, padding: 0, margin: "0 0 16px", minWidth: 0 }}>
                <legend style={{ fontSize: 14, color: muted, marginBottom: 8 }}>Narrow your search</legend>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 180px), 1fr))", gap: 12 }}>
                    <label>Sunday cycle<select aria-label="Sunday cycle" style={{ ...control, display: "block", width: "100%" }} value={cycle} onChange={e => setCycle(e.target.value)}><option value="">All years</option>{["Year A", "Year B", "Year C"].map(v => <option key={v}>{v}</option>)}</select></label>
                    <label>Weekday cycle<select aria-label="Weekday cycle" style={{ ...control, display: "block", width: "100%" }} value={weekday} onChange={e => setWeekday(e.target.value)}><option value="">All cycles</option>{["Cycle I", "Cycle II"].map(v => <option key={v}>{v}</option>)}</select></label>
                    <label>Tag<select aria-label="Tag" style={{ ...control, display: "block", width: "100%" }} value={tag} onChange={e => setTag(e.target.value)}><option value="">All tags</option>{tags.map(v => <option key={v}>{v}</option>)}</select></label>
                    <label>From<input aria-label="From date" type="date" style={{ ...control, display: "block", width: "100%", minWidth: 0 }} value={start} onChange={e => setStart(e.target.value)} /></label>
                    <label>Through<input aria-label="Through date" type="date" style={{ ...control, display: "block", width: "100%", minWidth: 0 }} value={end} onChange={e => setEnd(e.target.value)} /></label>
                </div>
                <p style={{ fontSize: 13, color: muted }}>Cycle labels follow the liturgical year. Weekday I/II describes Ordinary Time; seasonal and feast readings have their own propers.</p>
            </fieldset>}
            {invalidRange && <p role="alert">The From date must be on or before the Through date.</p>}
            {data && <p role="status" style={{ fontSize: 14, color: muted }}>{results.length} {results.length === 1 ? "reflection" : "reflections"} found · Showing {Math.min(limit, results.length)}</p>}
            {!loading && data && !results.length && !invalidRange && <p>No saved reflections match these filters. Missing historical dates are not reconstructed.</p>}
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                {results.slice(0, limit).map(row => <article key={row.date + row.sha256} style={{ border: "1px solid #ddd", borderRadius: 10, padding: 16, background: surface }}>
                    <h2 style={{ fontSize: 20, margin: "0 0 8px" }}><time dateTime={row.date}>{row.date}</time>{row.feast ? ` · ${row.feast}` : ""}</h2>
                    <p style={{ fontSize: 13, color: muted, margin: "0 0 12px" }}>{row.cycle} · {row.weekdayCycle}{row.refs.length ? ` · ${row.refs.join("; ")}` : ""}</p>
                    {row.quote && <blockquote style={{ margin: "0 0 12px", fontStyle: "italic" }}>{row.quote}{row.quoteCitation && <cite style={{ display: "block", fontSize: 14, fontStyle: "normal" }}>{row.quoteCitation}</cite>}</blockquote>}
                    {row.synthesis && <p style={{ margin: "0 0 12px" }}>{row.synthesis}</p>}
                    {row.tags.length > 0 && <p style={{ fontSize: 13, color: muted }}>{row.tags.join(" · ")}</p>}
                    <Reflection entry={row} archiveBase={archiveBase} />
                </article>)}
            </div>
            {limit < results.length && <button type="button" style={{ ...button, marginTop: 20 }} onClick={() => setLimit(v => v + pageSize)}>Show more reflections</button>}
        </div>
    </div>
}

addPropertyControls(DevotionsArchive, {
    indexUrl: { type: ControlType.String, title: "Search Index URL", defaultValue: DEFAULT_INDEX },
    showStatus: { type: ControlType.Boolean, title: "Show Status", defaultValue: true },
    placeholder: { type: ControlType.String, title: "Placeholder", defaultValue: "Search dates, quotes, summaries, tags, references…" },
    maxResults: { type: ControlType.Number, title: "Results per Page", defaultValue: 25, min: 1, max: 50, step: 1 },
    showFilters: { type: ControlType.Boolean, title: "Show Filters", defaultValue: true },
    smartSearch: { type: ControlType.Boolean, title: "Smart Fuzzy Search", defaultValue: true },
})
