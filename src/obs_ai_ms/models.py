from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


TOOL_PROMPT = """\
Access one or more Obsidian vaults.
Send a JSON array string: '[{{"kind":"get_vault_info"}}, ...]'

Request kinds:
{request_kinds}
"""


class ServerConfig(BaseModel):
    address: str = Field(default="127.0.0.1")
    port: int = Field(default=8747)
    fqdn: str = Field(default="")
    base_path: str = Field(default="")  # path before /web, /api, /mcp, etc
    obs_username: str = Field(default="")
    obs_password: str = Field(default="")
    # write-only: masked to "********" in API/UI responses when non-empty
    users: list[User] = Field(default_factory=lambda: [User()])
    # first user is admin and can be modified by env vars / cli args
    vaults: list[VaultConfig] = Field(default_factory=list)
    # first vault is default and can be modified by env vars / cli args


class User(BaseModel):
    username: str = Field(default="admin")
    token: str = Field(default="")
    access: list[PathAccess] = Field(default_factory=lambda: [PathAccess()])

    # "*:path/" grants access to path in all vaults
    is_admin: bool = Field(default=True)


class PathAccess(BaseModel):
    path: str = Field(default="*:")
    # "*:" grants all access
    # "*:something/" grants access to "something/" in all vaults
    read: bool = Field(default=True)
    write: bool = Field(default=True)
    recursive: bool = Field(default=True)


class VaultConfig(BaseModel):
    name: str = Field(...)
    # defaults to vault's dir name
    # used with any path to be vault-aware as
    # "name:some/path/to/note.md"
    dir_path: str = Field(...)
    daily_notes_folder: str = Field(default="")
    status: str = Field(default="")
    # - "ok"
    # - "unavailable - not configured"
    # - "unavailable - missing dir <dir_path>"
    # - "unavailable - dir not a vault <dir_path>"


class BaseRequest(BaseModel):
    kind: str = Field(..., description="Discriminator for request type")
    model_config = ConfigDict(extra="forbid")


class GetVaultsInfo(BaseRequest):
    """Your vaults and access."""

    kind: Literal["get_vault_info"] = "get_vault_info"


class ReadText(BaseRequest):
    """Notes and text files."""

    kind: Literal["read_text"] = "read_text"
    path: str = Field(...)
    offset: int = Field(default=0)
    limit: int = Field(default=20_000, description="-1 for unlimited chars.")


class ReplaceText(BaseRequest):
    """Replace 1+."""

    kind: Literal["replace_text"] = "replace_text"
    path: str = Field(...)
    old_text: str = Field(...)
    new_text: str = Field(...)
    count: int = Field(default=1, description="-1 for unlimited.")


class WriteText(BaseRequest):
    """Overwrite."""

    kind: Literal["write_text"] = "write_text"
    path: str = Field(...)
    text: str = Field(...)


class AppendText(BaseRequest):
    """Newlines up to you."""

    kind: Literal["append_text"] = "append_text"
    path: str = Field(...)
    text: str = Field(...)
    prepend: bool = Field(default=False)


class MoveFile(BaseRequest):
    """Move, copy, or delete."""

    # Able to move files between vaults

    kind: Literal["move_file"] = "move_file"
    old_path: str = Field(...)
    new_path: str | None = Field(default=None, description="Omit to delete.")
    make_copy: bool = Field(default=False, description="Keeps original.")


class ListFiles(BaseRequest):
    """
    Folder tree, returns:
    `<path> | <modified_at> | <length>`
    """

    kind: Literal["list_files"] = "list_files"
    path: str = Field(default="")
    extensions: list[str] = Field(default=[".md"], description="Empty matches all.")
    max_depth: int = Field(default=1, description="-1 for unlimited.")
    offset: int = Field(default=0)
    limit: int = Field(default=100, description="-1 for unlimited results.")
    sort_by: Literal["name", "length", "modified"] = Field(default="name")
    sort_order: Literal["asc", "desc"] = Field(default="asc")


