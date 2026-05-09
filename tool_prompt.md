Access one or more Obsidian vaults.
Send a JSON array string: '[{"kind":"get_vault_info"}, ...]'

Request kinds:
- get_vault_info: Your vaults and access.
- read_text(path, offset=0, limit=20000 "-1 for unlimited chars."): Notes and text files.
- replace_text(path, old_text, new_text, count=1 "-1 for unlimited."): Replace 1+.
- write_text(path, text): Overwrite.
- append_text(path, text, prepend=false): Newlines up to you.
- move_file(old_path, new_path=None "Omit to delete.", make_copy=false "Keeps original."): Move, copy, or delete.
- list_files(path="", extensions=[".md"] "Empty matches all.", max_depth=1 "-1 for unlimited.", offset=0, limit=100 "-1 for unlimited results.", sort_by="name" [name|length|modified], sort_order="asc" [asc|desc]): Folder tree, returns: `<path> | <modified_at> | <length>`
- search_files(pattern, path="", extensions=[".md"], max_depth=-1, context_chars=120, offset=0, limit=100): Regex names and content, returns: `<path>:<line> | <match> | <context>`
- list_users: 
- upsert_user(username, token=None, access=None, is_admin=None, delete=None): Create, update or delete.
- upsert_vault(name, dir_path, delete=None): Create, update or delete.
