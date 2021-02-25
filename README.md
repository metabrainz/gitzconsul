# gitzconsul

A Python alternative to git2consul

## Install poetry

https://python-poetry.org/docs/#installation

## Dev env

```bash
poetry shell
```

```bash
poetry install
```

```bash
gitzconsul --help
```

## Dependencies

- `git` command
- python >= 3.6
- python3 `requests` and `click` modules (see `pyproject.toml`)

## Usage

```
Usage: gitzconsul [OPTIONS]

  Register kv values into consul based on git repository content

Options:
  -r, --root TEXT                 root directory, relative to directory
                                  [default: ]

  -d, --directory TEXT            directory, must be absolute path  [required]
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


## Docker

### Build Image

```bash
docker build . -t gitzconsul
```


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
