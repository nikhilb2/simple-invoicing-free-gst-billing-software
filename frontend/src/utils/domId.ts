/** Text made safe for an element id: lower case, runs of anything else become one hyphen. */
export function domIdPart(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}
