import { useCallback, useEffect, useRef, useState } from "react";
import {
  copyEntry,
  createEntry,
  deleteEntry,
  fetchTree,
  moveEntry,
  renameEntry,
  type DataSource,
  type TreeEntry,
} from "../api";
import styles from "./FileTree.module.css";

interface TreeNodeData extends TreeEntry {
  children?: TreeNodeData[];
  loaded?: boolean;
  expanded?: boolean;
}

interface ClipboardState {
  mode: "copy" | "cut";
  path: string;
}

interface ContextMenuState {
  x: number;
  y: number;
  path: string;
  type: "file" | "directory";
}

interface PendingCreate {
  parentPath: string;
  kind: "file" | "directory";
}

interface PendingRename {
  path: string;
  initialName: string;
}

function parentOf(relPath: string): string {
  const i = relPath.lastIndexOf("/");
  return i === -1 ? "" : relPath.slice(0, i);
}

function basenameOf(relPath: string): string {
  const i = relPath.lastIndexOf("/");
  return i === -1 ? relPath : relPath.slice(i + 1);
}

function isUnderOrEqual(child: string, ancestor: string): boolean {
  return child === ancestor || child.startsWith(ancestor + "/");
}

function findNode(nodes: TreeNodeData[], path: string): TreeNodeData | null {
  for (const n of nodes) {
    if (n.path === path) return n;
    if (n.children?.length) {
      const f = findNode(n.children, path);
      if (f) return f;
    }
  }
  return null;
}

async function loadChildrenIfNeeded(
  node: TreeNodeData,
  dataSource: DataSource,
): Promise<void> {
  if (!node.loaded) {
    const r = await fetchTree(node.path, dataSource);
    node.children = r.children.map((c) => ({
      ...c,
      children: [],
      loaded: false,
      expanded: false,
    }));
    node.loaded = true;
  }
}

/** Paths of directories that were expanded before a full tree reload. */
function collectExpandedDirPaths(nodes: TreeNodeData[], out: Set<string>): void {
  for (const n of nodes) {
    if (n.type === "directory" && n.expanded) {
      out.add(n.path);
      if (n.children?.length) collectExpandedDirPaths(n.children, out);
    }
  }
}

/** Re-fetch children for each path in `expandedPaths` that still exists under `nodes`. */
async function restoreExpandedDirs(
  nodes: TreeNodeData[],
  expandedPaths: Set<string>,
  dataSource: DataSource,
): Promise<void> {
  for (const node of nodes) {
    if (node.type !== "directory") continue;
    if (!expandedPaths.has(node.path)) continue;
    node.expanded = true;
    const r = await fetchTree(node.path, dataSource);
    node.children = r.children.map((c) => ({
      ...c,
      children: [],
      loaded: false,
      expanded: false,
    }));
    node.loaded = true;
    await restoreExpandedDirs(
      node.children.filter((c) => c.type === "directory"),
      expandedPaths,
      dataSource,
    );
  }
}

type TreeNodeProps = {
  node: TreeNodeData;
  depth: number;
  activePath: string | null;
  selectedPath: string | null;
  pendingCreate: PendingCreate | null;
  pendingRename: PendingRename | null;
  clipboard: ClipboardState | null;
  dragOverPath: string | null;
  onToggle: (node: TreeNodeData) => void;
  onSelectNode: (path: string, type: "file" | "directory") => void;
  onOpenFile: (path: string) => void;
  onContextMenu: (e: React.MouseEvent, path: string, type: "file" | "directory") => void;
  onDragStart: (e: React.DragEvent, path: string, type: "file" | "directory") => void;
  onDragOver: (e: React.DragEvent, path: string, type: "file" | "directory") => void;
  onDragLeave: (e: React.DragEvent, path: string) => void;
  onDrop: (e: React.DragEvent, path: string, type: "file" | "directory") => void;
  onSubmitCreate: (name: string) => void;
  onCancelCreate: () => void;
  onSubmitRename: (path: string, newName: string) => void;
  onCancelRename: () => void;
};

