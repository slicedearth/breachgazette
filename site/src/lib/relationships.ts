import type { Relationship } from "./types";

export const RELATIONSHIPS_PER_PAGE = 50;

export type RelationshipPage = {
  items: Relationship[];
  currentPage: number;
  pageCount: number;
  total: number;
  firstItem: number;
  lastItem: number;
};

export function getRelationshipPage(
  relationships: Relationship[],
  currentPage: number,
): RelationshipPage {
  const pageCount = Math.max(1, Math.ceil(relationships.length / RELATIONSHIPS_PER_PAGE));
  if (!Number.isInteger(currentPage) || currentPage < 1 || currentPage > pageCount) {
    throw new Error("Relationship page is outside the published range");
  }
  const offset = (currentPage - 1) * RELATIONSHIPS_PER_PAGE;
  const items = relationships.slice(offset, offset + RELATIONSHIPS_PER_PAGE);
  return {
    items,
    currentPage,
    pageCount,
    total: relationships.length,
    firstItem: items.length ? offset + 1 : 0,
    lastItem: offset + items.length,
  };
}
