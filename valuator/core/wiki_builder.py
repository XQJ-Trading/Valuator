import hashlib
import json
import re

from .gemini3 import Gemini3Client
from .hdps import HDPS


H_OV = "\uac1c\uc694"
H_Q = "\ucffc\ub9ac \ubc18\uc601 \uccb4\ud06c\ub9ac\uc2a4\ud2b8"
H_TOC = "\ubaa9\ucc28"
H_BODY = "\ubcf8\ubb38"
H_REL = "\uad00\ub828 \ubb38\uc11c"
H_FOOT = "\uac01\uc8fc / \ucd9c\ucc98"
H_LOG = "\ubcc0\uacbd \uc774\ub825"

H_FACTS = "\uc0ac\uc2e4 / \ub370\uc774\ud130 (\uc6d0\ubb38 \uc694\uc9c0)"
H_INS = "\ud575\uc2ec \uc778\uc0ac\uc774\ud2b8"
H_RISK = "\ub9ac\uc2a4\ud06c / \uac00\uc815"
H_CHILD = "\ud558\uc704 \ubb38\uc11c \uc694\uc57d"
H_DIFF = "\ucc28\uc774\uc810 / \uc815\ud569\uc131"
H_GAP = "\uc7c1\uc810 / \ube48\uce78"
H_DEC = "\ud310\ub2e8 \uadfc\uac70"
H_CNT = "\ub9ac\uc2a4\ud06c / \ubc18\ub840"
H_ACT = "\ub2e4\uc74c \uc561\uc158"

LAB_PARENT = "\uc0c1\uc704"
LAB_CHILD = "\ud558\uc704"

LEAF_SYS = "Return JSON. Write in Korean. Use only provided artifacts."
LEAF_PROMPT = (
    "Task ID: {id}\nTitle: {title}\nDescription: {desc}\nAcceptance: {acc}\n"
    "Query items:\n{query}\n\nArtifacts:\n{artifacts}\n\n"
    "Return JSON with overview,facts,insights,risks.\n"
)
PARENT_SYS = "Return JSON. Write in Korean. Use only provided child summaries."
PARENT_PROMPT = (
    "Role: {role}\nTitle: {title}\nQuery items:\n{query}\n\nChildren:\n{children}\n\n"
    "Return JSON with overview.\n"
)
LEAF_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {"type": "string"},
        "facts": {"type": "array", "items": {"type": "string"}},
        "insights": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["overview", "facts", "insights", "risks"],
}
PARENT_SCHEMA = {
    "type": "object",
    "properties": {"overview": {"type": "string"}},
    "required": ["overview"],
}


