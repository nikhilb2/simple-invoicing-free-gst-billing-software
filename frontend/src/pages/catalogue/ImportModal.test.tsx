import { createRef } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';
import { ImportSummary } from './ImportModal';

function render(result: { created: number; updated: number; errors: Array<{ row: number; message: string }> }) {
  return renderToStaticMarkup(<ImportSummary result={result} resultRef={createRef<HTMLDivElement>()} />);
}

describe('ImportSummary', () => {
  test('a refused file shows its message without "Row 0" or "Fix the rows below"', () => {
    const html = render({
      created: 0,
      updated: 0,
      errors: [{ row: 0, message: 'This is an Excel file, not a CSV.' }],
    });
    expect(html).toContain('File not imported');
    expect(html).toContain('This is an Excel file, not a CSV.');
    expect(html).not.toContain('Row 0');
    expect(html).not.toContain('Fix the rows below');
  });

  test('row errors still list each row', () => {
    const html = render({
      created: 0,
      updated: 0,
      errors: [{ row: 3, message: 'Missing Item Code / SKU' }],
    });
    expect(html).toContain('Row 3');
    expect(html).toContain('Fix the rows below');
  });
});
