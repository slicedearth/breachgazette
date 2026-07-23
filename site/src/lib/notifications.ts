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
): Array<number | null> {
  if (pageCount <= 7) {
    return Array.from({ length: pageCount }, (_, index) => index + 1);
  }

  const includedPages = new Set([1, pageCount]);
  for (let page = currentPage - 2; page <= currentPage + 2; page += 1) {
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
