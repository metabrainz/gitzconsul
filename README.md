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

## Running in a docker container

### Build Image

```bash
docker build . -t gitzconsul
```

### Running

```bash
docker run --rm gitzconsul --help
```


## References

- https://python-consul2.readthedocs.io/en/latest/

