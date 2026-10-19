import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const css = readFileSync(join(process.cwd(), 'src/theme/global.css'), 'utf8');

/** Body of the first `@media (max-width: 767px)` block (brace-balanced). */
function phoneBlock(): string {
  const start = css.indexOf('@media (max-width: 767px)');
  expect(start).toBeGreaterThan(-1);
  const open = css.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1;
    if (css[i] === '}') depth -= 1;
    if (depth === 0) return css.slice(open + 1, i);
  }
  throw new Error('unbalanced @media block');
}

/** Selectors (comma lists split) of every rule in `block` that declares `position: sticky`. */
function stickySelectors(block: string): string[] {
  const found: string[] = [];
  for (const match of block.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (/position:\s*sticky/.test(match[2] ?? '')) {
      found.push(...(match[1] ?? '').split(',').map((s) => s.trim()));
    }
  }
  return found;
}

describe('playbar on phones (under 768 px)', () => {
  it('makes only the transport sticky, so sparklines, Speed and Stride scroll with the page', () => {
    expect(stickySelectors(phoneBlock())).toEqual(['.scrubber__transport']);
  });

  it('does not make the whole playbar sticky anywhere else', () => {
    const outsidePhone = css.replace(phoneBlock(), '');
    expect(stickySelectors(outsidePhone)).not.toContain('.playbar');
    expect(stickySelectors(outsidePhone)).not.toContain('.scrubber');
  });

  it('removes the playbar and scrubber boxes so the transport sticks against the page', () => {
    expect(phoneBlock()).toMatch(/\.playbar,\s*\.scrubber\s*\{\s*display:\s*contents;/);
  });
});
