from pathlib import Path

import pytest

from obs_ai_ms.models import (
    AdminListUsers,
    AdminUpsertUser,
    AdminUpsertVault,
    AppendText,
    GetVaultsInfo,
    ListFiles,
    MoveFile,
    PathAccess,
    ReadText,
    ReplaceText,
    SearchFiles,
    User,
    WriteText,
)
from obs_ai_ms.vault import Vault


@pytest.fixture
def vault(tmp_path):
    """Multi-vault Vault with sample files and known users."""
    # Work vault
    work = tmp_path / "work"
    (work / "notes").mkdir(parents=True)
    (work / "notes" / "test.md").write_text("hello world")
    (work / "notes" / "other.md").write_text("other content")
    (work / "readme.md").write_text("readme content")
    (work / ".obsidian").mkdir()
    (work / ".obsidian" / "daily-notes.json").write_text('{"folder":"Dailies"}')

    # Personal vault
    personal = tmp_path / "personal"
    (personal / "journal").mkdir(parents=True)
    (personal / "journal" / "day1.md").write_text("dear diary")
    (personal / "ideas.md").write_text("bright ideas")
    (personal / ".obsidian").mkdir()
    (personal / ".obsidian" / "daily-notes.json").write_text('{"folder":"Journal"}')

    v = Vault(config_path=str(tmp_path / "config.json"))
    v.register_vault("work", str(work))
    v.register_vault("personal", str(personal))
    v.config.users = [
        User(token="admin-token", is_admin=True),
        User(
            username="reader",
            token="reader-token",
            is_admin=False,
            access=[PathAccess(path="work:notes/", read=True, write=False)],
        ),
    ]
    v._save_config()
    return v


@pytest.fixture
def admin():
    return User(token="admin-token", is_admin=True)


@pytest.fixture
def reader():
    return User(
        username="reader",
        token="reader-token",
        is_admin=False,
        access=[PathAccess(path="work:notes/", read=True, write=False)],
    )


# --- Core operations ---


def test_get_vaults_info(vault, admin):
    resp = vault.obsidian([GetVaultsInfo()], admin)
    assert resp[0].kind == "vault_info"
    assert len(resp[0].vaults) == 2
    names = [v.name for v in resp[0].vaults]
    assert "work" in names
    assert "personal" in names
    assert resp[0].user.is_admin is True
    assert resp[0].user.token == ""  # token cleared in response


def test_read_text(vault, admin):
    resp = vault.obsidian([ReadText(path="work:notes/test.md")], admin)
    assert resp[0].kind == "file_text"
    assert resp[0].text == "hello world"
    assert resp[0].length == 11


def test_read_text_not_found(vault, admin):
    resp = vault.obsidian([ReadText(path="work:nope.md")], admin)
    assert resp[0].kind == "error"
    assert "not found" in resp[0].message.lower()


def test_write_text(vault, admin):
    resp = vault.obsidian([WriteText(path="work:new.md", text="fresh")], admin)
    assert resp[0].kind == "success"
    work_dir = next(Path(v.dir_path) for v in vault.config.vaults if v.name == "work")
    assert (work_dir / "new.md").read_text() == "fresh"


def test_append_text(vault, admin):
    resp = vault.obsidian([AppendText(path="work:notes/test.md", text="!")], admin)
    assert resp[0].kind == "success"
    work_dir = next(Path(v.dir_path) for v in vault.config.vaults if v.name == "work")
    assert (work_dir / "notes" / "test.md").read_text() == "hello world!"


def test_replace_text(vault, admin):
    resp = vault.obsidian(
        [ReplaceText(path="work:notes/test.md", old_text="hello", new_text="goodbye")],
        admin,
    )
    assert resp[0].kind == "success"
    work_dir = next(Path(v.dir_path) for v in vault.config.vaults if v.name == "work")
    assert (work_dir / "notes" / "test.md").read_text() == "goodbye world"


