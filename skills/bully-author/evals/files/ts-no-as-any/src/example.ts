// Example file -- contains a real `as any` cast for fixture tests to target.
export function widen(input: unknown) {
  const value = input as any;
  return value.foo;
}

// And a docblock that mentions "as any" in prose -- should NOT be flagged by an ast rule.
/**
 * Casting `as any` is forbidden. Use `as unknown` then narrow.
 */
export function compliant(input: unknown) {
  const value = input as unknown as { foo: string };
  return value.foo;
}