function TreeNode({
  node,
  depth,
  activePath,
  selectedPath,
  pendingCreate,
  pendingRename,
  clipboard,
  dragOverPath,
  onToggle,
  onSelectNode,
  onOpenFile,
  onContextMenu,
  onDragStart,
  onDragOver,
  onDragLeave,
  onDrop,
  onSubmitCreate,
  onCancelCreate,
  onSubmitRename,
  onCancelRename,
}: TreeNodeProps) {
  const isSelected = selectedPath === node.path;
  const isOpen = node.type === "file" && activePath === node.path;
  const isCut = clipboard?.mode === "cut" && clipboard.path === node.path;
  const isDragOver = dragOverPath === node.path && node.type === "directory";
  const paddingLeft = 12 + depth * 16;
  const renameThis = pendingRename?.path === node.path;

  const handleClick = () => {
    if (node.type === "directory") {
      onSelectNode(node.path, "directory");
      void onToggle(node);
    } else {
      onSelectNode(node.path, "file");
      onOpenFile(node.path);
    }
  };

  const createInputRef = useRef<HTMLInputElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);

  const showCreateRow =
    pendingCreate &&
    pendingCreate.parentPath === node.path &&
    node.type === "directory" &&
    node.expanded;

  useEffect(() => {
    if (renameThis) {
      renameInputRef.current?.focus();
      renameInputRef.current?.select();
    }
  }, [renameThis]);

  useEffect(() => {
    if (showCreateRow) {
      createInputRef.current?.focus();
    }
  }, [showCreateRow]);

  if (renameThis) {
    return (
      <div className={`${styles.row} ${styles.inlineRow}`} style={{ paddingLeft }}>
        <span className={styles.icon}>
          {node.type === "directory" ? (node.expanded ? "▾" : "▸") : ""}
        </span>
        <input
          ref={renameInputRef}
          className={styles.inlineInput}
          defaultValue={pendingRename!.initialName}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              const v = e.currentTarget.value.trim();
              if (v) onSubmitRename(node.path, v);
            }
            if (e.key === "Escape") onCancelRename();
          }}
          onBlur={(e) => {
            const v = e.target.value.trim();
            if (v && v !== pendingRename!.initialName) onSubmitRename(node.path, v);
            else onCancelRename();
          }}
        />
      </div>
    );
  }

  return (
    <>
      <div
        className={`${styles.row} ${isSelected ? styles.rowSelected : ""} ${isOpen ? styles.rowOpen : ""} ${isCut ? styles.rowCut : ""} ${isDragOver ? styles.rowDropTarget : ""}`}
        style={{ paddingLeft }}
        draggable
        onDragStart={(e) => onDragStart(e, node.path, node.type)}
        onDragOver={(e) => onDragOver(e, node.path, node.type)}
        onDragLeave={(e) => onDragLeave(e, node.path)}
        onDrop={(e) => onDrop(e, node.path, node.type)}
        onClick={handleClick}
        onContextMenu={(e) => onContextMenu(e, node.path, node.type)}
      >
        <span className={styles.icon}>
          {node.type === "directory" ? (node.expanded ? "▾" : "▸") : ""}
        </span>
        <span
          className={`${styles.label} ${node.type === "directory" ? styles.type_directory : styles.type_file}`}
        >
          {node.name}
        </span>
      </div>
      {node.type === "directory" && node.expanded && (
        <>
          {showCreateRow && (
            <div
              className={`${styles.row} ${styles.inlineRow}`}
              style={{ paddingLeft: paddingLeft + 16 }}
            >
              <span className={styles.icon} />
              <input
                ref={createInputRef}
                className={styles.inlineInput}
                placeholder={pendingCreate!.kind === "file" ? "filename" : "folder name"}
                defaultValue=""
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    const v = e.currentTarget.value.trim();
                    if (v) onSubmitCreate(v);
                  }
                  if (e.key === "Escape") onCancelCreate();
                }}
                onBlur={(e) => {
                  const v = e.target.value.trim();
                  if (v) onSubmitCreate(v);
                  else onCancelCreate();
                }}
              />
            </div>
          )}
          {node.children?.map((c) => (
            <TreeNode
              key={c.path}
              node={c}
              depth={depth + 1}
              activePath={activePath}
              selectedPath={selectedPath}
              pendingCreate={pendingCreate}
              pendingRename={pendingRename}
              clipboard={clipboard}
              dragOverPath={dragOverPath}
              onToggle={onToggle}
              onSelectNode={onSelectNode}
              onOpenFile={onOpenFile}
              onContextMenu={onContextMenu}
              onDragStart={onDragStart}
              onDragOver={onDragOver}
              onDragLeave={onDragLeave}
              onDrop={onDrop}
              onSubmitCreate={onSubmitCreate}
              onCancelCreate={onCancelCreate}
              onSubmitRename={onSubmitRename}
              onCancelRename={onCancelRename}
            />
          ))}
        </>
      )}
    </>
  );
}

