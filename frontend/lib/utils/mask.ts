/**
 * Mask a secret key for display: "sk-a1b2c3d4e5f6" → "sk-a1b**d4"
 */
export function maskSK(skPrefix: string): string {
  if (skPrefix.length <= 7) return skPrefix;
  return `${skPrefix.slice(0, 5)}**${skPrefix.slice(-2)}`;
}

/**
 * Mask a redemption code for display: "REDM-A3F2-K9L4-M7W1" → "REDM-****-A3F2"
 */
export function maskCode(codePrefix: string): string {
  if (codePrefix.length <= 9) return codePrefix;
  return `${codePrefix.slice(0, 5)}-****-${codePrefix.slice(-4)}`;
}
