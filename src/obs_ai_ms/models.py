from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class ServerConfig(BaseModel):
    vault_path: str = Field(...)
    api_key: str | None = Field(default=None)
    api_port: int = Field(default=8747)
    api_path: str = Field(default="/api")
    mcp_port: int = Field(default=8716)
    mcp_path: str = Field(default="/mcp")


class BaseRequest(BaseModel):
    kind: str = Field(..., description="Discriminator for request type")
    model_config = ConfigDict(extra="forbid")


class ReadText(BaseRequest):
    """Read path text."""

    kind: Literal["read_file"] = "read_file"
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
    copy: bool = Field(default=False, description="Set to true to copy the file.")


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


class BaseResponse(BaseModel):
    kind: str = Field(..., description="Discriminator for response type")
    model_config = ConfigDict(extra="forbid")


class Success(BaseResponse):
    """Request succeeded."""

    kind: Literal["success"] = "success"


class Error(BaseResponse):
    """Request failed."""

    kind: Literal["error"] = "error"
    message: str = Field(...)


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


# AI please keep these unions up to date w/ the current models.
# (this is the only part of this file you can edit without asking)

ServerRequest = Annotated[
    Union[ReadText, ReplaceText, WriteText, AppendText, MoveFile, ListFiles],
    Field(discriminator="kind"),
]

ServerResponse = Annotated[
    Union[Success, Error, FileText, FilesList],
    Field(discriminator="kind"),
]
