from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, field_validator

router = APIRouter()

MAX_CONFLICT_TRIES = 10000
MAX_FILE_SIZE = 2 * 1024 * 1024
VALID_SOURCES = {"session", "guide"}


def session_data_root() -> Path:
    configured = os.getenv("SESSION_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return (
        Path(__file__).resolve().parents[1] / "Researcher-UI-Demo" / "session-data"
    ).resolve()


def guide_data_root() -> Path:
    configured = os.getenv("GUIDE_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return (
        Path(__file__).resolve().parents[1] / "Researcher-UI-Demo" / "guide-data"
    ).resolve()


def ensure_viewer_roots() -> None:
    session_data_root().mkdir(parents=True, exist_ok=True)
    guide_data_root().mkdir(parents=True, exist_ok=True)


def _root_for_source(source: str) -> Path:
    return session_data_root() if source == "session" else guide_data_root()


def _safe_path(rel_path: str, base_root: Path) -> Path | None:
    resolved = (base_root / rel_path).resolve()
    try:
        resolved.relative_to(base_root)
    except ValueError:
        return None
    return resolved


def _require_source(source: str | None) -> str:
    if source in VALID_SOURCES:
        return source
    raise HTTPException(
        status_code=400, detail="invalid or missing source (session|guide)"
    )


def _require_path(rel_path: str) -> str:
    if rel_path:
        return rel_path
    raise HTTPException(status_code=400, detail="path required")


def _resolve_source_base_root(source: str | None) -> tuple[str, Path]:
    resolved_source = _require_source(source)
    return resolved_source, _root_for_source(resolved_source)


def _resolve_abs_path(
    *, base_root: Path, rel_path: str, not_found_detail: str = "not found"
) -> Path:
    abs_path = _safe_path(rel_path, base_root)
    if abs_path is None:
        raise HTTPException(status_code=403, detail="forbidden")
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail=not_found_detail)
    return abs_path


def _to_rel_posix(abs_path: Path, base_root: Path) -> str:
    rel = abs_path.relative_to(base_root)
    if str(rel) == ".":
        return ""
    return rel.as_posix()


def _parent_rel_path(rel_path: str) -> str:
    if "/" not in rel_path:
        return ""
    return rel_path.rsplit("/", 1)[0]


def _basename_rel(rel_path: str) -> str:
    return rel_path.rsplit("/", 1)[-1]


def _is_valid_entry_name(name: str) -> bool:
    if not name or name in {".", ".."}:
        return False
    if "/" in name or "\\" in name:
        return False
    return not name.startswith(".")


def _is_descendant_or_equal_dir(candidate: Path, ancestor: Path) -> bool:
    try:
        candidate.resolve().relative_to(ancestor.resolve())
    except ValueError:
        return False
    return True


def _resolve_non_conflict_name(dir_abs: Path, desired_name: str) -> str:
    ext = Path(desired_name).suffix
    base = desired_name[: -len(ext)] if ext else desired_name
    candidate = desired_name
    for index in range(MAX_CONFLICT_TRIES):
        if not (dir_abs / candidate).exists():
            return candidate
        if index == 0:
            candidate = f"{base} (copy){ext}" if ext else f"{desired_name} (copy)"
        else:
            candidate = (
                f"{base} (copy {index + 1}){ext}"
                if ext
                else f"{desired_name} (copy {index + 1})"
            )
    raise HTTPException(status_code=500, detail="could not resolve unique name")


def _copy_entry_to_dir(
    src_abs: Path, dest_parent_abs: Path, desired_name: str, base_root: Path
) -> dict[str, str]:
    final_name = _resolve_non_conflict_name(dest_parent_abs, desired_name)
    dest_abs = dest_parent_abs / final_name
    if src_abs.is_dir():
        shutil.copytree(src_abs, dest_abs)
    else:
        shutil.copy2(src_abs, dest_abs)
    return {"finalPath": _to_rel_posix(dest_abs, base_root), "name": final_name}


class SourceRequest(BaseModel):
    source: str

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        if value not in VALID_SOURCES:
            raise ValueError("invalid or missing source (session|guide)")
        return value


class CreateEntryRequest(SourceRequest):
    parentPath: str = ""
    name: str
    kind: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not _is_valid_entry_name(value):
            raise ValueError("invalid name")
        return value

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        if value not in {"file", "directory"}:
            raise ValueError("kind must be file|directory")
        return value