def test_move_file(vault, admin):
    resp = vault.obsidian(
        [MoveFile(old_path="work:notes/test.md", new_path="work:notes/renamed.md")],
        admin,
    )
    assert resp[0].kind == "success"
    work_dir = next(Path(v.dir_path) for v in vault.config.vaults if v.name == "work")
    assert not (work_dir / "notes" / "test.md").exists()
    assert (work_dir / "notes" / "renamed.md").read_text() == "hello world"


def test_list_files(vault, admin):
    work_dir = next(Path(v.dir_path) for v in vault.config.vaults if v.name == "work")
    (work_dir / "notes" / "data.txt").write_text("data")
    resp = vault.obsidian([ListFiles(path="work:notes")], admin)
    assert resp[0].kind == "files_list"
    names = [r.split(" | ")[0] for r in resp[0].results["work"]]
    assert "notes/test.md" in names
    assert "notes/other.md" in names
    assert not any("data.txt" in n for n in names)


def test_search_files(vault, admin):
    resp = vault.obsidian([SearchFiles(pattern="hello", path="")], admin)
    assert resp[0].kind == "search_results"
    assert resp[0].length > 0
    all_results = [m for matches in resp[0].results.values() for m in matches]
    assert any("hello" in m for m in all_results)


# --- Multi-vault operations ---


def test_list_files_multi_vault(vault, admin):
    resp = vault.obsidian([ListFiles(path="")], admin)
    assert resp[0].kind == "files_list"
    assert "work" in resp[0].results
    assert "personal" in resp[0].results


def test_search_files_multi_vault(vault, admin):
    resp = vault.obsidian([SearchFiles(pattern="world|diary", path="")], admin)
    assert resp[0].kind == "search_results"
    assert "work" in resp[0].results  # "hello world"
    assert "personal" in resp[0].results  # "dear diary"


def test_move_file_cross_vault(vault, admin):
    resp = vault.obsidian(
        [MoveFile(old_path="work:notes/test.md", new_path="personal:test.md")],
        admin,
    )
    assert resp[0].kind == "success"
    work_dir = next(Path(v.dir_path) for v in vault.config.vaults if v.name == "work")
    personal_dir = next(Path(v.dir_path) for v in vault.config.vaults if v.name == "personal")
    assert not (work_dir / "notes" / "test.md").exists()
    assert (personal_dir / "test.md").read_text() == "hello world"


def test_single_vault_shortcut(vault, reader):
    # Reader has access to only "work" vault — paths without prefix resolve there
    resp = vault.obsidian([ReadText(path="notes/test.md")], reader)
    assert resp[0].kind == "file_text"
    assert resp[0].text == "hello world"


# --- Auth tests ---


def test_authenticate_valid(vault):
    user = vault.authenticate("admin-token")
    assert user is not None
    assert user.is_admin is True


def test_authenticate_invalid(vault):
    assert vault.authenticate("bad-token") is None


def test_access_allowed(vault, reader):
    resp = vault.obsidian([ReadText(path="work:notes/test.md")], reader)
    assert resp[0].kind == "file_text"
    assert resp[0].text == "hello world"


def test_access_denied_read(vault, reader):
    resp = vault.obsidian([ReadText(path="work:readme.md")], reader)
    assert resp[0].kind == "error"


def test_access_denied_write(vault, reader):
    resp = vault.obsidian([WriteText(path="work:notes/test.md", text="x")], reader)
    assert resp[0].kind == "error"


def test_admin_full_access(vault, admin):
    resp = vault.obsidian([ReadText(path="work:readme.md")], admin)
    assert resp[0].kind == "file_text"
    resp = vault.obsidian([WriteText(path="work:any/path.md", text="ok")], admin)
    assert resp[0].kind == "success"


# --- Admin tests ---


def test_list_users(vault, admin):
    resp = vault.obsidian([AdminListUsers()], admin)
    assert resp[0].kind == "users_list"
    assert len(resp[0].users) == 2
    assert resp[0].users[0].token == "admin-token"
    assert resp[0].users[1].token == "reader-token"


def test_upsert_user_create(vault, admin):
    resp = vault.obsidian(
        [AdminUpsertUser(username="newbie", token="tok123")],
        admin,
    )
    assert resp[0].kind == "success"
    assert len(vault.users) == 3
    assert vault.users[2].username == "newbie"


