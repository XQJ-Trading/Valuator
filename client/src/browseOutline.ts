/** Path helpers aligned with `valuator/session/browse_tree.py` (report/final under each browse node). */

function posixJoin(a: string, b: string): string {
  const as = a.replace(/\/+$/, "");
  const bs = b.replace(/^\/+/, "");
  return bs ? `${as}/${bs}` : as;
}

/** Primary artifact per browse node (`browse_tree.py` copies aggregation/execution into `report.md`). */
export function browseDirToReportPath(relDirPath: string): string {
  return posixJoin(relDirPath, "report.md");
}

/** Session-level synthesis output at each browse node. */
export function browseDirToFinalPath(relDirPath: string): string {
  return posixJoin(relDirPath, "final.md");
}