export default function FileTree({
  dataSource,
  activePath,
  onSelect,
  onSelectDirectory,
  refreshToken,
  initialExpandDirectory,
}: {
  dataSource: DataSource;
  activePath: string | null;
  onSelect: (path: string | null) => void;
  onSelectDirectory?: (path: string) => void;
  refreshToken?: number;
  /** Expand and select this directory once (e.g. latest session / browse). */
  initialExpandDirectory?: string | null;
}) {
  const [roots, setRoots] = useState<TreeNodeData[]>([]);
  const rootsRef = useRef<TreeNodeData[]>([]);
  useEffect(() => {
    rootsRef.current = roots;
  }, [roots]);

  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [selectedType, setSelectedType] = useState<"file" | "directory" | null>(null);
  const [clipboard, setClipboard] = useState<ClipboardState | null>(null);
  const [menu, setMenu] = useState<ContextMenuState | null>(null);
  const [pendingCreate, setPendingCreate] = useState<PendingCreate | null>(null);
  const [pendingRename, setPendingRename] = useState<PendingRename | null>(null);
  const [dragOverPath, setDragOverPath] = useState<string | null>(null);
  const dragSrcRef = useRef<{ path: string; type: "file" | "directory" } | null>(null);

  const refreshRoots = useCallback(async () => {
    const expandedPaths = new Set<string>();
    collectExpandedDirPaths(rootsRef.current, expandedPaths);
    const r = await fetchTree("", dataSource);
    const newRoots: TreeNodeData[] = r.children.map((c) => ({
      ...c,
      children: [],
      loaded: false,
      expanded: false,
    }));
    await restoreExpandedDirs(
      newRoots.filter((n) => n.type === "directory"),
      expandedPaths,
      dataSource,
    );
    setRoots(newRoots);
  }, [dataSource]);

  useEffect(() => {
    void fetchTree("", dataSource).then((r) =>
      setRoots(
        r.children.map((c) => ({
          ...c,
          children: [],
          loaded: false,
          expanded: false,
        })),
      ),
    );
  }, [dataSource]);

  useEffect(() => {
    if (refreshToken == null) return;
    void refreshRoots();
  }, [refreshToken, refreshRoots]);

  const toggleNode = useCallback(
    async (target: TreeNodeData) => {
      if (!target.loaded) {
        const r = await fetchTree(target.path, dataSource);
        target.children = r.children.map((c) => ({
          ...c,
          children: [],
          loaded: false,
          expanded: false,
        }));
        target.loaded = true;
      }
      target.expanded = !target.expanded;
      setRoots((prev) => [...prev]);
    },
    [dataSource],
  );

  const expandPath = useCallback(
    async (folderPath: string) => {
      if (!folderPath) return;
      const cur = rootsRef.current;
      const parts = folderPath.split("/");
      let acc = "";
      for (let i = 0; i < parts.length; i++) {
        acc = i === 0 ? parts[0] : `${acc}/${parts[i]}`;
        const node = findNode(cur, acc);
        if (!node || node.type !== "directory") return;
        await loadChildrenIfNeeded(node, dataSource);
        node.expanded = true;
      }
      setRoots([...cur]);
    },
    [dataSource],
  );

  const autoExpandKeyRef = useRef<string>("");
  useEffect(() => {
    const raw = (initialExpandDirectory ?? "").trim();
    if (!raw) {
      autoExpandKeyRef.current = "";
      return;
    }
    if (roots.length === 0) return;
    // Path only (not refreshToken): chat-driven tree reload must not re-select / notify parent again.
    if (autoExpandKeyRef.current === raw) return;
    autoExpandKeyRef.current = raw;
    let cancelled = false;
    void (async () => {
      await expandPath(raw);
      if (cancelled) return;
      const node = findNode(rootsRef.current, raw);
      if (node && node.type === "directory") {
        setSelectedPath(raw);
        setSelectedType("directory");
        onSelectDirectory?.(raw);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [initialExpandDirectory, roots.length, expandPath, onSelectDirectory]);

  const defaultParentForCreate = useCallback((): string => {
    if (!selectedPath) return "";
    if (selectedType === "directory") return selectedPath;
    return parentOf(selectedPath);
  }, [selectedPath, selectedType]);

  const startNewFile = useCallback(async () => {
    const parent = defaultParentForCreate();
    setPendingRename(null);
    await expandPath(parent);
    setPendingCreate({ parentPath: parent, kind: "file" });
  }, [defaultParentForCreate, expandPath]);

  const startNewFolder = useCallback(async () => {
    const parent = defaultParentForCreate();
    setPendingRename(null);
    await expandPath(parent);
    setPendingCreate({ parentPath: parent, kind: "directory" });
  }, [defaultParentForCreate, expandPath]);

  const handleSubmitCreate = useCallback(
    async (name: string) => {
      if (!pendingCreate) return;
      const parent = pendingCreate.parentPath;
      const kind = pendingCreate.kind;
      setPendingCreate(null);
      try {
        const r = await createEntry(dataSource, parent, name, kind);
        await refreshRoots();
        setSelectedPath(r.finalPath);
        setSelectedType(kind === "file" ? "file" : "directory");
        if (kind === "file") onSelect(r.finalPath);
      } catch (e) {
        console.error(e);
        alert(e instanceof Error ? e.message : "Create failed");
      }
    },
    [pendingCreate, dataSource, refreshRoots, onSelect],
  );

  const handleCancelCreate = useCallback(() => {
    setPendingCreate(null);
  }, []);

  const handleSubmitRename = useCallback(
    async (path: string, newName: string) => {
      setPendingRename(null);
      if (!isValidEntryName(newName)) {
        alert("Invalid name");
        return;
      }
      try {
        const r = await renameEntry(dataSource, path, newName);
        await refreshRoots();
        setSelectedPath(r.finalPath);
        if (activePath === path) onSelect(r.finalPath);
      } catch (e) {
        console.error(e);
        alert(e instanceof Error ? e.message : "Rename failed");
      }
    },
    [dataSource, refreshRoots, activePath, onSelect],
  );

  const handleCancelRename = useCallback(() => {
    setPendingRename(null);
  }, []);

  const openContextMenu = useCallback(
    (e: React.MouseEvent, path: string, type: "file" | "directory") => {
      e.preventDefault();
      e.stopPropagation();
      setSelectedPath(path);
      setSelectedType(type);
      setMenu({ x: e.clientX, y: e.clientY, path, type });
    },
    [],
  );

  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    const t = window.setTimeout(() => {
      window.addEventListener("click", close);
    }, 0);
    return () => {
      window.clearTimeout(t);
      window.removeEventListener("click", close);
    };
  }, [menu]);

  const pasteTargetDir = useCallback((path: string, type: "file" | "directory") => {
    return type === "directory" ? path : parentOf(path);
  }, []);

  const handlePaste = useCallback(async () => {
    if (!menu || !clipboard) return;
    const destDir = pasteTargetDir(menu.path, menu.type);
    const clip = clipboard;
    setMenu(null);
    try {
      if (clip.mode === "copy") {
        await copyEntry(dataSource, clip.path, destDir);
      } else {
        const r = await moveEntry(dataSource, clip.path, destDir);
        if (activePath === clip.path) onSelect(r.finalPath);
        setClipboard(null);
      }
      await refreshRoots();
    } catch (e) {
      console.error(e);
      alert(e instanceof Error ? e.message : "Paste failed");
    }
  }, [menu, clipboard, dataSource, activePath, onSelect, refreshRoots, pasteTargetDir]);

  const handleCopy = useCallback(() => {
    if (!menu) return;
    setClipboard({ mode: "copy", path: menu.path });
    setMenu(null);
  }, [menu]);

  const handleCut = useCallback(() => {
    if (!menu) return;
    setClipboard({ mode: "cut", path: menu.path });
    setMenu(null);
  }, [menu]);

  const handleDelete = useCallback(async () => {
    if (!menu) return;
    const p = menu.path;
    setMenu(null);
    if (!window.confirm(`Delete "${basenameOf(p)}"?`)) return;
    try {
      if (activePath && isUnderOrEqual(activePath, p)) onSelect(null);
      await deleteEntry(dataSource, p);
      setSelectedPath(null);
      setSelectedType(null);
      if (clipboard?.path === p) setClipboard(null);
      await refreshRoots();
    } catch (e) {
      console.error(e);
      alert(e instanceof Error ? e.message : "Delete failed");
    }
  }, [menu, dataSource, activePath, onSelect, clipboard, refreshRoots]);

  const handleRename = useCallback(() => {
    if (!menu) return;
    setPendingCreate(null);
    setPendingRename({ path: menu.path, initialName: basenameOf(menu.path) });
    setMenu(null);
  }, [menu]);

  const onDragStart = useCallback(
    (e: React.DragEvent, path: string, type: "file" | "directory") => {
      dragSrcRef.current = { path, type };
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("application/x-session-path", path);
    },
    [],
  );

  const onDragOver = useCallback(
    (e: React.DragEvent, path: string, type: "file" | "directory") => {
      if (type !== "directory") return;
      const src = dragSrcRef.current;
      if (!src) return;
      if (src.path === path) return;
      if (src.type === "directory" && isUnderOrEqual(path, src.path)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      setDragOverPath(path);
    },
    [],
  );

  const onDragLeave = useCallback((e: React.DragEvent, path: string) => {
    const related = e.relatedTarget as Node | null;
    if (related && e.currentTarget.contains(related)) return;
    setDragOverPath((cur) => (cur === path ? null : cur));
  }, []);

  const onDrop = useCallback(
    async (e: React.DragEvent, path: string, type: "file" | "directory") => {
      e.preventDefault();
      setDragOverPath(null);
      const src = dragSrcRef.current;
      dragSrcRef.current = null;
      if (type !== "directory" || !src) return;
      if (src.path === path) return;
      if (src.type === "directory" && isUnderOrEqual(path, src.path)) return;
      const parent = parentOf(src.path);
      if (parent === path) return;
      try {
        const r = await moveEntry(dataSource, src.path, path);
        if (activePath === src.path) onSelect(r.finalPath);
        await refreshRoots();
      } catch (err) {
        console.error(err);
        alert(err instanceof Error ? err.message : "Move failed");
      }
    },
    [dataSource, activePath, onSelect, refreshRoots],
  );

  const selectNode = useCallback(
    (path: string, type: "file" | "directory") => {
      setSelectedPath(path);
      setSelectedType(type);
      if (type === "directory") {
        onSelectDirectory?.(path);
      }
    },
    [onSelectDirectory],
  );

  const rootInputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (pendingCreate?.parentPath === "") {
      rootInputRef.current?.focus();
    }
  }, [pendingCreate]);

  const rootCreateRow =
    pendingCreate?.parentPath === "" ? (
      <div className={`${styles.row} ${styles.inlineRow}`} style={{ paddingLeft: 12 }}>
        <span className={styles.icon} />
        <input
          ref={rootInputRef}
          className={styles.inlineInput}
          placeholder={pendingCreate.kind === "file" ? "filename" : "folder name"}
          defaultValue=""
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              const v = e.currentTarget.value.trim();
              if (v) void handleSubmitCreate(v);
            }
            if (e.key === "Escape") handleCancelCreate();
          }}
          onBlur={(e) => {
            const v = e.target.value.trim();
            if (v) void handleSubmitCreate(v);
            else handleCancelCreate();
          }}
        />
      </div>
    ) : null;

  return (
    <div className={styles.sidebar}>
      <div className={styles.explorerHeader}>
        <span className={styles.explorerTitle}>Explorer</span>
        <div className={styles.explorerActions}>
          <button
            type="button"
            className={styles.iconBtn}
            title="New File"
            aria-label="New File"
            onClick={() => void startNewFile()}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden>
              <path d="M3 2.5h5l2.5 2.5v8.5H3V2.5zm1 1V13h6.5V6H8V3.5H4zm6 1.2L10.2 5H9V3.7H10z" />
              <path d="M11 1h1.5v3.5H11V1zM9.5 2.5H13v1H9.5v-1z" />
            </svg>
          </button>
          <button
            type="button"
            className={styles.iconBtn}
            title="New Folder"
            aria-label="New Folder"
            onClick={() => void startNewFolder()}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden>
              <path d="M2.5 3.5h4.5l1 1.5H13.5V13h-11V3.5zm1 1V12h9V6.5H7.6L6.6 5h-3v-.5zm5.5 1h3v1h-3v-1z" />
            </svg>
          </button>
        </div>
      </div>
      <div className={styles.treeScroll}>
        {rootCreateRow}
        {roots.map((n) => (
          <TreeNode
            key={n.path}
            node={n}
            depth={0}
            activePath={activePath}
            selectedPath={selectedPath}
            pendingCreate={pendingCreate}
            pendingRename={pendingRename}
            clipboard={clipboard}
            dragOverPath={dragOverPath}
            onToggle={toggleNode}
            onSelectNode={selectNode}
            onOpenFile={(p) => onSelect(p)}
            onContextMenu={openContextMenu}
            onDragStart={onDragStart}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
            onSubmitCreate={handleSubmitCreate}
            onCancelCreate={handleCancelCreate}
            onSubmitRename={handleSubmitRename}
            onCancelRename={handleCancelRename}
          />
        ))}
      </div>
      {menu && (
        <div
          className={styles.contextMenu}
          style={{ left: menu.x, top: menu.y }}
          role="menu"
          onClick={(e) => e.stopPropagation()}
        >
          <button type="button" className={styles.menuItem} role="menuitem" onClick={handleCopy}>
            copy
          </button>
          <button
            type="button"
            className={styles.menuItem}
            role="menuitem"
            disabled={!clipboard}
            onClick={() => void handlePaste()}
          >
            paste
          </button>
          <button type="button" className={styles.menuItem} role="menuitem" onClick={handleCut}>
            cut
          </button>
          <button type="button" className={styles.menuItem} role="menuitem" onClick={handleRename}>
            rename
          </button>
          <button type="button" className={styles.menuItem} role="menuitem" onClick={() => void handleDelete()}>
            delete
          </button>
        </div>
      )}
    </div>
  );
}

function isValidEntryName(name: string): boolean {
  if (!name || name === "." || name === "..") return false;
  if (name.includes("/") || name.includes("\\")) return false;
  if (name.startsWith(".")) return false;
  return true;
}
