/**
 * Group scoping for asset lists — keyed on `commodity_group` (config-over-code:
 * pages scope by group identifier, never by hardcoded asset names).
 */

export interface GroupScope {
  /** Keep only items in this group (e.g. "equity" on the stocks page). */
  group?: string;
  /** Drop items in this group (the home explorer hides equities). */
  excludeGroup?: string;
}

export function filterByGroup<T extends { commodity_group: string }>(
  items: T[],
  scope: GroupScope = {},
): T[] {
  return items.filter(
    (c) =>
      (!scope.group || c.commodity_group === scope.group) &&
      (!scope.excludeGroup || c.commodity_group !== scope.excludeGroup),
  );
}
