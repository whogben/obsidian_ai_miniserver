import pytest

from obs_ai_ms.models import (
    AdminListUsers,
    AdminUpsertUser,
    AppendText,
    Batch,
    GetVaultInfo,
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
    """Vault with sample files and known users."""
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "test.md").write_text("hello world")
    (tmp_path / "notes" / "other.md").write_text("other content")
    (tmp_path / "readme.md").write_text("readme content")

    obs = tmp_path / ".obsidian"
    obs.mkdir()
    (obs / "daily-notes.json").write_text('{"folder":"Dailies"}')

    v = Vault(str(tmp_path))
    v.users = [
        User(token="admin-token", is_admin=True),
        User(
            username="reader",
            token="reader-token",
            is_admin=False,
            access=[PathAccess(path="notes/", read=True, write=False)],
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
        access=[PathAccess(path="notes/", read=True, write=False)],
    )


# --- Core operations ---


def test_get_vault_info(vault, admin):
    resp = vault.obsidian(GetVaultInfo(), admin)
    assert resp.kind == "vault_info"
    assert resp.name == vault.vault_path.name
    assert resp.daily_notes_folder == "Dailies"


def test_read_text(vault, admin):
    resp = vault.obsidian(ReadText(path="notes/test.md"), admin)
    assert resp.kind == "file_text"
    assert resp.text == "hello world"
    assert resp.length == 11


def test_read_text_not_found(vault, admin):
    resp = vault.obsidian(ReadText(path="nope.md"), admin)
    assert resp.kind == "error"
    assert "not found" in resp.message.lower()


def test_write_text(vault, admin):
    resp = vault.obsidian(WriteText(path="new.md", text="fresh"), admin)
    assert resp.kind == "success"
    assert (vault.vault_path / "new.md").read_text() == "fresh"


def test_append_text(vault, admin):
    resp = vault.obsidian(AppendText(path="notes/test.md", text="!"), admin)
    assert resp.kind == "success"
    assert (vault.vault_path / "notes" / "test.md").read_text() == "hello world!"


def test_replace_text(vault, admin):
    resp = vault.obsidian(
        ReplaceText(path="notes/test.md", old_text="hello", new_text="goodbye"),
        admin,
    )
    assert resp.kind == "success"
    assert (vault.vault_path / "notes" / "test.md").read_text() == "goodbye world"


def test_move_file(vault, admin):
    resp = vault.obsidian(
        MoveFile(old_path="notes/test.md", new_path="notes/renamed.md"), admin
    )
    assert resp.kind == "success"
    assert not (vault.vault_path / "notes" / "test.md").exists()
    assert (vault.vault_path / "notes" / "renamed.md").read_text() == "hello world"


def test_list_files(vault, admin):
    # Add a .txt file to verify extension filter excludes it
    (vault.vault_path / "notes" / "data.txt").write_text("data")
    resp = vault.obsidian(ListFiles(path="notes"), admin)
    assert resp.kind == "files_list"
    names = [r.split(" | ")[0] for r in resp.results]
    assert "notes/test.md" in names
    assert "notes/other.md" in names
    assert not any("data.txt" in n for n in names)


# --- Auth tests ---


def test_authenticate_valid(vault):
    user = vault.authenticate("admin-token")
    assert user is not None
    assert user.is_admin is True


def test_authenticate_invalid(vault):
    assert vault.authenticate("bad-token") is None


def test_access_allowed(vault, reader):
    resp = vault.obsidian(ReadText(path="notes/test.md"), reader)
    assert resp.kind == "file_text"
    assert resp.text == "hello world"


def test_access_denied_read(vault, reader):
    resp = vault.obsidian(ReadText(path="readme.md"), reader)
    assert resp.kind == "error"


def test_access_denied_write(vault, reader):
    resp = vault.obsidian(WriteText(path="notes/test.md", text="x"), reader)
    assert resp.kind == "error"


def test_admin_full_access(vault, admin):
    # Admin can read outside any explicit path rule
    resp = vault.obsidian(ReadText(path="readme.md"), admin)
    assert resp.kind == "file_text"
    # Admin can write
    resp = vault.obsidian(WriteText(path="any/path.md", text="ok"), admin)
    assert resp.kind == "success"


# --- Admin tests ---


def test_list_users(vault, admin):
    resp = vault.obsidian(AdminListUsers(), admin)
    assert resp.kind == "users_list"
    assert len(resp.users) == 2
    # tokens are visible to admin
    assert resp.users[0].token == "admin-token"
    assert resp.users[1].token == "reader-token"


def test_upsert_user_create(vault, admin):
    resp = vault.obsidian(
        AdminUpsertUser(username="newbie", token="tok123"), admin
    )
    assert resp.kind == "success"
    assert len(vault.users) == 3
    assert vault.users[2].username == "newbie"


def test_upsert_user_update(vault, admin):
    resp = vault.obsidian(
        AdminUpsertUser(username="reader", token="new-tok"), admin
    )
    assert resp.kind == "success"
    assert vault.users[1].token == "new-tok"


def test_upsert_user_delete(vault, admin):
    resp = vault.obsidian(
        AdminUpsertUser(username="reader", delete_user=True), admin
    )
    assert resp.kind == "success"
    assert len(vault.users) == 1


def test_cannot_remove_admin(vault, admin):
    resp = vault.obsidian(
        AdminUpsertUser(username="admin", delete_user=True), admin
    )
    assert resp.kind == "error"
    assert len(vault.users) == 2


def test_non_admin_cannot_list_users(vault, reader):
    resp = vault.obsidian(AdminListUsers(), reader)
    assert resp.kind == "error"


# --- Bug-fix regression tests ---


def test_trailing_slash_normalization(vault, reader):
    """Accessing 'notes' (no slash) should match rule 'notes/'."""
    resp = vault.obsidian(ListFiles(path="notes"), reader)
    assert resp.kind == "files_list"


def test_non_recursive_blocks_subdirectory(vault):
    """A non-recursive rule on 'notes' should not grant access to 'notes/sub'."""
    user = User(
        username="flat",
        token="flat-token",
        is_admin=False,
        access=[PathAccess(path="notes", read=True, write=False, recursive=False)],
    )
    # Exact path should be allowed
    resp = vault.obsidian(ListFiles(path="notes"), user)
    assert resp.kind == "files_list"
    # Subdirectory should be denied
    resp = vault.obsidian(ReadText(path="notes/test.md"), user)
    assert resp.kind == "error"


# --- SearchFiles tests ---


def test_search_files(vault, admin):
    resp = vault.obsidian(SearchFiles(pattern="hello"), admin)
    assert resp.kind == "search_results"
    assert resp.length > 0
    assert any("hello" in m for m in resp.results)


def test_search_files_with_path(vault, admin):
    resp = vault.obsidian(SearchFiles(pattern="content", path="notes"), admin)
    assert resp.kind == "search_results"
    assert resp.length > 0
    # Should find "other content" in notes/other.md
    assert any("other.md" in m for m in resp.results)


def test_search_files_no_results(vault, admin):
    resp = vault.obsidian(SearchFiles(pattern="xyzzy_nonsense"), admin)
    assert resp.kind == "search_results"
    assert resp.length == 0


def test_search_files_invalid_regex(vault, admin):
    resp = vault.obsidian(SearchFiles(pattern="[invalid"), admin)
    assert resp.kind == "error"
    assert "invalid regex" in resp.message.lower()


def test_search_files_pagination(vault, admin):
    # Write a file with multiple matches
    vault.obsidian(WriteText(path="multi.md", text="match\nmatch\nmatch\nmatch\nmatch"), admin)
    resp = vault.obsidian(SearchFiles(pattern="match", limit=2), admin)
    assert resp.kind == "search_results"
    assert len(resp.results) == 2
    assert resp.length == 5  # total matches


# --- Batch tests ---


def test_batch(vault, admin):
    resp = vault.obsidian(Batch(requests=[
        ReadText(path="notes/test.md"),
        GetVaultInfo(),
    ]), admin)
    assert resp.kind == "batch_response"
    assert len(resp.responses) == 2
    assert resp.responses[0].kind == "file_text"
    assert resp.responses[0].text == "hello world"
    assert resp.responses[1].kind == "vault_info"


def test_batch_access_denied(vault, reader):
    """Batch should deny sub-requests that fail access control."""
    resp = vault.obsidian(Batch(requests=[
        ReadText(path="readme.md"),  # reader can't access this
    ]), reader)
    assert resp.kind == "batch_response"
    assert resp.responses[0].kind == "error"