class WikiBuilder:
    def __init__(self, hdps: HDPS, client: Gemini3Client | None = None):
        self.hdps = hdps
        self.client = client or Gemini3Client()

    async def update_for_tasks(
        self, plan: dict, query: str, task_ids: list[str]
    ) -> None:
        if not isinstance(plan, dict) or "tasks" not in plan:
            raise ValueError("plan must include tasks")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query is required")
        if not isinstance(task_ids, list):
            raise ValueError("task_ids must be a list")
        (self.hdps.p("output/wiki") / "pages").mkdir(parents=True, exist_ok=True)
        tasks = plan["tasks"]
        task_map, children = _task_maps(tasks)
        qitems = _query_items(query)
        idx = _sync_index(_load_index(self.hdps), tasks, children, qitems)
        dirty = []
        for tid in task_ids:
            task = task_map.get(tid)
            if not task:
                continue
            meta = _meta(task, children)
            if meta["role"] == "leaf":
                changed = await self._update_leaf(meta, qitems, idx)
                if changed and meta["parent"]:
                    dirty.append(meta["parent"])
        dirty = list(dict.fromkeys(dirty))
        idx["dirty_pages"] = dirty
        seen = set()
        queue = list(dirty)
        while queue:
            pid = queue.pop(0)
            if pid in seen:
                continue
            seen.add(pid)
            task = task_map.get(pid)
            if not task:
                continue
            meta = _meta(task, children)
            if not meta["children"]:
                continue
            await self._update_parent(meta, qitems, idx)
            if meta["parent"]:
                queue.append(meta["parent"])
        idx["dirty_pages"] = []
        _write_index(self.hdps, idx)
        _write_index_md(self.hdps, idx)

    async def _update_leaf(self, meta: dict, qitems: list[str], idx: dict) -> bool:
        path = _page_path(self.hdps, meta["id"])
        content = _clean(path.read_text(encoding="utf-8")) if path.exists() else ""
        old_hash = _hash(content) if content else ""
        if not content or f"## {H_OV}" not in content:
            content = _page_skeleton(meta)
        gen = not path.exists() or H_FACTS not in content
        if gen:
            data = await _leaf_sections(
                self.client, meta, qitems, _load_artifacts(self.hdps, meta["id"])
            )
            content = _replace_h2(content, H_OV, data["overview"])
            content = _replace_h3(content, H_FACTS, _bullets(data["facts"]))
            content = _replace_h3(content, H_INS, _bullets(data["insights"]))
            content = _replace_h3(content, H_RISK, _bullets(data["risks"]))
        content = _replace_h2(content, H_TOC, _children_list([]))
        content = _replace_h2(content, H_REL, _related(meta))
        self.hdps.write_atomic(path, content)
        new_hash = _hash(content)
        _touch(idx, meta["id"], new_hash, self.hdps.now())
        return old_hash != new_hash

    async def _update_parent(self, meta: dict, qitems: list[str], idx: dict) -> None:
        path = _page_path(self.hdps, meta["id"])
        content = _clean(path.read_text(encoding="utf-8")) if path.exists() else ""
        if not content or f"## {H_OV}" not in content:
            content = _page_skeleton(meta)
        children = _child_summaries(self.hdps, meta["children"])
        overview = await _parent_overview(self.client, meta, qitems, children)
        content = _replace_h2(content, H_OV, overview)
        content = _replace_h2(content, H_TOC, _children_list(children))
        content = _replace_h2(content, H_REL, _related(meta))
        self.hdps.write_atomic(path, content)
        _touch(idx, meta["id"], _hash(content), self.hdps.now())


def _task_maps(tasks: list[dict]) -> tuple[dict[str, dict], dict[str, list[str]]]:
    task_map = {t["id"]: t for t in tasks}
    children = {tid: [] for tid in task_map}
    for task in tasks:
        parent = task.get("parent_id")
        if parent:
            children.setdefault(parent, []).append(task["id"])
    return task_map, children


def _meta(task: dict, children: dict[str, list[str]]) -> dict:
    tid = task["id"]
    kids = sorted(children.get(tid, []))
    parent = task.get("parent_id")
    role = "leaf" if not kids else ("root" if not parent else "node")
    return {
        "id": tid,
        "title": task.get("title") or tid,
        "desc": task.get("description") or "",
        "acceptance": task.get("acceptance") or [],
        "parent": parent,
        "children": kids,
        "role": role,
        "status": task.get("status") or "PENDING",
    }


def _query_items(query: str) -> list[str]:
    items = []
    bullet = re.compile(r"^[-*]\s+")
    enum = re.compile(r"^\d+(?:[.-][0-9a-zA-Z]+)*\.?\s+")
    for line in query.splitlines():
        line = line.strip()
        if not line:
            continue
        line = enum.sub("", bullet.sub("", line)).strip()
        if line.startswith("**") and line.endswith("**") and len(line) > 4:
            line = line.strip("*").strip()
        if line:
            items.append(line)
    if not items:
        items = [" ".join(query.split())]
    deduped = []
    seen = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def _load_artifacts(hdps: HDPS, task_id: str) -> list[dict]:
    out_dir = hdps.p(f"execution/outputs/{task_id}")
    if not out_dir.exists():
        return []
    items = []
    for path in sorted(out_dir.glob("*")):
        if path.is_dir() or path.name == "artifact_manifest.json":
            continue
        items.append(
            {"name": path.name, "content": path.read_text(encoding="utf-8")[:4000]}
        )
    return items