class RenameEntryRequest(SourceRequest):
    path: str
    newName: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _require_path(value)

    @field_validator("newName")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not _is_valid_entry_name(value):
            raise ValueError("invalid newName")
        return value


class DeleteEntryRequest(SourceRequest):
    path: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _require_path(value)


class MoveCopyEntryRequest(DeleteEntryRequest):
    targetDirPath: str = ""


class SaveFileRequest(DeleteEntryRequest):
    content: str


@router.post("/api/fs/create")
async def create_entry(request: CreateEntryRequest):
    base_root = _root_for_source(request.source)
    parent_abs = _resolve_abs_path(
        base_root=base_root,
        rel_path=request.parentPath,
        not_found_detail="parent not found",
    )
    if not parent_abs.is_dir():
        raise HTTPException(status_code=400, detail="parent is not a directory")

    final_name = _resolve_non_conflict_name(parent_abs, request.name)
    abs_path = parent_abs / final_name
    if request.kind == "directory":
        abs_path.mkdir()
    else:
        abs_path.write_text("", encoding="utf-8")
    rel_path = _to_rel_posix(abs_path, base_root)
    return {"path": rel_path, "finalPath": rel_path, "name": final_name}


@router.post("/api/fs/rename")
async def rename_entry(request: RenameEntryRequest):
    base_root = _root_for_source(request.source)
    abs_path = _resolve_abs_path(base_root=base_root, rel_path=request.path)

    dest_abs = abs_path.parent / request.newName
    if dest_abs == abs_path:
        return {
            "path": request.path,
            "finalPath": request.path,
            "name": request.newName,
        }
    if dest_abs.exists():
        raise HTTPException(status_code=409, detail="target exists")

    abs_path.rename(dest_abs)
    final_path = _to_rel_posix(dest_abs, base_root)
    return {"path": request.path, "finalPath": final_path, "name": request.newName}


@router.post("/api/fs/delete")
async def delete_entry(request: DeleteEntryRequest):
    base_root = _root_for_source(request.source)
    abs_path = _resolve_abs_path(base_root=base_root, rel_path=request.path)

    if abs_path.is_dir():
        shutil.rmtree(abs_path)
    else:
        abs_path.unlink()
    return {"path": request.path, "finalPath": "", "name": _basename_rel(request.path)}


@router.post("/api/fs/move")
async def move_entry(request: MoveCopyEntryRequest):
    base_root = _root_for_source(request.source)
    src_abs = _safe_path(request.path, base_root)
    target_dir_abs = _safe_path(request.targetDirPath, base_root)
    if src_abs is None or target_dir_abs is None:
        raise HTTPException(status_code=403, detail="forbidden")
    if _parent_rel_path(request.path) == request.targetDirPath:
        return {
            "path": request.path,
            "finalPath": request.path,
            "name": _basename_rel(request.path),
        }
    if not target_dir_abs.exists():
        raise HTTPException(status_code=404, detail="target dir not found")
    if not target_dir_abs.is_dir():
        raise HTTPException(status_code=400, detail="target is not a directory")
    if not src_abs.exists():
        raise HTTPException(status_code=404, detail="not found")
    if src_abs.is_dir() and _is_descendant_or_equal_dir(target_dir_abs, src_abs):
        raise HTTPException(status_code=400, detail="cannot move into self")

    final_name = _resolve_non_conflict_name(target_dir_abs, _basename_rel(request.path))
    dest_abs = target_dir_abs / final_name
    try:
        shutil.move(str(src_abs), str(dest_abs))
    except Exception as exc:
        raise HTTPException(status_code=500, detail="move failed") from exc
    final_path = _to_rel_posix(dest_abs, base_root)
    return {"path": request.path, "finalPath": final_path, "name": final_name}


@router.post("/api/fs/copy")
async def copy_entry(request: MoveCopyEntryRequest):
    base_root = _root_for_source(request.source)
    src_abs = _safe_path(request.path, base_root)
    target_dir_abs = _safe_path(request.targetDirPath, base_root)
    if src_abs is None or target_dir_abs is None:
        raise HTTPException(status_code=403, detail="forbidden")
    if not target_dir_abs.exists():
        raise HTTPException(status_code=404, detail="target dir not found")
    if not target_dir_abs.is_dir():
        raise HTTPException(status_code=400, detail="target is not a directory")
    if not src_abs.exists():
        raise HTTPException(status_code=404, detail="not found")
    if src_abs.is_dir() and _is_descendant_or_equal_dir(target_dir_abs, src_abs):
        raise HTTPException(status_code=400, detail="cannot copy into self")

    try:
        result = _copy_entry_to_dir(
            src_abs, target_dir_abs, _basename_rel(request.path), base_root
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail="copy failed") from exc
    return {"path": request.path, **result}


