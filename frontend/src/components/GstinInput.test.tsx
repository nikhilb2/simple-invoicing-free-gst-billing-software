import { describe, expect, it } from 'vitest';
import type { ChangeEvent, ReactElement } from 'react';
import { renderToString } from 'react-dom/server';
import GstinInput from './GstinInput';

type RenderableInput = {
  render: (props: Parameters<typeof GstinInput>[0], ref: null) => ReactElement<{
    onChange: (event: ChangeEvent<HTMLInputElement>) => void;
  }>;
};

describe('GstinInput', () => {
  it('sets no maxlength, so the browser cannot cut a pasted GSTIN before its spaces are removed', () => {
    const html = renderToString(
      <GstinInput id="ledger-gst" className="input" value="" onValueChange={() => {}} placeholder="27ABCDE1234F1Z0" />,
    );

    expect(html).toContain('id="ledger-gst"');
    expect(html).toContain('placeholder="27ABCDE1234F1Z0"');
    expect(html.toLowerCase()).not.toContain('maxlength');
  });

  it('hands the caller a pasted GSTIN with its spaces removed and in upper case', () => {
    const received: string[] = [];
    const input = (GstinInput as unknown as RenderableInput).render(
      { value: '', onValueChange: (gstin) => received.push(gstin) },
      null,
    );

    input.props.onChange({ target: { value: ' 29AAB CK1234 L1ZI ' } } as ChangeEvent<HTMLInputElement>);
    input.props.onChange({ target: { value: '27abcde1234f1z0' } } as ChangeEvent<HTMLInputElement>);

    expect(received).toEqual(['29AABCK1234L1ZI', '27ABCDE1234F1Z0']);
  });
});
