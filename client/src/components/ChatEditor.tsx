import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import type { Editor } from "@tiptap/core";
import { EditorContent, useEditor } from "@tiptap/react";
import { mergeAttributes } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import Mention from "@tiptap/extension-mention";
import Placeholder from "@tiptap/extension-placeholder";
import {
  createMentionSuggestionRender,
  fetchMentionItems,
} from "./mentionSuggestionConfig";
import styles from "./ChatEditor.module.css";

export type ChatEditorHandle = {
  clear: () => void;
};

const MENTION_LIMIT = 5;

const FileMention = Mention.extend({
  selectable: true,
}).configure({
  deleteTriggerWithBackspace: false,
  renderText({ node }) {
    const id = node.attrs.id ?? "";
    const idx = id.indexOf(":");
    if (idx >= 0) {
      const source = id.slice(0, idx);
      const relPath = id.slice(idx + 1);
      return `@[${source}:${relPath}]`;
    }
    return `@${node.attrs.label ?? id}`;
  },
  renderHTML({ node, suggestion }) {
    const label = node.attrs.label ?? node.attrs.id;
    const ch = suggestion?.char ?? "@";
    return [
      "span",
      mergeAttributes(
        { class: "chat-mention", "data-type": "mention" },
        {
          "data-id": node.attrs.id ?? undefined,
          "data-label": node.attrs.label ?? undefined,
        },
      ),
      `${ch}${label}`,
    ];
  },
  suggestion: {
    char: "@",
    items: async ({ query }) => fetchMentionItems(query, MENTION_LIMIT),
    render: createMentionSuggestionRender(),
  },
});

const ChatEditor = forwardRef<
  ChatEditorHandle,
  {
    disabled?: boolean;
    onSubmit: (plainText: string) => void;
    onDraftChange?: (plainText: string) => void;
  }
>(function ChatEditor({ disabled, onSubmit, onDraftChange }, ref) {
  const onSubmitRef = useRef(onSubmit);
  const onDraftChangeRef = useRef(onDraftChange);
  const editorRef = useRef<Editor | null>(null);

  useEffect(() => {
    onSubmitRef.current = onSubmit;
  }, [onSubmit]);

  useEffect(() => {
    onDraftChangeRef.current = onDraftChange;
  }, [onDraftChange]);

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: false,
        blockquote: false,
        bulletList: false,
        orderedList: false,
        listItem: false,
        listKeymap: false,
        codeBlock: false,
        horizontalRule: false,
        bold: false,
        italic: false,
        strike: false,
        code: false,
        link: false,
        underline: false,
        trailingNode: false,
      }),
      FileMention,
      Placeholder.configure({
        placeholder: "Message…",
        emptyEditorClass: "is-editor-empty",
      }),
    ],
    content: "<p></p>",
    onCreate: ({ editor: ed }) => {
      editorRef.current = ed;
    },
    onDestroy: () => {
      editorRef.current = null;
    },
    onUpdate: ({ editor: ed }) => {
      onDraftChangeRef.current?.(ed.getText());
    },
    editorProps: {
      attributes: {
        spellcheck: "false",
      },
      handleKeyDown: (_view, event) => {
        if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
          event.preventDefault();
          const ed = editorRef.current;
          if (!ed) return false;
          const text = ed.getText().trim();
          if (text) {
            onSubmitRef.current(text);
          }
          return true;
        }
        return false;
      },
    },
    immediatelyRender: true,
  });

  useImperativeHandle(ref, () => ({
    clear: () => {
      editorRef.current?.commands.clearContent();
      onDraftChangeRef.current?.("");
    },
  }));

  useEffect(() => {
    editor?.setEditable(!disabled);
  }, [disabled, editor]);

  return (
    <div className={styles.wrap}>
      <EditorContent editor={editor} className={styles.editor} />
    </div>
  );
});

ChatEditor.displayName = "ChatEditor";

export default ChatEditor;
