/**
 * Format price from cents (INTEGER) to display string (¥X.XX).
 * Architecture constraint #8: balance amounts are stored in cents (INTEGER).
 */
export function formatPrice(cents: number): string {
  const yuan = cents / 100;
  return `¥${yuan.toFixed(2)}`;
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
 * Format token unit price from micro-yuan per 1K tokens.
 * E.g., 15000 → "¥0.015", 150 → "¥0.00015".
 */
export function formatUnitPrice(microYuan: number): string {
  const yuan = microYuan / 1_000_000;
  if (yuan === 0) {
    return "¥0";
  }
  if (yuan < 0.001) {
    return `¥${yuan.toFixed(5).replace(/0+$/, "")}`;
  }
  if (yuan < 1) {
    return `¥${yuan.toFixed(4).replace(/0+$/, "")}`;
  }
  return `¥${yuan.toFixed(2)}`;
}

/**
 * Format ISO date string to Chinese locale display.
 */
export function formatDate(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}
