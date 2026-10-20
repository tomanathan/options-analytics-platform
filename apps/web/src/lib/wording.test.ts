import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
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
});
