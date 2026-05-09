from __future__ import annotations

import hmac
import json
import re
import secrets
import shutil
from datetime import datetime
from pathlib import Path

from platformdirs import user_config_dir

from .models import (
    AdminListUsers,
    AdminUpsertUser,
    AdminUpsertVault,
    AppendText,
    Error,
    FileText,
    FilesList,
    GetVaultsInfo,
    ListFiles,
    MoveFile,
    PathAccess,
    ReadText,
    ReplaceText,
    SearchFiles,
    SearchResults,
    ServerConfig,
    ServerRequest,
    ServerResponse,
    Success,
    User,
    UsersList,
    VaultConfig,
    VaultsInfo,
    WriteText,
)


class PathEscapeError(ValueError):
    pass


class Vault:
    def __init__(self, config_path: str | None = None):
        self._config_path = (
            Path(config_path)
            if config_path
            else Path(user_config_dir("obsidian_ai_miniserver")) / "config.json"
        )
        self._handlers = {
            "get_vault_info": self._get_vaults_info,
            "read_text": self._read_text,
            "write_text": self._write_text,
            "append_text": self._append_text,
            "replace_text": self._replace_text,
            "move_file": self._move_file,
            "list_files": self._list_files,
            "search_files": self._search_files,
            "list_users": self._list_users,
            "upsert_user": self._upsert_user,
            "upsert_vault": self._upsert_vault,
        }
        self._load_config()
        self.sync_manager = None  # type: ignore  # Set by entry.py

    def ensure_sync_manager(self):
        """Create and start SyncManager if credentials + sync vaults exist but manager is None."""
        if self.sync_manager is not None:
            return
        has_sync = any(v.dir_path.startswith("sync:") for v in self.config.vaults)
        if has_sync and self.config.obs_username:
            from .sync import SyncManager
            self.sync_manager = SyncManager(
                self.config.obs_username, self.config.obs_password, self.config.vaults
            )
            self.sync_manager.start()

    @property
    def users(self) -> list[User]:
        return self.config.users

    def _load_config(self):
        if self._config_path.exists():
            self.config = ServerConfig.model_validate_json(self._config_path.read_text())
        else:
            token = secrets.token_urlsafe(16)
            print("Initialized config — set OBS_AI_MS_ADMIN_TOKEN or see config.json for admin token")
            self.config = ServerConfig(users=[User(token=token)])
            self._save_config()

    def _save_config(self):
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._config_path.with_suffix(".tmp")
        tmp.write_text(self.config.model_dump_json(indent=2))
        tmp.replace(self._config_path)

    # -- Vault management --

    def register_vault(self, name: str, dir_path: str):
        if dir_path.startswith("sync:") and len(dir_path) <= 5:
            raise ValueError("sync: path must include a directory, e.g. sync:/vaults/MyNotes")
        if dir_path.startswith("sync:"):
            resolved = "sync:" + str(Path(dir_path[5:]).resolve())
        else:
            resolved = str(Path(dir_path).resolve())
        for i, v in enumerate(self.config.vaults):
            if v.name == name:
                return
            if v.dir_path == resolved:
                self.config.vaults[i] = v.model_copy(update={"name": name})
                self._save_config()
                return
        self.config.vaults.append(VaultConfig(name=name, dir_path=resolved))
        self._save_config()

    def _resolve_dir_path(self, vc: VaultConfig) -> str:
        """Return the actual filesystem path, stripping any sync: prefix."""
        if vc.dir_path.startswith("sync:"):
            return vc.dir_path[5:]
        return vc.dir_path

    def _compute_status(self, vc: VaultConfig) -> str:
        dir_path = self._resolve_dir_path(vc)
        p = Path(dir_path)
        if not p.exists():
            if vc.dir_path.startswith("sync:"):
                return "sync pending"
            return f"unavailable - missing dir {dir_path}"
        if not (p / ".obsidian").exists():
            return f"unavailable - dir not a vault {dir_path}"
        return "ok"

    def _daily_notes_folder(self, vc: VaultConfig) -> str:
        dir_path = self._resolve_dir_path(vc)
        path = Path(dir_path) / ".obsidian" / "daily-notes.json"
        if path.exists():
            return json.loads(path.read_text()).get("folder", "")
        return ""

    # -- Vault-aware path resolution --

    def _user_vaults(self, user: User) -> list[VaultConfig]:
        """Vaults the user can potentially access."""
        if user.is_admin:
            return list(self.config.vaults)
        result = []
        for v in self.config.vaults:
            for rule in user.access:
                if ":" in rule.path:
                    rv, _ = rule.path.split(":", 1)
                    if rv == "*" or rv == v.name:
                        result.append(v)
                        break
        return result

    def _parse_path(self, user: User, path: str) -> list[tuple[VaultConfig, str]] | Error:
        user_vaults = self._user_vaults(user)

        # Wildcard or empty — all accessible vaults
        if not path or path == "*:":
            if not user_vaults:
                return Error(message="No accessible vaults")
            return [(v, "") for v in user_vaults]

        # Explicit vault prefix
        if ":" in path:
            vault_name, rel_path = path.split(":", 1)
            if vault_name == "*":
                if not user_vaults:
                    return Error(message="No accessible vaults")
                return [(v, rel_path) for v in user_vaults]
            vault = next((v for v in user_vaults if v.name == vault_name), None)
            if not vault:
                return Error(message=f"Vault not found or access denied: {vault_name}")
            return [(vault, rel_path)]

        # No prefix — single-vault shortcut
        if len(user_vaults) == 1:
            return [(user_vaults[0], path)]
        if not user_vaults:
            return Error(message="No accessible vaults")
        return Error(message="Ambiguous path — specify vault, e.g. 'vaultname:path'")

    def _resolve(self, vault_config: VaultConfig, rel: str) -> Path:
        base = Path(self._resolve_dir_path(vault_config)).resolve()
        resolved = (base / rel).resolve()
        if not resolved.is_relative_to(base):
            raise PathEscapeError(f"Path escapes vault: {rel}")
        return resolved

    # -- Auth & access --

    def authenticate(self, token: str) -> User | None:
        for u in self.config.users:
            if u.token and hmac.compare_digest(u.token, token):
                return u
        return None

    def check_access(self, user: User, vault_name: str, path: str, write: bool) -> bool:
        if user.is_admin:
            return True
        norm_path = path.rstrip("/")
        for rule in user.access:
            if ":" in rule.path:
                rule_vault, rule_rel = rule.path.split(":", 1)
                if rule_vault != "*" and rule_vault != vault_name:
                    continue
                norm_rule = rule_rel.rstrip("/")
            else:
                # Non-prefixed rules only apply in single-vault mode
                if len(self.config.vaults) > 1:
                    continue
                norm_rule = rule.path.rstrip("/")
            if norm_rule and norm_path != norm_rule and not norm_path.startswith(norm_rule + "/"):
                continue
            if not rule.recursive and norm_path != norm_rule:
                continue
            if write and not rule.write:
                continue
            if not write and not rule.read:
                continue
            return True
        return False

    # -- Dispatch --

    def obsidian(self, requests: list[ServerRequest], user: User) -> list[ServerResponse]:
        return [self._handle_one(r, user) for r in requests]

    def _handle_one(self, request: ServerRequest, user: User) -> ServerResponse:
        # Admin-only operations
        if request.kind in ("list_users", "upsert_user", "upsert_vault") and not user.is_admin:
            return Error(message="Access denied")

        # Path-based access control
        if request.kind not in ("get_vault_info", "list_users", "upsert_user", "upsert_vault"):
            write = request.kind in ("write_text", "append_text", "replace_text", "move_file")
            paths = [request.old_path] if request.kind == "move_file" else [request.path]
            for p in paths:
                parsed = self._parse_path(user, p)
                if isinstance(parsed, Error):
                    return parsed
                for vault, rel in parsed:
                    if not self.check_access(user, vault.name, rel, write):
                        return Error(message="Access denied")
            if request.kind == "move_file" and request.new_path:
                parsed = self._parse_path(user, request.new_path)
                if isinstance(parsed, Error):
                    return parsed
                for vault, rel in parsed:
                    if not self.check_access(user, vault.name, rel, True):
                        return Error(message="Access denied")

        handler = self._handlers.get(request.kind)
        if not handler:
            return Error(message=f"Unsupported request: {request.kind}")

        try:
            return handler(request, user)
        except PathEscapeError:
            return Error(message="Invalid path")

    # -- Handlers --

    def _get_vaults_info(self, _req, user: User) -> VaultsInfo:
        safe_user = user.model_copy(update={"token": ""})
        vaults = [
            v.model_copy(update={
                "status": self._compute_status(v),
                "daily_notes_folder": self._daily_notes_folder(v),
            })
            for v in self._user_vaults(user)
        ]
        msg = 'Paths: "vault:path", "*:" or "" = all.' if len(vaults) >= 2 else ""
        if user.is_admin and self.sync_manager is not None:
            line = self.sync_manager.get_latest_line()
            if line is not None:
                msg = f"{msg}\nobs active: {line}" if msg else f"obs active: {line}"
        return VaultsInfo(vaults=vaults, user=safe_user, message=msg)

    def _read_text(self, req, user: User) -> FileText | Error:
        parsed = self._parse_path(user, req.path)
        if isinstance(parsed, Error):
            return parsed
        vault, rel = parsed[0]
        resolved = self._resolve(vault, rel)
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

    def _write_text(self, req, user: User) -> Success | Error:
        parsed = self._parse_path(user, req.path)
        if isinstance(parsed, Error):
            return parsed
        vault, rel = parsed[0]
        path = self._resolve(vault, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(req.text)
        return Success()

    def _append_text(self, req, user: User) -> Success | Error:
        parsed = self._parse_path(user, req.path)
        if isinstance(parsed, Error):
            return parsed
        vault, rel = parsed[0]
        path = self._resolve(vault, rel)
        if not path.is_file():
            return Error(message=f"File not found: {req.path}")
        existing = path.read_text(encoding="utf-8")
        path.write_text(
            (req.text + existing) if req.prepend else (existing + req.text),
            encoding="utf-8",
        )
        return Success()

    def _replace_text(self, req, user: User) -> Success | Error:
        parsed = self._parse_path(user, req.path)
        if isinstance(parsed, Error):
            return parsed
        vault, rel = parsed[0]
        path = self._resolve(vault, rel)
        if not path.is_file():
            return Error(message=f"File not found: {req.path}")
        text = path.read_text()
        if req.old_text not in text:
            return Error(message=f"Text not found in file: {req.path}")
        path.write_text(text.replace(req.old_text, req.new_text, req.count))
        return Success()

    def _move_file(self, req, user: User) -> Success | Error:
        parsed_old = self._parse_path(user, req.old_path)
        if isinstance(parsed_old, Error):
            return parsed_old
        old_vault, old_rel = parsed_old[0]
        old = self._resolve(old_vault, old_rel)
        if not old.exists():
            return Error(message=f"File not found: {req.old_path}")
        if not req.new_path:
            old.unlink()
            return Success()

        parsed_new = self._parse_path(user, req.new_path)
        if isinstance(parsed_new, Error):
            return parsed_new
        new_vault, new_rel = parsed_new[0]
        new = self._resolve(new_vault, new_rel)
        if new.exists():
            return Error(message=f"File already exists: {req.new_path}")
        new.parent.mkdir(parents=True, exist_ok=True)
        if req.make_copy:
            shutil.copy2(str(old), str(new))
        elif old_vault.dir_path == new_vault.dir_path:
            shutil.move(str(old), str(new))
        else:
            # Cross-vault: copy + delete for different filesystems
            shutil.copy2(str(old), str(new))
            old.unlink()
        return Success()

    def _list_files(self, req, user: User) -> FilesList | Error:
        parsed = self._parse_path(user, req.path)
        if isinstance(parsed, Error):
            return parsed
        # (vault_name, rel_path, modified_str, size, formatted_line)
        all_entries: list[tuple[str, str, str, int, str]] = []
        for vault, rel in parsed:
            base = self._resolve(vault, rel)
            if not base.is_dir():
                continue
            entries: list[tuple[str, str, int, str]] = []
            self._walk(base, req.extensions, req.max_depth, 0, rel, entries)
            for e in entries:
                all_entries.append((vault.name, *e))

        key_idx = {"name": 1, "modified": 2, "length": 3}[req.sort_by]
        all_entries.sort(key=lambda e: e[key_idx], reverse=req.sort_order == "desc")

        total = len(all_entries)
        offset = req.offset
        limit = total if req.limit == -1 else req.limit
        sliced = all_entries[offset : offset + limit]

        results: dict[str, list[str]] = {}
        for vault_name, _, _, _, formatted in sliced:
            results.setdefault(vault_name, []).append(formatted)
        return FilesList(results=results, length=total, offset=offset, limit=limit)

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

    def _search_files(self, req, user: User) -> SearchResults | Error:
        parsed = self._parse_path(user, req.path)
        if isinstance(parsed, Error):
            return parsed
        try:
            pattern = re.compile(req.pattern)
        except re.error as e:
            return Error(message=f"Invalid regex: {e}")

        # (vault_name, formatted_line)
        all_matches: list[tuple[str, str]] = []
        for vault, rel in parsed:
            base = self._resolve(vault, rel)
            if not base.is_dir():
                continue
            matches: list[str] = []
            self._search_walk(base, req.extensions, req.max_depth, 0, rel, pattern, req.context_chars, matches)
            for m in matches:
                all_matches.append((vault.name, m))

        total = len(all_matches)
        limit = total if req.limit == -1 else req.limit
        sliced = all_matches[req.offset : req.offset + limit]

        results: dict[str, list[str]] = {}
        for vault_name, formatted in sliced:
            results.setdefault(vault_name, []).append(formatted)
        return SearchResults(results=results, length=total, offset=req.offset, limit=limit)

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
                for m in pattern.finditer(child.name):
                    out.append(f"{rel}:0 | {m.group()} | (filename)")
                try:
                    for i, line in enumerate(child.read_text().splitlines(), 1):
                        for m in pattern.finditer(line):
                            half = context_chars // 2
                            ctx = line[max(0, m.start() - half) : m.end() + half]
                            out.append(f"{rel}:{i} | {m.group()} | {ctx}")
                except (UnicodeDecodeError, PermissionError):
                    continue

    def _list_users(self, _req, _user: User) -> UsersList:
        return UsersList(users=self.config.users)

    def _upsert_user(self, req, _user: User) -> Success | Error:
        existing = next((u for u in self.config.users if u.username == req.username), None)

        if req.delete:
            if not existing:
                return Error(message=f"User not found: {req.username}")
            if self.config.users.index(existing) == 0:
                return Error(message="Cannot remove admin user")
            self.config.users.remove(existing)
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
            idx = self.config.users.index(existing)
            self.config.users[idx] = existing.model_copy(update=updates)
            self._save_config()
            return Success()

        token = req.token or secrets.token_urlsafe(16)
        self.config.users.append(User(
            username=req.username,
            token=token,
            access=req.access or [PathAccess()],
            is_admin=bool(req.is_admin),
        ))
        self._save_config()
        return Success(message=f"Created user '{req.username}' with token: {token}")

    def _upsert_vault(self, req, _user: User) -> Success | Error:
        if req.delete:
            idx = next((i for i, v in enumerate(self.config.vaults) if v.name == req.name), None)
            if idx is None:
                return Error(message=f"Vault not found: {req.name}")
            self.config.vaults.pop(idx)
            self._save_config()
            return Success()

        if req.dir_path.startswith("sync:"):
            resolved = "sync:" + str(Path(req.dir_path[5:]).resolve())
        else:
            resolved = str(Path(req.dir_path).resolve())
        existing = next((v for v in self.config.vaults if v.name == req.name), None)
        if existing:
            idx = self.config.vaults.index(existing)
            self.config.vaults[idx] = existing.model_copy(update={"dir_path": resolved})
        else:
            self.config.vaults.append(VaultConfig(name=req.name, dir_path=resolved))
        self._save_config()
        if resolved.startswith("sync:"):
            self.ensure_sync_manager()
            if self.sync_manager is not None:
                self.sync_manager.start_vault(VaultConfig(name=req.name, dir_path=resolved))
        return Success()
