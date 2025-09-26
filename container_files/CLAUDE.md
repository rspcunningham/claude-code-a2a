## Workspace layout

You are in a sandboxed 'workspace' directory. This directory will contain all files you need.

The directory structure looks like this:

```
workspace/
├── agent_outputs/          # end ouputs you create for the user
├── scripts/                # intermediate python scripts you use as you work
├── user_uploaded_data/     # data the user has uploaded to the workspace for you
├── .git/
├── .venv/
├── CLAUDE.md               # this file
└── pyproject.toml          # python configuration file
```

## General workspace instructions

You MUST follow these rules exactly. failure to do so will result in workspace corruption.

 - ALWAYS use python as your primary programming and scripting language.
 - NEVER modify the pyproject.toml file directly, or attempt to use 'pip'. ALWAYS use 'uv'. install packages using 'uv add <package_name>'and run scripts using 'uv run <script_name.py>'
 - ALWAYS create scripts to handle data manipulation and processing, rather than trying to do it manually. Any scripts you create should be placed in the 'scripts/' directory.
 - ALWAYS place end outputs for the user in the 'agent_outputs/' directory - this is the only directory that the user has read access to.
 - ALWAYS look at the 'user_uploaded_data/' directory for data the user has uploaded to the workspace for you - this is the only directory that the user has write access to.
 - ALWAYS use proper git commands to manage your workspace. Once you are sure that a certain operation has been completed successfully, commit your changes using 'git add .' and 'git commit -m "some description of what you did"'
 - NEVER use 'git push' or 'git pull' commands - there is no remote configured for this repo.
