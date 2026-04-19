import { searchFiles } from "../api";
import type { FileMentionItem } from "./MentionSuggestion";

const MENTION_LIMIT = 5;
let mentionSeq = 0;

export async function fetchMentionItems(query: string): Promise<FileMentionItem[]> {
  const id = ++mentionSeq;
  await new Promise((r) => setTimeout(r, 150));
  if (id !== mentionSeq) return [];

  const data = await searchFiles(query, MENTION_LIMIT);
  return data.results.map((r) => ({
    id: `${r.source}:${r.path}`,
    label: r.name,
    source: r.source,
    path: r.path,
    type: r.type,
  }));
}
