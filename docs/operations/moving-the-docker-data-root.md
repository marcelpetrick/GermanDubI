# Moving Docker's data root to /home

**This is a record, not a recipe.** It was run once, on 2026-09-04, on the machine this
project is developed on, and it is kept here so the change is reviewable rather than
folklore. Nobody should need to run it again, and running it on a machine whose facts differ
from the ones below would be a mistake.

## Why

Docker stores everything under `/var/lib/docker`, which on this machine is the root
filesystem — 98 GB, and 90% full. `/home` is a separate 807 GB partition with 100 GB free.
Building the container image needs roughly 15 GB of transient space, and two builds had
already failed with `no space left on device` partway through unpacking NVIDIA libraries,
which does not look like a disk problem at first glance.

Docker supports this directly: `data-root` in `/etc/docker/daemon.json`. The daemon runs as
root, so there is no way to do it without `sudo`.

## What was checked first

Every one of these was verified on the machine before the script was written. They are the
reason it is this short:

| Fact | Why it mattered |
| --- | --- |
| `/etc/docker/` did not exist | A clean `daemon.json` create, with no existing configuration to merge or clobber |
| `/home` is ext4, mounted `rw,relatime` — same as `/` | overlay2 behaves identically. A `nodev` or `nosuid` mount, or a filesystem without `d_type`, would have broken it |
| `rsync` present | `-aHAX` copies with hardlinks preserved. **`-H` is the load-bearing flag**: overlay2 leans on hardlinks, and without it the copy balloons |
| 6.8 GB to move, 100 GB free on `/home` | Comfortable. The script checks anyway |
| `docker.socket` disabled, `docker.service` enabled | Stopping the service suffices, but the script stops both so socket activation cannot restart the daemon mid-copy |

## What happened

```
Docker Root Dir: /var/lib/docker  ->  /home/docker
/      9.9 GB free  ->  17 GB free   (+7.1 GB, after removing the old copy)
/home  100 GB free  ->  93 GB free
```

All eight images survived, which the script verifies by diffing the image list before and
after rather than by assertion.

Two notes for anyone reading this as a template:

- **The script does not delete the old data.** Reclaiming `/`'s space is a separate
  `sudo rm -rf /var/lib/docker`, printed at the end and run by hand afterwards. A copy of
  6.8 GB of images is a cheap safety net until the new root is seen to work, and `rm -rf` is
  not something to chain automatically behind an unattended rsync.
- **Its final check pulls `hello-world`.** That image was not cached, so `docker run` fetched
  it — a 20 KB side effect that stays behind. Harmless, and worth knowing about rather than
  wondering where it came from.

## The script, as run

```bash
#!/usr/bin/env bash
# Move Docker's data root from / to /home, which has the space.
#
# Verified beforehand on this machine: /home is ext4 with the same mount options as /, so
# overlay2 behaves identically; /etc/docker does not exist yet, so there is no daemon.json
# to merge with; rsync is present.
#
# The old data is left in place. Nothing is reclaimed on / until you run the last command
# this script prints, which is deliberate: a 6.8 GB copy of your images is a cheap safety
# net until you have seen the new root work.
set -euo pipefail

OLD=/var/lib/docker
NEW=/home/docker

if [[ $EUID -ne 0 ]]; then
  echo "run me with sudo" >&2
  exit 1
fi

echo "==> Before"
docker info --format 'root: {{.DockerRootDir}}' 2>/dev/null || true
docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | sort > /tmp/docker-images-before.txt || true
echo "images: $(wc -l < /tmp/docker-images-before.txt)"
need=$(du -sk "$OLD" | cut -f1)
have=$(df --output=avail -k /home | tail -1)
echo "need $((need / 1024)) MB, /home has $((have / 1024)) MB free"
(( have > need + 1048576 )) || { echo "not enough room on /home" >&2; exit 1; }

echo "==> Stopping Docker"
systemctl stop docker.socket 2>/dev/null || true
systemctl stop docker.service
sleep 2

echo "==> Copying $OLD -> $NEW  (-H preserves the hardlinks overlay2 relies on)"
mkdir -p "$NEW"
rsync -aHAX --info=progress2 "$OLD/" "$NEW/"

echo "==> Pointing the daemon at $NEW"
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<JSON
{
  "data-root": "$NEW"
}
JSON
cat /etc/docker/daemon.json

echo "==> Starting Docker"
systemctl start docker.service
sleep 3

echo "==> After"
docker info --format 'root: {{.DockerRootDir}}'
docker images --format '{{.Repository}}:{{.Tag}}' | sort > /tmp/docker-images-after.txt
echo "images: $(wc -l < /tmp/docker-images-after.txt)"

if diff -q /tmp/docker-images-before.txt /tmp/docker-images-after.txt >/dev/null; then
  echo "every image survived the move"
else
  echo "!! the image list changed:" >&2
  diff /tmp/docker-images-before.txt /tmp/docker-images-after.txt >&2 || true
  exit 1
fi

docker run --rm hello-world >/dev/null 2>&1 && echo "a container ran from the new root" \
  || echo "note: hello-world is not cached locally; skipping that check"

cat <<DONE

Done. Docker now stores everything under $NEW.

The old copy is still on / and still using the space. Once you are happy, reclaim it:

    sudo rm -rf $OLD

DONE
```
