export function relevanceLabel(score: number | undefined): string | null {
  if (typeof score !== "number" || !Number.isFinite(score) || score < 0 || score > 1) return null;
  const percentage = Math.round(score * 100);
  return `${percentage}% retrieval similarity${score < 0.5 ? " · Weak match" : ""}`;
}
