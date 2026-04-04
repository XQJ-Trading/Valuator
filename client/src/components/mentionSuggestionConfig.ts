import type { SuggestionKeyDownProps, SuggestionProps } from "@tiptap/suggestion";
import { ReactRenderer } from "@tiptap/react";
import tippy, { type Instance as TippyInstance } from "tippy.js";
import { searchFiles } from "../api";
import { MentionList, type FileMentionItem, type MentionListHandle } from "./MentionSuggestion";

import "tippy.js/dist/tippy.css";

type ListProps = SuggestionProps<FileMentionItem, FileMentionItem>;

let mentionSeq = 0;

export async function fetchMentionItems(query: string, limit: number): Promise<FileMentionItem[]> {
  const id = ++mentionSeq;
  await new Promise((r) => setTimeout(r, 150));
  if (id !== mentionSeq) return [];

  const data = await searchFiles(query, limit);
  return data.results.map((r) => ({
    id: `${r.source}:${r.path}`,
    label: r.name,
    source: r.source,
    path: r.path,
    type: r.type,
  }));
}

export function createMentionSuggestionRender() {
  return () => {
    let component: ReactRenderer<MentionListHandle, ListProps> | null = null;
    let popup: TippyInstance | null = null;

    return {
      onStart: (props: SuggestionProps<FileMentionItem, FileMentionItem>) => {
        component = new ReactRenderer(MentionList, {
          props,
          editor: props.editor,
        });

        popup = tippy(document.body, {
          getReferenceClientRect: () => props.clientRect?.() ?? new DOMRect(),
          appendTo: () => document.body,
          content: component.element,
          showOnCreate: true,
          interactive: true,
          trigger: "manual",
          placement: "bottom-start",
          offset: [0, 4],
        });
      },

      onUpdate: (props: SuggestionProps<FileMentionItem, FileMentionItem>) => {
        component?.updateProps(props);
        popup?.setProps({
          getReferenceClientRect: () => props.clientRect?.() ?? new DOMRect(),
        });
      },

      onKeyDown: (props: SuggestionKeyDownProps) => {
        if (props.event.key === "Escape") {
          popup?.hide();
          return true;
        }
        return component?.ref?.onKeyDown(props) ?? false;
      },

      onExit: () => {
        popup?.destroy();
        component?.destroy();
        popup = null;
        component = null;
      },
    };
  };
}
