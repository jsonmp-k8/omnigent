import { renderToStaticMarkup } from "react-dom/server";
import Markdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

import { copyRichText, copyText } from "./clipboard";

/**
 * Renders markdown to an HTML fragment for the clipboard's `text/html` flavor.
 *
 * GFM only, matching how assistant bubbles render (remark-breaks is a
 * user-bubble concern). Raw HTML tags are dropped rather than parsed — no
 * rehype-raw — and sanitize strips unsafe URLs, so agent output cannot smuggle
 * script or event handlers into whatever app the user pastes into.
 */
export function markdownToHtml(markdown: string): string {
  return renderToStaticMarkup(
    <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
      {markdown}
    </Markdown>,
  );
}

/**
 * Copies markdown as rendered HTML alongside its source, so pasting into Slack
 * or a doc keeps the formatting while a plain-text target still gets markdown.
 *
 * Rendering stays synchronous: an `await` before the clipboard write can outlive
 * the click's user-activation window and lose the write permission.
 */
export async function copyMarkdown(markdown: string): Promise<void> {
  let html: string;
  try {
    html = markdownToHtml(markdown);
  } catch {
    // A render failure must not cost the user their copy.
    await copyText(markdown);
    return;
  }
  await copyRichText({ html, text: markdown });
}
