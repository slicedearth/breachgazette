export function createPageJump(currentPage: number, pageCount: number): HTMLDivElement {
  const wrapper = document.createElement("div");
  wrapper.className = "pagination__jump";
  wrapper.dataset.pageJump = "";
  const label = document.createElement("label");
  label.append(document.createTextNode("Jump to page"));
  const input = document.createElement("input");
  input.type = "number";
  input.inputMode = "numeric";
  input.min = "1";
  input.max = String(pageCount);
  input.step = "1";
  input.required = true;
  input.value = String(currentPage);
  label.append(input);
  const total = document.createElement("span");
  total.textContent = `of ${pageCount.toLocaleString()}`;
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Go";
  wrapper.append(label, total, button);
  return wrapper;
}

export function submitPageJump(wrapper: HTMLElement): void {
  const input = wrapper.querySelector("input");
  if (!input || !input.reportValidity() || !Number.isSafeInteger(input.valueAsNumber)) return;
  wrapper.dispatchEvent(new CustomEvent("notification-page-jump", { bubbles: true, detail: input.valueAsNumber }));
}

export function enhanceStaticPageJumps(root: HTMLElement | Document = document): void {
  root.querySelectorAll<HTMLElement>("[data-static-page-jump]").forEach((slot) => {
    if (!slot.childElementCount) slot.append(createPageJump(Number(slot.dataset.currentPage), Number(slot.dataset.pageCount)));
  });
}
