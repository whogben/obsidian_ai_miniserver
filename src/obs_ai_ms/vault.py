from __future__ import annotations

import hmac
import json
import re
import secrets
import shutil
from datetime import datetime
from pathlib import Path

from .models import (
    AdminListUsers,
    AdminUpsertUser,
    AppendText,
    Error,
    FileText,
    FilesList,
    GetVaultInfo,
    ListFiles,
    MoveFile,
    PathAccess,
    ReadText,
    ReplaceText,
    SearchFiles,
    SearchResults,
    ServerRequest,
    ServerResponse,
    Success,
    User,
    UsersList,
    VaultInfo,
    WriteText,
)


class Vault:
    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path).resolve()
        self._config_path = self.vault_path / ".obsidian" / "obsidian_ai_miniserver.json"
        self._handlers = {
            "get_vault_info": self._get_vault_info,
            "read_text": self._read_text,
            "write_text": self._write_text,
            "append_text": self._append_text,
            "replace_text": self._replace_text,
            "move_file": self._move_file,
            "list_files": self._list_files,
            "search_files": self._search_files,
            "list_users": self._list_users,
            "upsert_user": self._upsert_user,
        }
        self._load_config()
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._save_config()

    def _load_config(self):
        if self._config_path.exists():
            data = json.loads(self._config_path.read_text())
            self.users = [User(**u) for u in data.get("users", [])]
        else:
            self.users = [User()]
            self._save_config()

    def _save_config(self):
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps({"users": [u.model_dump() for u in self.users]}, indent=2)
        )

    def _resolve(self, rel: str) -> Path:
        resolved = (self.vault_path / rel).resolve()
        if not resolved.is_relative_to(self.vault_path.resolve()):
            raise ValueError(f"Path escapes vault: {rel}")
        return resolved

    def _daily_notes_folder(self) -> str:
        path = self.vault_path / ".obsidian" / "daily-notes.json"
        if path.exists():
            return json.loads(path.read_text()).get("folder", "")
        return ""

    def authenticate(self, token: str) -> User | None:
        for u in self.users:
            if u.token and hmac.compare_digest(u.token, token):
                return u
        return None

    def check_access(self, user: User, path: str, write: bool) -> bool:
        if user.is_admin:
            return True
        norm_path = path.rstrip("/")
        for rule in user.access:
            norm_rule = rule.path.rstrip("/")
            if norm_path != norm_rule and not norm_path.startswith(norm_rule + "/"):
                continue
            if not rule.recursive and norm_path != norm_rule:
                continue
            if write and not rule.write:
                continue
            if not write and not rule.read:
                continue
            return True
        return False

    def obsidian(self, requests: list[ServerRequest], user: User) -> list[ServerResponse]:
        results: list[ServerResponse] = []
        for request in requests:
            results.append(self._handle_one(request, user))
        return results

    def _handle_one(self, request: ServerRequest, user: User) -> ServerResponse:
        # Admin-only operations
        if request.kind in ("list_users", "upsert_user") and not user.is_admin:
            return Error(message="Access denied")

        # Path-based access control
        if request.kind not in ("get_vault_info", "list_users", "upsert_user"):
            write = request.kind in ("write_text", "append_text", "replace_text", "move_file")
            if request.kind == "move_file":
                check_paths = [request.old_path]
            else:
                check_paths = [request.path]
            for p in check_paths:
                if not self.check_access(user, p, write):
                    return Error(message="Access denied")
            if request.kind == "move_file" and request.new_path:
                if not self.check_access(user, request.new_path, True):
                    return Error(message="Access denied")

        handler = self._handlers.get(request.kind)
        if not handler:
            return Error(message=f"Unsupported request: {request.kind}")

        try:
            if request.kind == "get_vault_info":
                return handler(request, user)
            return handler(request)
        except ValueError:
            return Error(message="Invalid path")

    def _get_vault_info(self, _req: GetVaultInfo, user: User) -> VaultInfo:
        safe_user = user.model_copy(update={"token": ""})
        return VaultInfo(
            name=self.vault_path.name,
            daily_notes_folder=self._daily_notes_folder(),
            user=safe_user,
        )

    def _read_text(self, req: ReadText) -> FileText | Error:
        resolved = self._resolve(req.path)
        if not resolved.is_file():
            return Error(message=f"File not found: {req.path}")
        text = resolved.read_text()
        modified = datetime.fromtimestamp(resolved.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        limit = len(text) if req.limit == -1 else req.limit
        return FileText(
            text=text[req.offset : req.offset + limit],
            length=len(text),
            modified_at=modified,
            offset=req.offset,
            limit=limit,
        )

    def _write_text(self, req: WriteText) -> Success:
        path = self._resolve(req.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(req.text)
        return Success()

    def _append_text(self, req: AppendText) -> Success | Error:
        path = self._resolve(req.path)
        if not path.is_file():
            return Error(message=f"File not found: {req.path}")
        path.write_text(path.read_text(encoding="utf-8") + req.text, encoding="utf-8")
        return Success()

    def _replace_text(self, req: ReplaceText) -> Success | Error:
        path = self._resolve(req.path)
        if not path.is_file():
            return Error(message=f"File not found: {req.path}")
        text = path.read_text()
        if req.old_text not in text:
            return Error(message=f"Text not found in file: {req.path}")
        path.write_text(text.replace(req.old_text, req.new_text, req.count))
        return Success()

    def _move_file(self, req: MoveFile) -> Success | Error:
        old = self._resolve(req.old_path)
        if not old.exists():
            return Error(message=f"File not found: {req.old_path}")
        if not req.new_path:
            old.unlink()
            return Success()
        new = self._resolve(req.new_path)
        if new.exists():
            return Error(message=f"File already exists: {req.new_path}")
        new.parent.mkdir(parents=True, exist_ok=True)
        if req.make_copy:
            shutil.copy2(old, new)
        else:
            shutil.move(str(old), str(new))
        return Success()

    def _list_files(self, req: ListFiles) -> FilesList | Error:
        base = self._resolve(req.path)
        if not base.is_dir():
            return Error(message=f"Directory not found: {req.path}")
        # (rel_path, modified_str, size, formatted_line)
        entries: list[tuple[str, str, int, str]] = []
        self._walk(base, req.extensions, req.max_depth, 0, req.path, entries)
        key_idx = {"name": 0, "modified": 1, "length": 2}[req.sort_by]
        entries.sort(key=lambda e: e[key_idx], reverse=req.sort_order == "desc")
        results = [e[3] for e in entries]
        total = len(results)
        offset = req.offset
        limit = total if req.limit == -1 else req.limit
        return FilesList(
            base_path=req.path,
            results=results[offset : offset + limit],
            length=total,
            offset=offset,
            limit=limit,
        )

    def _walk(
        self,
        dir_path: Path,
        extensions: list[str],
        max_depth: int,
        depth: int,
        rel_prefix: str,
        out: list[tuple[str, str, int, str]],
    ):
        if max_depth != -1 and depth >= max_depth:
            return
        try:
            children = sorted(dir_path.iterdir(), key=lambda e: e.name)
        except PermissionError:
            return
        for child in children:
            if child.name.startswith("."):
                continue
            rel = f"{rel_prefix}/{child.name}" if rel_prefix else child.name
            stat = child.stat()
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            if child.is_dir():
                out.append((rel, modified, 0, f"{rel} | {modified} | 0 b"))
                self._walk(child, extensions, max_depth, depth + 1, rel, out)
            elif child.is_file() and (not extensions or child.suffix in extensions):
                size = stat.st_size
                unit = "chars" if child.suffix in (".md", ".txt") else "b"
                out.append((rel, modified, size, f"{rel} | {modified} | {size} {unit}"))

    def _search_files(self, req: SearchFiles) -> SearchResults | Error:
        base = self._resolve(req.path)
        if not base.is_dir():
            return Error(message=f"Directory not found: {req.path}")
        try:
            pattern = re.compile(req.pattern)
        except re.error as e:
            return Error(message=f"Invalid regex: {e}")
        matches: list[str] = []
        self._search_walk(base, req.extensions, req.max_depth, 0, req.path, pattern, req.context_chars, matches)
        total = len(matches)
        limit = total if req.limit == -1 else req.limit
        return SearchResults(
            results=matches[req.offset : req.offset + limit],
            length=total,
            offset=req.offset,
            limit=limit,
        )

    def _search_walk(
        self,
        dir_path: Path,
        extensions: list[str],
        max_depth: int,
        depth: int,
        rel_prefix: str,
        pattern: re.Pattern,
        context_chars: int,
        out: list[str],
    ):
        if max_depth != -1 and depth >= max_depth:
            return
        try:
            children = sorted(dir_path.iterdir(), key=lambda e: e.name)
        except PermissionError:
            return
        for child in children:
            if child.name.startswith("."):
                continue
            rel = f"{rel_prefix}/{child.name}" if rel_prefix else child.name
            if child.is_dir():
                self._search_walk(child, extensions, max_depth, depth + 1, rel, pattern, context_chars, out)
            elif child.is_file() and (not extensions or child.suffix in extensions):
                # Match filename
                for m in pattern.finditer(child.name):
                    out.append(f"{rel}:0 | {m.group()} | (filename)")
                # Match file contents
                try:
                    for i, line in enumerate(child.read_text().splitlines(), 1):
                        for m in pattern.finditer(line):
                            half = context_chars // 2
                            ctx = line[max(0, m.start() - half) : m.end() + half]
                            out.append(f"{rel}:{i} | {m.group()} | {ctx}")
                except (UnicodeDecodeError, PermissionError):
                    continue

    def _list_users(self, _req: AdminListUsers) -> UsersList:
        return UsersList(users=self.users)

    def _upsert_user(self, req: AdminUpsertUser) -> Success | Error:
        existing = next((u for u in self.users if u.username == req.username), None)

        if req.delete_user:
            if not existing:
                return Error(message=f"User not found: {req.username}")
            if self.users.index(existing) == 0:
                return Error(message="Cannot remove admin user")
            self.users.remove(existing)
            self._save_config()
            return Success()

        if existing:
            updates = {}
            if req.token is not None:
                updates["token"] = req.token
            if req.access is not None:
                updates["access"] = req.access
            if req.is_admin is not None:
                updates["is_admin"] = req.is_admin
            idx = self.users.index(existing)
            self.users[idx] = existing.model_copy(update=updates)
            self._save_config()
            return Success()

        token = req.token or secrets.token_urlsafe(16)
        self.users.append(User(
            username=req.username,
            token=token,
            access=req.access or [PathAccess()],
            is_admin=bool(req.is_admin),
        ))
        self._save_config()
        return Success(message=f"Created user '{req.username}' with token: {token}")