async def _leaf_sections(
    client: Gemini3Client, meta: dict, qitems: list[str], artifacts: list[dict]
) -> dict:
    prompt = LEAF_PROMPT.format(
        id=meta["id"],
        title=meta["title"],
        desc=meta["desc"] or meta["title"],
        acc="; ".join(meta["acceptance"]),
        query="\n".join(f"- {item}" for item in qitems),
        artifacts=_artifact_text(artifacts) or "(no artifacts)",
    )
    raw = await client.generate(
        prompt,
        system_prompt=LEAF_SYS,
        response_mime_type="application/json",
        response_json_schema=LEAF_SCHEMA,
    )
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise TypeError("leaf response must be an object")
    return {
        "overview": data["overview"].strip(),
        "facts": data["facts"],
        "insights": data["insights"],
        "risks": data["risks"],
    }


async def _parent_overview(
    client: Gemini3Client, meta: dict, qitems: list[str], children: list[dict]
) -> str:
    prompt = PARENT_PROMPT.format(
        role=meta["role"],
        title=meta["title"],
        query="\n".join(f"- {item}" for item in qitems),
        children=_children_text(children),
    )
    raw = await client.generate(
        prompt,
        system_prompt=PARENT_SYS,
        response_mime_type="application/json",
        response_json_schema=PARENT_SCHEMA,
    )
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise TypeError("parent response must be an object")
    return data["overview"].strip()


def _artifact_text(artifacts: list[dict]) -> str:
    return "\n\n".join(f"[{a['name']}]\n{a['content']}" for a in artifacts)


def _children_text(children: list[dict]) -> str:
    return "\n".join(f"- {c['id']} {c['title']}: {c['summary']}" for c in children)


def _page_skeleton(meta: dict) -> str:
    return "\n".join(
        [
            f"# {meta['title']}",
            "",
            f"## {H_OV}",
            "-",
            "",
            f"## {H_TOC}",
            "-",
            "",
            f"## {H_BODY}",
            _body_stub(meta["role"]),
            "",
            f"## {H_REL}",
            "-",
            "",
            f"## {H_FOOT}",
            "-",
            "",
            f"## {H_LOG}",
            "-",
            "",
        ]
    )


def _body_stub(role: str) -> str:
    if role == "leaf":
        return "\n".join(
            [
                f"### {H_FACTS}",
                "-",
                "",
                f"### {H_INS}",
                "-",
                "",
                f"### {H_RISK}",
                "-",
            ]
        )
    if role == "root":
        return "\n".join(
            [
                f"### {H_DEC}",
                "-",
                "",
                f"### {H_CNT}",
                "-",
                "",
                f"### {H_ACT}",
                "-",
            ]
        )
    return "\n".join(
        [
            f"### {H_CHILD}",
            "-",
            "",
            f"### {H_DIFF}",
            "-",
            "",
            f"### {H_GAP}",
            "-",
        ]
    )


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "-"


def _children_list(children: list[dict]) -> str:
    lines = []
    for child in children:
        summary = _first_line(child.get("summary") or "")
        line = f"[[{child['id']}|{child['title']}]]"
        if summary:
            line += f" - {summary}"
        lines.append(line)
    return _bullets(lines)


def _related(meta: dict) -> str:
    lines = []
    if meta["parent"]:
        lines.append(f"{LAB_PARENT}: [[{meta['parent']}|{meta['parent']}]]")
    for child_id in meta["children"]:
        lines.append(f"{LAB_CHILD}: [[{child_id}|{child_id}]]")
    return _bullets(lines)


