import DOMPurify from "dompurify";
import { marked } from "marked";

/**
 * Digest content is LLM-generated *from email bodies* — attacker-influenced
 * text. Sanitize after markdown parsing before it ever reaches
 * dangerouslySetInnerHTML, so a crafted email can't inject a script tag that
 * survives into the summary and executes in the browser.
 */
export function renderMarkdown(source: string): string {
  const html = marked.parse(source, { async: false }) as string;
  return DOMPurify.sanitize(html);
}
