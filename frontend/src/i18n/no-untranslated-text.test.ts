import { readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

import ts from 'typescript';
import { describe, expect, it } from 'vitest';

/**
 * No English may be written straight into a component.
 *
 * Half the interface was translated and half was not, which reads as broken rather than as
 * untranslated: a Croatian reader met "Loading project…" and "German preview" among their
 * own language. The catalogues are type-checked against each other, so the gap was never in
 * the catalogues -- it was in components that never asked for one.
 *
 * This parses each component with the TypeScript compiler rather than matching text, so a
 * literal cannot hide behind formatting. It is the "next English string cannot be added
 * silently" rule; the failure message names the file, the line and the text.
 */

// Resolved from the Vitest root rather than from `import.meta.url`, which is a module
// specifier here and not a path on disk.
const SOURCE_ROOT = resolve(process.cwd(), 'src');

/** Attributes a screen reader or a tooltip renders, so they need translating too. */
const TRANSLATED_ATTRIBUTES = new Set([
  'aria-label',
  'aria-description',
  'alt',
  'placeholder',
  'title',
]);

/**
 * Literals that are not prose.
 *
 * The product's own name, a URL example in a placeholder and the name of a command read the
 * same in every language; putting them through a catalogue would mean four identical copies
 * to keep in step, and a translator who "translated" one would be wrong.
 */
const NOT_PROSE = /^[^\p{L}]*$|^https?:\/\/|^germandubi\b/iu;

function componentFiles(directory: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) found.push(...componentFiles(path));
    else if (entry.name.endsWith('.tsx') && !entry.name.endsWith('.test.tsx')) found.push(path);
  }
  return found;
}

function literalsIn(path: string): string[] {
  const text = readFileSync(path, 'utf8');
  const source = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const found: string[] = [];

  const report = (node: ts.Node, value: string) => {
    const { line } = source.getLineAndCharacterOfPosition(node.getStart(source));
    found.push(`${path.slice(SOURCE_ROOT.length + 1)}:${String(line + 1)} ${value}`);
  };

  const visit = (node: ts.Node): void => {
    if (ts.isJsxText(node)) {
      const value = node.text.trim();
      if (value && !NOT_PROSE.test(value)) report(node, value);
    }
    if (ts.isJsxAttribute(node) && ts.isIdentifier(node.name)) {
      const initializer = node.initializer;
      if (
        TRANSLATED_ATTRIBUTES.has(node.name.text) &&
        initializer &&
        ts.isStringLiteral(initializer) &&
        !NOT_PROSE.test(initializer.text)
      ) {
        report(node, `${node.name.text}="${initializer.text}"`);
      }
    }
    ts.forEachChild(node, visit);
  };

  visit(source);
  return found;
}

describe('components', () => {
  it('contain no text that bypasses the catalogues', () => {
    const offenders = componentFiles(SOURCE_ROOT).flatMap(literalsIn);
    expect(offenders, `translate these through useT():\n${offenders.join('\n')}`).toEqual([]);
  });
});
