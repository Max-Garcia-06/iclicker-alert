() => {
  // v1 heuristic: poll is open when >=2 distinct visible answer buttons A-E exist.
  // Replace with an exact rule once --record captures real iClicker pages.
  const LABELS = new Set(["A", "B", "C", "D", "E"]);
  const seen = new Set();
  for (const el of document.querySelectorAll('button, [role="button"]')) {
    const text = (el.innerText || "").trim();
    if (!LABELS.has(text)) continue;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    if (rect.width === 0 || rect.height === 0) continue;
    if (style.visibility === "hidden" || style.display === "none") continue;
    seen.add(text);
  }
  const labels = [...seen].sort();
  return labels.length >= 2
    ? { open: true, reason: `answer buttons: ${labels.join(",")}` }
    : { open: false, reason: `answer buttons: ${labels.length}` };
}
