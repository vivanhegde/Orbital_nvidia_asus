/** UTC-relative formatting helpers. */

const FALLBACK = "—";

function isValidTimeMs(ms: number): boolean {
  return Number.isFinite(ms) && !Number.isNaN(ms);
}

export function formatSecondsAgo(iso: string | null): string {
  if (!iso) return FALLBACK;
  try {
    const t = new Date(iso).getTime();
    if (!isValidTimeMs(t)) return FALLBACK;
    const sec = Math.round((Date.now() - t) / 1000);
    if (sec < 0) return "future";
    if (sec < 60) return `${sec}s ago`;
    const m = Math.floor(sec / 60);
    if (m < 60) return `${m} min ago`;
    const h = Math.floor(m / 60);
    if (h < 48) return `${h}h ago`;
    const d = Math.floor(h / 24);
    return `${d}d ago`;
  } catch {
    return FALLBACK;
  }
}

export function formatUntilTca(iso: string): string {
  try {
    const t = new Date(iso).getTime();
    if (!isValidTimeMs(t)) return FALLBACK;
    const ms = t - Date.now();
    if (ms < 0) {
      const sec = Math.round(-ms / 1000);
      const m = Math.floor(sec / 60);
      const h = Math.floor(m / 60);
      return `${h}h ${m % 60}m ago`;
    }
    const m = Math.floor(ms / 60000);
    const h = Math.floor(m / 60);
    const mi = m % 60;
    return `in ${h}h ${mi}m`;
  } catch {
    return FALLBACK;
  }
}

export function formatUtcAbsolute(iso: string): string {
  try {
    const d = new Date(iso);
    if (!isValidTimeMs(d.getTime())) return FALLBACK;
    return d.toISOString().replace("T", " ").slice(0, 19) + " UTC";
  } catch {
    return FALLBACK;
  }
}

export function formatPcOneSigFig(pc: number): string {
  if (pc === 0) return "0.0e0";
  return pc.toExponential(1);
}
