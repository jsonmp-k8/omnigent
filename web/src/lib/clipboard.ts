/** A clipboard payload offered in more than one flavor. */
export interface RichTextPayload {
  /** Rendered HTML, taken by rich-text targets such as Slack or Google Docs. */
  html: string;
  /** Plain-text source, taken by editors, terminals, and code cells. */
  text: string;
}

export async function copyText(text: string): Promise<void> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Fall through to the selected-textarea path when async clipboard is
      // unavailable at runtime, e.g. permission denied or a non-secure origin.
    }
  }

  if (copyWithExecCommand({ text })) return;

  throw new Error("Clipboard API not available");
}

/**
 * Writes both flavors so the paste target picks the one it understands: a
 * rich-text editor keeps the formatting, everything else still gets `text`.
 */
export async function copyRichText({ html, text }: RichTextPayload): Promise<void> {
  if (
    typeof navigator !== "undefined" &&
    navigator.clipboard?.write &&
    typeof ClipboardItem === "function"
  ) {
    try {
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/html": new Blob([html], { type: "text/html" }),
          "text/plain": new Blob([text], { type: "text/plain" }),
        }),
      ]);
      return;
    } catch {
      // Fall through: multi-flavor `write` can be unavailable or permission
      // gated where the plain-text paths below still succeed.
    }
  }

  if (copyWithExecCommand({ html, text })) return;

  // Nothing could carry the HTML — copying the source beats copying nothing.
  await copyText(text);
}

function copyWithExecCommand({ html, text }: { html?: string; text: string }): boolean {
  if (
    typeof document === "undefined" ||
    typeof document.execCommand !== "function" ||
    !document.body
  ) {
    return false;
  }

  const selection = document.getSelection();
  const previouslyFocused =
    document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const selectedRanges = selection
    ? Array.from({ length: selection.rangeCount }, (_, index) => selection.getRangeAt(index))
    : [];
  const textArea = document.createElement("textarea");

  textArea.value = text;
  textArea.setAttribute("readonly", "");
  textArea.style.position = "fixed";
  textArea.style.top = "0";
  textArea.style.left = "0";
  textArea.style.width = "1px";
  textArea.style.height = "1px";
  textArea.style.padding = "0";
  textArea.style.border = "0";
  textArea.style.opacity = "0";
  textArea.style.pointerEvents = "none";

  const handleCopy = (event: ClipboardEvent) => {
    event.preventDefault();
    event.clipboardData?.setData("text/plain", text);
    if (html !== undefined) event.clipboardData?.setData("text/html", html);
  };

  document.addEventListener("copy", handleCopy);
  document.body.appendChild(textArea);
  try {
    textArea.focus();
    textArea.select();
    textArea.selectionStart = 0;
    textArea.selectionEnd = textArea.value.length;

    return document.execCommand("copy");
  } finally {
    document.removeEventListener("copy", handleCopy);
    textArea.remove();
    if (previouslyFocused?.isConnected) {
      previouslyFocused.focus({ preventScroll: true });
    }
    if (selection) {
      selection.removeAllRanges();
      for (const range of selectedRanges) {
        selection.addRange(range);
      }
    }
  }
}
