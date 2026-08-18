import {escapeHtml} from './core.js?v=20260818-7';

function inlineMarkdown(value) {
  const parts = String(value ?? '').split(/(`[^`\n]+`)/g);
  return parts.map(part => {
    if (part.startsWith('`') && part.endsWith('`')) {
      return `<code>${escapeHtml(part.slice(1, -1))}</code>`;
    }
    return escapeHtml(part)
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/__([^_]+)__/g, '<strong>$1</strong>')
      .replace(/(^|\s)\*([^*\n]+)\*/g, '$1<em>$2</em>')
      .replace(/(^|\s)_([^_\n]+)_/g, '$1<em>$2</em>');
  }).join('');
}

function codeBlock(language, code) {
  const label = language || 'text';
  return `<div class="code-block"><div class="code-header"><span>${escapeHtml(label)}</span><button type="button" class="copy-code" data-copy-code>Copy</button></div><pre><code class="language-${escapeHtml(label)}">${escapeHtml(code)}</code></pre></div>`;
}

export function renderMarkdown(markdown) {
  const lines = String(markdown ?? '').replace(/\r\n?/g, '\n').split('\n');
  const output = [];
  let paragraph = [];
  let list = null;
  let quote = [];

  const flushParagraph = () => {
    if (paragraph.length) output.push(`<p>${inlineMarkdown(paragraph.join('\n')).replace(/\n/g, '<br>')}</p>`);
    paragraph = [];
  };
  const flushList = () => {
    if (list) output.push(`<${list.tag}>${list.items.map(item => `<li>${inlineMarkdown(item)}</li>`).join('')}</${list.tag}>`);
    list = null;
  };
  const flushQuote = () => {
    if (quote.length) output.push(`<blockquote>${quote.map(inlineMarkdown).join('<br>')}</blockquote>`);
    quote = [];
  };
  const flushText = () => { flushParagraph(); flushList(); flushQuote(); };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const fence = line.match(/^```([\w.+-]*)\s*$/);
    if (fence) {
      flushText();
      const code = [];
      index += 1;
      while (index < lines.length && !/^```\s*$/.test(lines[index])) {
        code.push(lines[index]);
        index += 1;
      }
      output.push(codeBlock(fence[1], code.join('\n')));
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushText();
      const level = heading[1].length + 2;
      output.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    const listItem = line.match(/^\s*([-*]|\d+[.])\s+(.+)$/);
    if (listItem) {
      flushParagraph(); flushQuote();
      const tag = /\d/.test(listItem[1]) ? 'ol' : 'ul';
      if (list && list.tag !== tag) flushList();
      if (!list) list = {tag, items: []};
      list.items.push(listItem[2]);
      continue;
    }
    const quoted = line.match(/^>\s?(.*)$/);
    if (quoted) {
      flushParagraph(); flushList(); quote.push(quoted[1]);
      continue;
    }
    if (!line.trim()) {
      flushText();
      continue;
    }
    flushList(); flushQuote(); paragraph.push(line);
  }
  flushText();
  return output.join('');
}

export function wireMarkdownActions(root = document) {
  root.addEventListener('click', async event => {
    const button = event.target.closest('[data-copy-code]');
    if (!button) return;
    const code = button.closest('.code-block')?.querySelector('code')?.textContent || '';
    try {
      await navigator.clipboard.writeText(code);
      button.textContent = 'Copied';
      setTimeout(() => { button.textContent = 'Copy'; }, 1400);
    } catch (_) {
      button.textContent = 'Copy failed';
    }
  });
}
