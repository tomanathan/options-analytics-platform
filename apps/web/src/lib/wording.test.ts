import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { ENTRY_EVIDENCE, ENTRY_RULE } from '../test/fixtures';
import { ADVICE_WORDS } from '../test/wording';

/** Source files of the explorer UI (tests and the generated schema excluded). */
function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === 'test' ? [] : sources(path);
    if (!/\.(ts|tsx)$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name)) return [];
    return path.endsWith(join('api', 'schema.ts')) ? [] : [path];
  });
}

describe('wording', () => {
  it('has no buy, sell, recommend or should in any UI source string', () => {
    // Tests run from apps/web (npm test).
    const offenders = sources(join(process.cwd(), 'src')).flatMap((file) => {
      const match = ADVICE_WORDS.exec(readFileSync(file, 'utf8'));
      return match ? [`${file}: ${match[0]}`] : [];
    });
    expect(offenders).toEqual([]);
  });

  it('has none of them in the API contract, whose descriptions name the entry rule and its evidence', () => {
    const contract = readFileSync(join(process.cwd(), 'openapi.json'), 'utf8');
    expect(contract).toContain('entry_evidence');
    expect(ADVICE_WORDS.exec(contract)?.[0] ?? null).toBeNull();
  });

  it('has none of them in the entry rule and evidence the explorer prints', () => {
    [ENTRY_RULE, ENTRY_EVIDENCE].forEach((text) => {
      expect(ADVICE_WORDS.exec(text)?.[0] ?? null).toBeNull();
    });
  });
});
