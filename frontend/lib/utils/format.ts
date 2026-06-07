/**
 * Format price from cents (INTEGER) to display string ($X.XX).
 * 1:1 relabel — internal storage is still in cents, but the UI shows $.
 * Architecture constraint #8: balance amounts are stored in cents (INTEGER).
 */
export function formatPrice(cents: number): string {
  const dollars = cents / 100;
  return `$${dollars.toFixed(2)}`;
}

/**
 * Format large numbers with thousands separators.
 */
export function formatNumber(n: number): string {
  return n.toLocaleString("zh-CN");
}

/**
 * Format token count with units (1K=1000).
 */
export function formatTokens(tokens: number): string {
  if (tokens >= 1_000_000) {
    return `${(tokens / 1_000_000).toFixed(1)}M`;
  }
  if (tokens >= 1_000) {
    return `${(tokens / 1_000).toFixed(1)}K`;
  }
  return String(tokens);
}

/**
 * Format token unit price from micro-yuan per 1K tokens, displayed as $X.XX per 1M.
 * 1:1 relabel — micro-yuan is treated as cents-of-a-dollar; multiplying by 1000
 * converts from per-1K to per-1M.
 *
 * E.g., 15000 → "$15.00", 75000 → "$75.00".
 */
export function formatUnitPrice(microYuan: number): string {
  if (microYuan === 0) {
    return "$0.00";
  }
  const dollarsPer1M = microYuan / 1000;
  return `$${dollarsPer1M.toFixed(2)}`;
}

/**
 * Format ISO date string to Chinese locale display.
 */
export function formatDate(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}