@router.get("/api/tree")
async def get_tree(
    source: str | None = Query(default=None),
    path: str = Query(default=""),
):
    _, base_root = _resolve_source_base_root(source)
    abs_path = _resolve_abs_path(base_root=base_root, rel_path=path)
    if not abs_path.is_dir():
        raise HTTPException(status_code=404, detail="not found")

    children = []
    entries = sorted(
        (entry for entry in abs_path.iterdir() if not entry.name.startswith(".")),
        key=lambda entry: (not entry.is_dir(), entry.name.lower()),
    )
    for entry in entries:
        children.append(
            {
                "name": entry.name,
                "path": f"{path}/{entry.name}" if path else entry.name,
                "type": "directory" if entry.is_dir() else "file",
                "ext": entry.suffix.lower() if entry.is_file() else None,
            }
        )
    return {"path": path or "/", "children": children}


def _collect_all_entries(root_abs: Path, source: str) -> list[dict[str, str]]:
    if not root_abs.exists() or not root_abs.is_dir():
        return []

    out: list[dict[str, str]] = []

    def walk(dir_abs: Path, rel_from_root: str) -> None:
        try:
            entries = sorted(dir_abs.iterdir(), key=lambda entry: entry.name.lower())
        except OSError:
            return
        for entry in entries:
            if entry.name.startswith("."):
                continue
            rel_path = f"{rel_from_root}/{entry.name}" if rel_from_root else entry.name
            if entry.is_dir():
                out.append(
                    {
                        "name": entry.name,
                        "path": rel_path,
                        "source": source,
                        "type": "directory",
                    }
                )
                walk(entry, rel_path)
            elif entry.is_file():
                out.append(
                    {
                        "name": entry.name,
                        "path": rel_path,
                        "source": source,
                        "type": "file",
                    }
                )

    walk(root_abs, "")
    return out


def _search_score(query: str, entry: dict[str, str]) -> int:
    name_lc = entry["name"].lower()
    path_lc = entry["path"].lower()
    if name_lc == query:
        return 0
    if name_lc.startswith(query):
        return 1
    if query in name_lc:
        return 2
    if query in path_lc:
        return 3
    return 999


@router.get("/api/search")
async def search_files(
    q: str = Query(default=""),
    limit: int = Query(default=5),
):
    query = q.strip().lower()
    clamped_limit = min(50, max(1, limit))
    all_entries = _collect_all_entries(session_data_root(), "session")
    all_entries.extend(_collect_all_entries(guide_data_root(), "guide"))

    if not query:
        all_entries.sort(key=lambda entry: entry["path"])
        return {"results": all_entries[:clamped_limit]}

    ranked: list[tuple[int, dict[str, str]]] = []
    for entry in all_entries:
        score = _search_score(query, entry)
        if score < 999:
            ranked.append((score, entry))
    ranked.sort(key=lambda item: (item[0], item[1]["path"]))
    return {"results": [entry for _, entry in ranked[:clamped_limit]]}


@router.get("/api/file")
async def get_file(
    source: str | None = Query(default=None),
    path: str = Query(default=""),
):
    _, base_root = _resolve_source_base_root(source)
    rel_path = _require_path(path)
    abs_path = _resolve_abs_path(base_root=base_root, rel_path=rel_path)
    if abs_path.is_dir():
        raise HTTPException(status_code=400, detail="is a directory")

    size = abs_path.stat().st_size
    if size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="file too large")
    content = abs_path.read_text(encoding="utf-8")
    return {
        "path": rel_path,
        "ext": abs_path.suffix.lower(),
        "size": size,
        "content": content,
    }


@router.put("/api/file")
async def save_file(request: SaveFileRequest):
    size = len(request.content.encode("utf-8"))
    if size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="file too large")

    base_root = _root_for_source(request.source)
    abs_path = _resolve_abs_path(base_root=base_root, rel_path=request.path)
    if abs_path.is_dir():
        raise HTTPException(status_code=400, detail="is a directory")

    try:
        abs_path.write_text(request.content, encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail="write failed") from exc
    return {
        "path": request.path,
        "ext": abs_path.suffix.lower(),
        "size": abs_path.stat().st_size,
        "content": request.content,
    }
