# gitzconsul

Sync JSON files from a git repository into [Consul](https://www.consul.io/) KV store.

A lightweight Python alternative to [git2consul](https://github.com/breser/git2consul) (unmaintained Node.js project).
It clones a git repository, watches for changes, and flattens JSON files into Consul key/value pairs.

## Install uv

https://docs.astral.sh/uv/getting-started/installation/

## Dev env

```bash
uv sync
uv run gitzconsul --help
```

## Running tests

```bash
uv run ruff check gitzconsul tests
uv run ruff format gitzconsul tests
uv run python -m pytest -v --cov=gitzconsul tests/
```

## Dependencies

- `git` command
- python >= 3.10
- python3 `requests` and `click` modules (see `pyproject.toml`)

## Usage

```
Usage: gitzconsul [OPTIONS]

  Register kv values into consul based on git repository content

Options:
  -r, --root TEXT                 root directory to read files from, relative
                                  to directory  [default: ]

  -d, --directory TEXT            directory of the repository, will be created
                                  if needed  [required]

  -g, --git-url TEXT              git repository remote url
  -R, --git-ref TEXT              git repository remote ref  [default:
                                  refs/heads/master]

  -k, --consul-key TEXT           add keys under this key  [required]
  -u, --consul-url TEXT           consul url  [default: http://localhost:8500]
  -i, --interval INTEGER          interval in seconds between syncs  [default:
                                  15]

  -a, --consul-datacenter TEXT    consul datacenter
  -t, --consul-token TEXT         consul token
  -T, --consul-token-file TEXT    path to file containing consul token
  -f, --logfile TEXT              log file path
  -l, --loglevel [CRITICAL|ERROR|WARNING|INFO|DEBUG]
                                  log level  [default: INFO]
  -G, --debug                     output extra debug info
  --help                          Show this message and exit.
```

Typical directory structure will be:

```
topdir/
├── dir1
│   ├── file2.json
│   └── subdir1
│       ├── file1.json
│       └── ignored.txt
└── dir2
    └── somestuff
```

Typical `file1.json` (and `file2.json` for this example) would contain something like:

```json
{
  "key1": "foo",
  "key2": {
    "key3": "bar"
  }
}
```

```bash
gitzconsul --directory topdir/ --root dir1 --consul-key mytopkey
```

```bash
curl http://localhost:8500/v1/kv/mytopkey?keys
```

```json
[
    "mytopkey/file2.json/key1",
    "mytopkey/file2.json/key2/key3",
    "mytopkey/subdir1/file1.json/key1",
    "mytopkey/subdir1/file1.json/key2/key3"
]
```

- Files not ending with `.json` or unparseable json files are ignored.
- Directory specified by `--root` isn't prepended to keys and any content outside of it is ignored.
- JSON file names are used as keys (it keeps the extension)
- If a previously parsed json file becomes unparseable, keys related to it are left untouched.
- The default `--git-ref` is `refs/heads/master`. Use `--git-ref refs/heads/main` for repositories using `main` as default branch.

## How it works

gitzconsul clones a git repository and polls it for changes at a configurable interval (default: 15 seconds). On each cycle, it:

1. Fetches the latest changes from the remote repository
2. Walks the directory tree looking for `.json` files
3. Recursively flattens JSON objects into Consul key paths
4. Compares with existing Consul KV entries and applies only the diff (add/modify/delete)

JSON flattening rules:
- Nested objects become path segments: `{"a": {"b": "v"}}` → key `a/b`, value `v`
- Arrays and non-object values are stored as string values
- Booleans are stored as lowercase strings (`true`/`false`) for compatibility with git2consul
- Keys are URI-encoded (spaces become `%20`)
- Empty keys and keys containing the path separator (`/`) are skipped

## Requirements

- `git` must be installed and on your path
- Python >= 3.10
- Write access to the Consul KV store
- For private repositories: SSH key access (ssh:// URIs preferred)

## Differences from git2consul

gitzconsul is a lightweight alternative to [git2consul](https://github.com/breser/git2consul). Key differences:

- **Single repo only**: gitzconsul watches one repository (git2consul supports multiple)
- **Single branch only**: tracks one ref via `--git-ref` (git2consul supports multiple branches with branch name in key path)
- **Polling only**: no webhook support (git2consul supports GitHub, Stash, Bitbucket, and Gitlab webhooks)
- **JSON only**: no YAML or .properties file expansion (git2consul supports all three)
- **CLI configuration**: all options are command-line flags (git2consul uses a JSON config stored in Consul)
- **`--root` option**: equivalent to git2consul's `source_root`, limits which subdirectory is synced
- **`--consul-key` option**: equivalent to git2consul's repo `name`, used as the top-level key prefix
- **No branch name in keys**: keys are `<consul-key>/<path>/<file.json>/<json-key>` (git2consul includes the branch name)
- **No `expand_keys` toggle**: JSON expansion is always on (git2consul requires explicit opt-in)


## Docker

### Available images


Official docker images are available from [Docker Hub](https://hub.docker.com/r/metabrainz/gitzconsul)

```bash
docker pull metabrainz/gitzconsul
```

#### Available tags

- `latest`: the latest released image
- `vA.B.C`: released versionned image
- `edge`: the last build, upon last commit of the main github branch


### Build Image

```bash
docker build . -t gitzconsul
```

The image uses [tini](https://github.com/krallin/tini) as PID 1 to properly reap zombie processes spawned by git/ssh operations.


It will look for ssh files in /tmp/.ssh and copy them over proper user's home with proper perms:

```
/tmp/.ssh/id_rsa_shared
/tmp/.ssh/config
/tmp/.ssh/known_hosts
```

See `entrypoint.sh`

### Running

```bash
docker run --rm gitzconsul --help
```

### Examples

If git repository isn't public, you'll need to setup a deploy key, and pass it to the container.

```bash
ssh-keygen -t ed25519 -C 'gitzconsul' -P '' -f ./id_rsa_shared
```

Also to access consul, you may want to use network host mode (depending on your setup): `--net host`

Example of `docker run` command:

```bash
TOPKEY=mytopkey
DIRROOT=dir1
GITREPO=git@github.com:domain/project.git
docker run \
	--name gitzconsul \
	--volume $(pwd)/id_rsa_shared:/tmp/.ssh/id_rsa_shared:ro \
	--detach \
	--net host \
	gitzconsul \
		--root $DIRROOT \
		--consul-key $TOPKEY \
		--git-url $GITREPO \
		--directory /home/gitzconsul/repo
```
