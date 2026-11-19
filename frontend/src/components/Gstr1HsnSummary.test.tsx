import { renderToStaticMarkup } from 'react-dom/server';
import { expect, test } from 'vitest';
import type { Gstr1HsnSummaryItem } from '../types/api';
import Gstr1HsnSummary from './Gstr1HsnSummary';

const litres: Gstr1HsnSummaryItem = {
  hsn_code: '1508', description: 'Oil', uqc: 'LTR', gst_rate: 5,
  category: 'B2B', quantity: 20.25, taxable_value: 100,
  cgst: 2.5, sgst: 2.5, igst: 0, total_tax: 5,
};

test('shows each buyer, rate and unit row with a two-decimal quantity', () => {
  const html = renderToStaticMarkup(<Gstr1HsnSummary currency="INR" rows={[
    litres,
    { ...litres, category: 'B2C', uqc: 'KGS', gst_rate: 18, quantity: 3 },
  ]} />);
  expect(html).toContain('2 rows');
  expect(html).toContain('<th scope="col">Buyer type</th>');
  expect(html).toContain('<th scope="col">Description</th>');
  expect(html).toContain('<th scope="col">UQC</th>');
  expect(html).toContain('<td>B2B</td>');
  expect(html).toContain('<td>B2C</td>');
  expect(html).toContain('<td>Oil</td>');
  expect(html).toContain('<td>LTR</td>');
  expect(html).toContain('<td>KGS</td>');
  expect(html).toContain('>5%</td>');
  expect(html).toContain('>18%</td>');
  expect(html).toContain('>20.25</td>');
  expect(html).toContain('>3.00</td>');
});

test('says "1 row", not "1 rows", for a single row', () => {
  const html = renderToStaticMarkup(<Gstr1HsnSummary currency="INR" rows={[litres]} />);
  expect(html).toContain('1 row');
  expect(html).not.toContain('1 rows');
});

test('labels the combined rows from periods before the B2B/B2C split', () => {
  const html = renderToStaticMarkup(<Gstr1HsnSummary currency="INR" rows={[
    { ...litres, category: null, quantity: -0.25 },
  ]} />);
  expect(html).toContain('<td>All buyers</td>');
  expect(html).toContain('>-0.25</td>');
});

test('the empty state spans every column', () => {
  const html = renderToStaticMarkup(<Gstr1HsnSummary currency="INR" rows={[]} />);
  expect(html).toContain('0 rows');
  expect(html).toContain('colSpan="11"');
  expect(html).toContain('No HSN data');
});
