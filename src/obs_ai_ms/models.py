from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class ServerConfig(BaseModel):
    vault_path: str = Field(...)
    openapi_port: int = Field(default=8747)
    mcp_port: int = Field(default=8716)
    openapi_base: str = Field(default="/api")
    mcp_path: str = Field(default="/mcp")
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
    paths: str | list[str] = Field(...)
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
    ],
    Field(discriminator="kind"),
]
