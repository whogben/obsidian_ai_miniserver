from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class ServerConfig(BaseModel):
    vault_path: str = Field(...)
    address: str = Field(default="127.0.0.1")
    port: int = Field(default=8747)
    fqdn: str = Field(default="")
    base_path: str = Field(default="")  # path before /web, /api, /mcp, etc
    users: list[User] = Field(default_factory=lambda: [User()])
    # first user is admin and cant be removed


class User(BaseModel):
    username: str = Field(default="admin")
    token: str = Field(default="")
    access: list[PathAccess] = Field(default_factory=lambda: [PathAccess()])
    is_admin: bool = Field(default=True)


class PathAccess(BaseModel):
    path: str = Field(default="/")
    read: bool = Field(default=True)
    write: bool = Field(default=True)
    recursive: bool = Field(default=True)


class BaseRequest(BaseModel):
    kind: str = Field(..., description="Discriminator for request type")
    model_config = ConfigDict(extra="forbid")


class GetVaultInfo(BaseRequest):
    """About the vault and your access."""

    kind: Literal["get_vault_info"] = "get_vault_info"


class ReadText(BaseRequest):
    """Read path text."""

    kind: Literal["read_text"] = "read_text"
    path: str = Field(...)
    offset: int = Field(default=0)
    limit: int = Field(default=20_000, description="-1 for unlimited chars.")


class ReplaceText(BaseRequest):
    """Replace 1 or more instances of `old_text` with `new_text`."""

    kind: Literal["replace_text"] = "replace_text"
    path: str = Field(...)
    old_text: str = Field(...)
    new_text: str = Field(...)
    count: int = Field(default=1, description="Set to -1 for unlimited.")


class WriteText(BaseRequest):
    """Overwrite the path with the text."""

    kind: Literal["write_text"] = "write_text"
    path: str = Field(...)
    text: str = Field(...)


class AppendText(BaseRequest):
    """Append text to the end of the path."""

    kind: Literal["append_text"] = "append_text"
    path: str = Field(...)
    text: str = Field(...)


class MoveFile(BaseRequest):
    """Moves, copies, or removes the file at `old_path`."""

    kind: Literal["move_file"] = "move_file"
    old_path: str = Field(...)
    new_path: str = Field(..., description="Set to '' to delete the file.")
    make_copy: bool = Field(default=False, description="Set to true to copy the file.")


class ListFiles(BaseRequest):
    """
    Lists files and folders at path.
    Returns relative file paths with their modified time and length.
    """

    kind: Literal["list_files"] = "list_files"
    path: str = Field(default="")
    extensions: list[str] = Field(
        default=[".md"], description="Empty list maches all files."
    )
    max_depth: int = Field(default=1, description="-1 for infinite depth.")
    offset: int = Field(default=0)
    limit: int = Field(default=100, description="-1 for unlimited results.")
    sort_by: Literal["name", "length", "modified"] = Field(default="name")
    sort_order: Literal["asc", "desc"] = Field(default="asc")


class SearchFiles(BaseRequest):
    """
    Regex notes & text files and receive matches as
    <path>:<line> | <match> | <context>
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
    """List all users."""

    kind: Literal["list_users"] = "list_users"


class AdminUpsertUser(BaseRequest):
    """Upsert a user."""

    kind: Literal["upsert_user"] = "upsert_user"
    username: str = Field(...)
    token: str | None = Field(default=None)
    access: list[PathAccess] | None = Field(default=None)
    is_admin: bool | None = Field(default=None)
    delete_user: bool | None = Field(default=None)


class Batch(BaseRequest):
    """Send multiple requests, get multiple responses."""

    kind: Literal["batch"] = "batch"
    requests: list[ServerRequest] = Field(...)


class BaseResponse(BaseModel):
    kind: str = Field(..., description="Discriminator for response type")
    model_config = ConfigDict(extra="forbid")


class Success(BaseResponse):
    """Default response."""

    kind: Literal["success"] = "success"
    message: str = Field(default="")


class Error(BaseResponse):
    """Request failed."""

    kind: Literal["error"] = "error"
    message: str = Field(...)


class BatchResponse(BaseResponse):
    """Responses for a batch of requests."""

    kind: Literal["batch_response"] = "batch_response"
    responses: list[ServerResponse] = Field(...)


class VaultInfo(BaseResponse):
    """Name, path to daily notes."""

    kind: Literal["vault_info"] = "vault_info"
    name: str = Field(...)
    daily_notes_folder: str = Field(default="")
    user: User = Field(...)


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
    base_path: str = Field(default="")
    results: list[str] = Field(
        ...
    )  # Format: `<path> | <modified_at> | <length> <chars or b>`
    length: int = Field(...)
    offset: int = Field(default=0)
    limit: int = Field(default=100)


class SearchResults(BaseResponse):
    """Regex search results with context snippets."""

    kind: Literal["search_results"] = "search_results"
    results: list[str] = Field(...)  # Format: `<path>:<line> | <match> | <context>`
    length: int = Field(...)
    offset: int = Field(default=0)
    limit: int = Field(default=50)


class UsersList(BaseResponse):

    kind: Literal["users_list"] = "users_list"
    users: list[User] = Field(...)


# AI please keep these unions up to date w/ the current models.
# (this is the only part of this file you can edit without asking)

ServerRequest = Annotated[
    Union[
        GetVaultInfo,
        ReadText,
        ReplaceText,
        WriteText,
        AppendText,
        MoveFile,
        ListFiles,
        SearchFiles,
        AdminListUsers,
        AdminUpsertUser,
        Batch,
    ],
    Field(discriminator="kind"),
]

ServerResponse = Annotated[
    Union[
        Success,
        Error,
        VaultInfo,
        FileText,
        FilesList,
        SearchResults,
        UsersList,
        BatchResponse,
    ],
    Field(discriminator="kind"),
]


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
    - label: vault_name
    - label: server_error (when present)
    - labels: web_fqdn, api_fqdn, mcp_fqdn
    - paragraph: show the header auth setup and any other key setup details
    - link: username -> /users/<username>
    - link: "Users" -> /users
    - link: "Config" -> /config
    - button: "Logout" (logs out the current user)
    """

    vault_name: str
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
    - labels: vault_path, address, port, base_path
    - link: "<user_count> Users" -> /users
    """

    config: ServerConfig


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


class AddUserPage(UserPage):
    """
    path: /users/add
    title: Add User
    Equivalent to UserPage, but before it has a username and url.
    """
