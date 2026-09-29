import { afterEach, describe, expect, it, vi } from "vitest";

import { copyMarkdown, markdownToHtml } from "./copyMarkdown";

const clipboardDescriptor = Object.getOwnPropertyDescriptor(Navigator.prototype, "clipboard");
const execCommandDescriptor = Object.getOwnPropertyDescriptor(Document.prototype, "execCommand");

// jsdom ships no ClipboardItem, so copyRichText's preferred path needs a stub.
class FakeClipboardItem {
  items: Record<string, Blob>;

  constructor(items: Record<string, Blob>) {
    this.items = items;
  }
}

function installClipboard(value: unknown): void {
  Object.defineProperty(Navigator.prototype, "clipboard", { configurable: true, value });
}

/** Reads the flavors back off the ClipboardItem handed to `clipboard.write`. */
async function writtenFlavors(write: ReturnType<typeof vi.fn>): Promise<Record<string, string>> {
  const items = write.mock.calls[0][0] as FakeClipboardItem[];
  const entries = await Promise.all(
    Object.entries(items[0].items).map(async ([type, blob]) => [type, await blob.text()] as const),
  );
  return Object.fromEntries(entries);
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";

  if (clipboardDescriptor) {
    Object.defineProperty(Navigator.prototype, "clipboard", clipboardDescriptor);
  } else {
    delete (Navigator.prototype as { clipboard?: unknown }).clipboard;
  }

  if (execCommandDescriptor) {
    Object.defineProperty(Document.prototype, "execCommand", execCommandDescriptor);
  } else {
    delete (Document.prototype as { execCommand?: unknown }).execCommand;
  }
});

describe("markdownToHtml", () => {
  it("renders inline emphasis and headings as HTML elements", () => {
    expect(markdownToHtml("## Title\n\nSome **bold** and _italic_ text.")).toBe(
      "<h2>Title</h2>\n<p>Some <strong>bold</strong> and <em>italic</em> text.</p>",
    );
  });

  it("renders GFM tables and strikethrough, which plain markdown would not", () => {
    expect(markdownToHtml("| a | b |\n| --- | --- |\n| 1 | 2 |")).toBe(
      "<table><thead><tr><th>a</th><th>b</th></tr></thead>" +
        "<tbody><tr><td>1</td><td>2</td></tr></tbody></table>",
    );
    expect(markdownToHtml("~~gone~~")).toBe("<p><del>gone</del></p>");
  });

  it("keeps a fenced block's language so the paste target can highlight it", () => {
    expect(markdownToHtml("```ts\nconst x = 1;\n```")).toBe(
      '<pre><code class="language-ts">const x = 1;\n</code></pre>',
    );
  });

  it("drops raw HTML tags and strips a javascript: href", () => {
    const html = markdownToHtml(
      '<script>alert(1)</script><img src=x onerror="alert(1)">\n\n[click](javascript:alert(1))',
    );

    expect(html).not.toContain("<script");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("onerror");
    expect(html).not.toContain("javascript:");
    expect(html).toContain("<a>click</a>");
  });
});

describe("copyMarkdown", () => {
  it("writes the rendered HTML and the markdown source as separate flavors", async () => {
    const write = vi.fn().mockResolvedValue(undefined);

    vi.stubGlobal("ClipboardItem", FakeClipboardItem);
    installClipboard({ write });

    await copyMarkdown("A **bold** claim");

    expect(write).toHaveBeenCalledTimes(1);
    expect(await writtenFlavors(write)).toEqual({
      "text/html": "<p>A <strong>bold</strong> claim</p>",
      "text/plain": "A **bold** claim",
    });
  });

  it("falls back to a plain-text write when the browser has no ClipboardItem", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);

    installClipboard({ writeText });
    Object.defineProperty(Document.prototype, "execCommand", {
      configurable: true,
      value: vi.fn(() => false),
    });

    await copyMarkdown("A **bold** claim");

    expect(writeText).toHaveBeenCalledWith("A **bold** claim");
  });
});
