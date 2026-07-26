import type { Notification } from "./types";

export const NOTIFICATIONS_PER_PAGE = 50;

export type NotificationPage = {
  items: Notification[];
  currentPage: number;
  pageCount: number;
  total: number;
  firstItem: number;
  lastItem: number;
};

export function getNotificationPage(
  notifications: Notification[],
  currentPage: number,
): NotificationPage {
  const pageCount = Math.max(1, Math.ceil(notifications.length / NOTIFICATIONS_PER_PAGE));
  if (!Number.isInteger(currentPage) || currentPage < 1 || currentPage > pageCount) {
    throw new Error("Notification page is outside the published range");
  }
  const offset = (currentPage - 1) * NOTIFICATIONS_PER_PAGE;
  const items = notifications.slice(offset, offset + NOTIFICATIONS_PER_PAGE);
  return {
    items,
    currentPage,
    pageCount,
    total: notifications.length,
    firstItem: items.length ? offset + 1 : 0,
    lastItem: offset + items.length,
  };
}

export function getNotificationPaginationItems(
  currentPage: number,
  pageCount: number,
  siblingCount = 2,
): Array<number | null> {
  if (!Number.isInteger(siblingCount) || siblingCount < 0) {
    throw new Error("Pagination sibling count must be a non-negative integer");
  }

  const fullRangeLimit = siblingCount * 2 + 5;
  if (pageCount <= fullRangeLimit) {
    return Array.from({ length: pageCount }, (_, index) => index + 1);
  }

  const interiorWindowSize = siblingCount * 2 + 1;
  let windowStart = currentPage - siblingCount;
  let windowEnd = currentPage + siblingCount;
  if (windowStart <= 2) {
    windowStart = 2;
    windowEnd = windowStart + interiorWindowSize - 1;
  } else if (windowEnd >= pageCount - 1) {
    windowEnd = pageCount - 1;
    windowStart = windowEnd - interiorWindowSize + 1;
  }

  const includedPages = new Set([1, pageCount]);
  for (let page = windowStart; page <= windowEnd; page += 1) {
    if (page > 1 && page < pageCount) includedPages.add(page);
  }

  const sortedPages = [...includedPages].sort((left, right) => left - right);
  const items: Array<number | null> = [];
  sortedPages.forEach((page, index) => {
    const previousPage = sortedPages[index - 1];
    if (previousPage !== undefined && page - previousPage > 1) items.push(null);
    items.push(page);
  });
  return items;
}
