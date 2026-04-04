/** Maps task ids like `root.0.1` to session-relative folder paths under `tasks/`. */
export function taskIdToFolderPath(taskId: string): string {
  const parts = taskId.split(".");
  if (parts[0] !== "root") return "";
  let acc = "root";
  let path = `tasks/${acc}`;
  for (let i = 1; i < parts.length; i++) {
    acc = `${acc}.${parts[i]}`;
    path = `${path}/${acc}`;
  }
  return path;
}

export function taskIdToTaskMdPath(taskId: string): string {
  const folder = taskIdToFolderPath(taskId);
  if (!folder) return "";
  return `${folder}/task.md`;
}
