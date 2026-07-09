/**
 * Copy `text` to the clipboard, falling back when the modern API is
 * unavailable (HTTP context, missing focus, sandboxed iframe).
 *
 * Returns `true` on success, `false` if every strategy failed.
 * Never throws — caller decides how to surface failure.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  // Primary: secure-context async API.
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to the textarea fallback.
    }
  }

  if (typeof document === "undefined") return false;

  // Fallback: hidden <textarea> + document.execCommand("copy").
  // Works in non-secure contexts (HTTP) and in older browsers.
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.top = "-1000px";
  ta.style.left = "0";
  ta.style.opacity = "0";
  document.body.appendChild(ta);

  const selection = document.getSelection();
  const previousRange =
    selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;

  ta.select();
  ta.setSelectionRange(0, text.length);

  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }

  document.body.removeChild(ta);

  // Restore the user's previous selection.
  if (previousRange && selection) {
    selection.removeAllRanges();
    selection.addRange(previousRange);
  }

  return ok;
}

/**
 * Last-resort fallback: pop a native prompt with the text already
 * selected so the user can Ctrl/Cmd-C even when clipboard APIs
 * are entirely blocked (e.g. very old browser, strict sandbox).
 * Returns `true` if the user actually copied (i.e. didn't cancel).
 */
export function promptCopyFallback(text: string): boolean {
  if (typeof window === "undefined") return false;
  // The native prompt always renders the full text and lets the user
  // select+copy. There's no return value indicating copy, so we treat
  // any non-cancel as success.
  window.prompt("请使用 Ctrl/⌘+C 复制 sk：", text);
  return true;
}
