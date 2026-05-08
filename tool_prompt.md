Access the Obsidian vault. Send a JSON array string: '[{"kind":"get_vault_info"}, ...]'

Request kinds:
- get_vault_info: Vault and your user access.
- read_text(path, offset=0, limit=20000 "-1 for unlimited chars."): Notes or other text files.
- replace_text(path, old_text, new_text, count=1 "Set to -1 for unlimited."): Replace 1 or more.
- write_text(path, text): Overwrite with new text, creates intermediate dirs.
- append_text(path, text): Direct append, you handle newlines.
- move_file(old_path, new_path=None "Omit to delete.", make_copy=false "Keeps original."): Moves, copies, or deletes.
- list_files(path="", extensions=[".md"] "Empty list matches all files.", max_depth=1 "-1 for infinite depth.", offset=0, limit=100 "-1 for unlimited results.", sort_by="name" [name|length|modified], sort_order="asc" [asc|desc]): Folder tree, returns: `<path> | <modified_at> | <length>`
- search_files(pattern, path="", extensions=[".md"], max_depth=-1, context_chars=120, offset=0, limit=100): Regex filenames and text contents, returns: `<path>:<line> | <match> | <context>`
- list_users: 
- upsert_user(username, token=None, access=None, is_admin=None, delete_user=None): Creates, updates or deletes.
