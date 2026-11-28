import { renderToString } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { FinancialYear } from '../api/financialYears';
import FYDateWarning from './FYDateWarning';

const mockFY = vi.hoisted(() => ({ fyList: [] as FinancialYear[], activeFY: null as FinancialYear | null }));
vi.mock('../context/FYContext', () => ({ useFY: () => mockFY }));

const fy = (id: number, label: string, start: string, end: string, active: boolean): FinancialYear => ({
  id, label, start_date: start, end_date: end, is_active: active,
});

describe('FYDateWarning', () => {
  it('replaces "will still be created" with the refusal text when no year holds the date', () => {
    const current = fy(1, '2026-27', '2026-04-01', '2027-03-31', true);
    mockFY.fyList = [current];
    mockFY.activeFY = current;
    const html = renderToString(<FYDateWarning date="2027-04-01" outcome="The invoice will still be created." />);
    expect(html).toContain('class="field-warning"');
    expect(html).toContain('This date is in FY 2027-28, which isn&#x27;t set up yet.');
    expect(html).toContain('Or pick a date in FY 2026-27.');
    expect(html).not.toContain('will still be created');
  });

  it('keeps "will still be created" when another year holds the date', () => {
    const current = fy(1, '2026-27', '2026-04-01', '2027-03-31', true);
    mockFY.fyList = [current, fy(2, '2025-26', '2025-04-01', '2026-03-31', false)];
    mockFY.activeFY = current;
    const html = renderToString(<FYDateWarning date="2026-03-31" outcome="The invoice will still be created." />);
    expect(html).toContain('outside the active financial year (2026-27). The invoice will still be created.');
  });

  it('renders nothing when the company has no years', () => {
    mockFY.fyList = [];
    mockFY.activeFY = null;
    expect(renderToString(<FYDateWarning date="2027-04-01" outcome="x" />)).toBe('');
  });
});
