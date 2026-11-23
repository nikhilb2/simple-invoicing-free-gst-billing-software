/**
 * GstinInput.tsx
 *
 * A GSTIN text box that hands its caller the value normalised as the API
 * stores it (upper case, no whitespace), whether it was typed or pasted.
 *
 * It sets no maxLength on purpose. The browser cuts pasted text to maxLength
 * before onChange sees it, spaces included, so a GSTIN copied with spaces such
 * as " 29AAB CK1234 L1ZI " used to arrive as "29AABCK1234L" with a format
 * error. The length is checked by gstinError instead, like on the Company page.
 */
import { forwardRef, type InputHTMLAttributes } from 'react';
import { normalizeGstinInput } from '../utils/gstin';

type GstinInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'maxLength'> & {
  value: string;
  /** Receives the normalised GSTIN on every change. */
  onValueChange: (gstin: string) => void;
};

const GstinInput = forwardRef<HTMLInputElement, GstinInputProps>(function GstinInput(
  { value, onValueChange, ...rest },
  ref,
) {
  return (
    <input
      {...rest}
      ref={ref}
      value={value}
      onChange={(event) => onValueChange(normalizeGstinInput(event.target.value))}
    />
  );
});

export default GstinInput;