class SearchFiles(BaseRequest):
    """
    Regex names and content, returns:
    `<path>:<line> | <match> | <context>`
    """

    kind: Literal["search_files"] = "search_files"
    pattern: str = Field(...)
    path: str = Field(default="")
    extensions: list[str] = Field(default=[".md"])
    max_depth: int = Field(default=-1)
    context_chars: int = Field(default=120)
    offset: int = Field(default=0)
    limit: int = Field(default=100)


class AdminListUsers(BaseRequest):
    """"""

    kind: Literal["list_users"] = "list_users"


class AdminUpsertUser(BaseRequest):
    """Create, update or delete."""

    kind: Literal["upsert_user"] = "upsert_user"
    username: str = Field(...)
    token: str | None = Field(default=None)
    access: list[PathAccess] | None = Field(default=None)
    is_admin: bool | None = Field(default=None)
    delete: bool | None = Field(default=None)


# class AdminListVaults(BaseRequest):
# Deliberately omitted, just use GetVaultsInfo instead


class AdminUpsertVault(BaseRequest):
    """Create, update or delete."""

    kind: Literal["upsert_vault"] = "upsert_vault"
    name: str = Field(...)
    dir_path: str = Field(...)
    delete: bool | None = Field(default=None)


class BaseResponse(BaseModel):
    kind: str = Field(..., description="Discriminator for response type")
    model_config = ConfigDict(extra="forbid")


class Success(BaseResponse):
    """Default response."""

    kind: Literal["success"] = "success"
    message: str | None = Field(
        default=None,
        description='Omitted when absent. After move_file rename, e.g. "Updates links in 1 file" / "Updates links in N files".',
    )


class Error(BaseResponse):
    """Request failed."""

    kind: Literal["error"] = "error"
    message: str = Field(...)


class VaultsInfo(BaseResponse):
    """Accessible vaults and user info."""

    kind: Literal["vault_info"] = "vault_info"
    vaults: list[VaultConfig] = Field(...)
    user: User = Field(...)

    message: str = Field(default="")
    # If user has access to 2+ vaults, includes:
    # "Paths accept "vault:path", "*:" or "" = all.""
    # If user is admin and sync is active, appends:
    # "obs active: <latest single log line>" (only if line is < 30 seconds old)


class FileText(BaseResponse):
    """
    If offset > 0 or length > limit, the text is an excerpt.
    """

    kind: Literal["file_text"] = "file_text"
    text: str = Field(...)
    length: int = Field(...)
    modified_at: str = Field(...)  # Format: `YYYY-MM-DD HH:MM:SS`
    offset: int = Field(default=0)
    limit: int = Field(default=20_000)


class FilesList(BaseResponse):
    """
    List of files and folders relative to the base path.
    If offset > 0 or length > limit, the results are an excerpt.
    """

    kind: Literal["files_list"] = "files_list"
    results: dict[str, list[str]] = Field(  # key by vault name
        ...
    )  # Format: `<path> | <modified_at> | <length> <chars or b>`
    length: int = Field(...)
    offset: int = Field(default=0)
    limit: int = Field(default=100)


class SearchResults(BaseResponse):
    """Regex search results with context snippets."""

    kind: Literal["search_results"] = "search_results"
    results: dict[str, list[str]] = Field(  # key by vault name
        ...
    )  # Format: `<path>:<line> | <match> | <context>`
    length: int = Field(...)
    offset: int = Field(default=0)
    limit: int = Field(default=50)


class UsersList(BaseResponse):

    kind: Literal["users_list"] = "users_list"
    users: list[User] = Field(...)


# AI please keep these unions up to date w/ the current models.
# Endpoint accepts list[ServerRequest] and returns list[ServerResponse].
# (this is the only part of this file you can edit without asking)

ServerRequest = Annotated[
    Union[
        GetVaultsInfo,
        ReadText,
        ReplaceText,
        WriteText,
        AppendText,
        MoveFile,
        ListFiles,
        SearchFiles,
        AdminListUsers,
        AdminUpsertUser,
        AdminUpsertVault,
    ],
    Field(discriminator="kind"),
]