def test_upsert_user_update(vault, admin):
    resp = vault.obsidian(
        [AdminUpsertUser(username="reader", token="new-tok")],
        admin,
    )
    assert resp[0].kind == "success"
    assert vault.users[1].token == "new-tok"


def test_upsert_user_delete(vault, admin):
    resp = vault.obsidian(
        [AdminUpsertUser(username="reader", delete=True)],
        admin,
    )
    assert resp[0].kind == "success"
    assert len(vault.users) == 1


def test_cannot_remove_admin(vault, admin):
    resp = vault.obsidian(
        [AdminUpsertUser(username="admin", delete=True)],
        admin,
    )
    assert resp[0].kind == "error"
    assert len(vault.users) == 2


def test_non_admin_cannot_list_users(vault, reader):
    resp = vault.obsidian([AdminListUsers()], reader)
    assert resp[0].kind == "error"


# --- Vault admin tests ---


def test_upsert_vault_create(vault, admin, tmp_path):
    new_dir = tmp_path / "new_vault"
    new_dir.mkdir()
    (new_dir / ".obsidian").mkdir()
    resp = vault.obsidian(
        [AdminUpsertVault(name="new", dir_path=str(new_dir))],
        admin,
    )
    assert resp[0].kind == "success"
    assert any(v.name == "new" for v in vault.config.vaults)


def test_upsert_vault_delete(vault, admin):
    resp = vault.obsidian(
        [AdminUpsertVault(name="personal", dir_path="", delete=True)],
        admin,
    )
    assert resp[0].kind == "success"
    assert not any(v.name == "personal" for v in vault.config.vaults)


def test_non_admin_cannot_upsert_vault(vault, reader):
    resp = vault.obsidian(
        [AdminUpsertVault(name="hack", dir_path="/tmp")],
        reader,
    )
    assert resp[0].kind == "error"


# --- Bug-fix regression tests ---


def test_trailing_slash_normalization(vault, reader):
    """Accessing 'work:notes' (no slash) should match rule 'work:notes/'."""
    resp = vault.obsidian([ListFiles(path="work:notes")], reader)
    assert resp[0].kind == "files_list"


def test_non_recursive_blocks_subdirectory(vault):
    """A non-recursive rule on 'work:notes' should not grant access to 'work:notes/sub'."""
    user = User(
        username="flat",
        token="flat-token",
        is_admin=False,
        access=[PathAccess(path="work:notes", read=True, write=False, recursive=False)],
    )
    # Exact path allowed
    resp = vault.obsidian([ListFiles(path="work:notes")], user)
    assert resp[0].kind == "files_list"
    # Subdirectory denied
    resp = vault.obsidian([ReadText(path="work:notes/test.md")], user)
    assert resp[0].kind == "error"


# --- Search tests ---


def test_search_files_with_path(vault, admin):
    resp = vault.obsidian([SearchFiles(pattern="content", path="work:notes")], admin)
    assert resp[0].kind == "search_results"
    assert resp[0].length > 0
    all_results = [m for matches in resp[0].results.values() for m in matches]
    assert any("other.md" in m for m in all_results)


def test_search_files_no_results(vault, admin):
    resp = vault.obsidian([SearchFiles(pattern="xyzzy_nonsense", path="work:")], admin)
    assert resp[0].kind == "search_results"
    assert resp[0].length == 0


def test_search_files_invalid_regex(vault, admin):
    resp = vault.obsidian([SearchFiles(pattern="[invalid", path="work:")], admin)
    assert resp[0].kind == "error"
    assert "invalid regex" in resp[0].message.lower()


def test_search_files_pagination(vault, admin):
    vault.obsidian([WriteText(path="work:multi.md", text="match\nmatch\nmatch\nmatch\nmatch")], admin)
    resp = vault.obsidian([SearchFiles(pattern="match", path="work:", limit=2)], admin)
    assert resp[0].kind == "search_results"
    total_returned = sum(len(v) for v in resp[0].results.values())
    assert total_returned == 2
    assert resp[0].length == 5  # total matches