def _child_summaries(hdps: HDPS, ids: list[str]) -> list[dict]:
    items = []
    for cid in ids:
        path = _page_path(hdps, cid)
        if not path.exists():
            items.append({"id": cid, "title": cid, "summary": ""})
            continue
        content = _clean(path.read_text(encoding="utf-8"))
        items.append(
            {
                "id": cid,
                "title": _title(content) or cid,
                "summary": _section(content, H_OV),
            }
        )
    return items


def _title(content: str) -> str:
    match = re.search(r"^#\s+(.+)$", content, re.M)
    return match.group(1).strip() if match else ""


def _section(content: str, heading: str) -> str:
    match = re.search(
        rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=\n##\s+|\Z)", content, re.S | re.M
    )
    return match.group(1).strip() if match else ""


def _clean(content: str) -> str:
    if not content:
        return content
    content = re.sub(r"<!-- AUTO:[^>]*-->\n?", "", content)
    content = _drop_section(content, H_Q)
    return content.strip()


def _drop_section(content: str, heading: str) -> str:
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$.*?(?=^##\s+|\Z)", re.S | re.M
    )
    return pattern.sub("", content)


def _replace_h2(content: str, heading: str, body: str) -> str:
    pattern = re.compile(
        rf"(^##\s+{re.escape(heading)}\n)(.*?)(?=\n##\s+|\Z)", re.S | re.M
    )
    match = pattern.search(content)
    if not match:
        return content
    start = match.group(1)
    replacement = f"{start}{body}\n"
    return content[: match.start()] + replacement + content[match.end() :]


def _replace_h3(content: str, heading: str, body: str) -> str:
    pattern = re.compile(
        rf"(^###\s+{re.escape(heading)}\n)(.*?)(?=\n###\s+|\n##\s+|\Z)", re.S | re.M
    )
    match = pattern.search(content)
    if not match:
        return content
    start = match.group(1)
    replacement = f"{start}{body}\n"
    return content[: match.start()] + replacement + content[match.end() :]


def _first_line(text: str) -> str:
    compact = " ".join(text.split())
    return compact[:137] + "..." if len(compact) > 140 else compact


def _page_path(hdps: HDPS, task_id: str):
    return hdps.p(f"output/wiki/pages/{task_id}.md")


def _load_index(hdps: HDPS) -> dict:
    path = hdps.p("output/wiki/index.json")
    return (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {"pages": {}, "dirty_pages": []}
    )


def _sync_index(
    index: dict, tasks: list[dict], children: dict[str, list[str]], qitems: list[str]
) -> dict:
    pages = {}
    prev = index.get("pages", {})
    for task in tasks:
        meta = _meta(task, children)
        old = prev.get(meta["id"], {})
        pages[meta["id"]] = {
            "id": meta["id"],
            "title": meta["title"],
            "level": task.get("level"),
            "role": meta["role"],
            "parents": [meta["parent"]] if meta["parent"] else [],
            "children": meta["children"],
            "status": meta["status"],
            "query": qitems,
            "content_hash": old.get("content_hash", ""),
            "last_updated": old.get("last_updated", ""),
        }
    index["pages"] = pages
    index.setdefault("dirty_pages", [])
    return index


def _write_index(hdps: HDPS, index: dict) -> None:
    hdps.write_atomic(
        hdps.p("output/wiki/index.json"),
        json.dumps(index, indent=2, ensure_ascii=False) + "\n",
    )


def _write_index_md(hdps: HDPS, index: dict) -> None:
    roots = [p for p in index.get("pages", {}).values() if not p.get("parents")]
    lines = ["# Index", ""]
    for page in sorted(roots, key=lambda p: p.get("id", "")):
        lines.append(f"- [[{page['id']}|{page.get('title', page['id'])}]]")
    hdps.write_atomic(hdps.p("output/wiki/index.md"), "\n".join(lines))


def _touch(index: dict, task_id: str, content_hash: str, ts: str) -> None:
    page = index["pages"][task_id]
    page["content_hash"] = content_hash
    page["last_updated"] = ts


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