ServerResponse = Annotated[
    Union[
        Success,
        Error,
        VaultsInfo,
        FileText,
        FilesList,
        SearchResults,
        UsersList,
    ],
    Field(discriminator="kind"),
]


class ObsidianBody(BaseModel):
    """Body for the obsidian API endpoint."""

    requests: str = Field(
        ...,
        description='JSON array of request objects, e.g. \'[{"kind":"get_vault_info"}]\'',
    )


class BasePage(BaseModel):
    """A page of the web UI."""


class LoginPage(BasePage):
    """
    path: /login
    title: Login
    - secret text field: access_token
    - button: "Login" (logs in the user)
    - label: error (when present)
    """

    login_error: str | None = None


class HomePage(BasePage):
    """
    path: /
    title: Obsidian AI Mini Server
    - list: vaults (name + status)
    - label: server_error (when present)
    - labels: web_fqdn, api_fqdn, mcp_fqdn
    - paragraph: show the header auth setup and any other key setup details
    - link: username -> /users/<username>
    - link: "Users" -> /users
    - link: "Vaults" -> /vaults
    - link: "Config" -> /config
    - button: "Logout" (logs out the current user)
    """

    vaults: list[VaultConfig]
    username: str
    web_fqdn: str
    api_fqdn: str
    mcp_fqdn: str
    server_error: str | None = None


class ConfigPage(BasePage):
    """
    path: /config
    title: Server Config
    - label: server_config
    - labels: address, port, base_path, obs_username
    - secret field: obs_password (write-only, shown as "••••••" if set, editable)
    - link: "<vault_count> Vaults" -> /vaults
    - link: "<user_count> Users" -> /users
    - if sync_active:
        - section: "Obsidian Sync Log"
        - <pre> block: last 50 lines from sync log
        - checkbox: "Auto-refresh (1s)" — reloads page every second when checked
    """

    config: ServerConfig
    sync_log: list[str] = Field(default_factory=list)
    sync_active: bool = Field(default=False)


class UsersPage(BasePage):
    """
    path: /users
    title: Users
    - list: "Users"
        - link: "<username>" -> /users/<username>
        - checkbox (disabled) is_admin
    - link: "Add User" -> /users/add
    """

    users: list[User]


class UserPage(BasePage):
    """
    path: /users/<username>
    title: "User: <username>"
    - text field: username
    - secret text field: access_token
        - inline button: "show"/"hide" toggles token visibility
        - inline button: "copy" copies token to clipboard
    - checkbox: is_admin
    - list: "Access"
        - text field: "Path"
        - checkbox: "Recursive"
        - checkbox: "Read"
        - checkbox: "Write"
        - button: "Delete" (with confirmation popup)
    - button: "Add Access" (adds a new access list item)
    - button: "Save Changes" (disabled if no changes yet)
    - button: "Delete User" (with confirmation, not available for user 0)

    Notes:
    - if the user does not change the access_token, it will
    not be modified on save.
    """

    user: User


class AddUserPage(UserPage):
    """
    path: /users/add
    title: Add User
    Equivalent to UserPage, but before it has a username and url.
    Up to user to copy or overwrite the autogenerated token.
    """

    autogenerated_token: str


class VaultsPage(BasePage):
    """
    path: /vaults
    title: Vaults
    - list: "Vaults"
        - link: "<vault_name>" -> /vaults/<vault_name>
        - label: "<status>"
    - link: "Add Vault" -> /vaults/add
    """

    vaults: list[VaultConfig]


class VaultPage(BasePage):
    """
    path: /vaults/<vault_name>
    title: "Vault: <vault_name>"
    - text field: name
    - text field: dir_path
        - hint: "Prefix with sync: to auto-sync from Obsidian — final dir name must match the vault name on Obsidian, e.g. sync:/vaults/MyNotes"
    - label: "<status>"
    - label: "Daily Notes at <daily_notes_folder>"
    - button: "Save Changes" (disabled if no changes yet)
    - button: "Delete Vault" (with confirmation)
    """

    vault: VaultConfig


class AddVaultPage(VaultPage):
    """
    path: /vaults/add
    title: Add Vault
    Equivalent to VaultPage, but before it has a name and url.
    """
