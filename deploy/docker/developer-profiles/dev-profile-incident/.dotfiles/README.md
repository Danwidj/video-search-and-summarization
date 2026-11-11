# VM dotfiles

An optional shell setup for the VM, the Ubuntu VM that several accounts share. One idempotent bash script, `bootstrap.sh`, sets up your own account only; it is not team-wide provisioning.

## Run it

The VM already has this repo at `/srv/rise-up/vss`, so there is nothing to clone:

```bash
bash /srv/rise-up/vss/deploy/docker/developer-profiles/dev-profile-incident/.dotfiles/bootstrap.sh
```

Then start a new shell, or run `source ~/.bashrc`. Running it again picks up changes without touching `.bashrc` twice.

## What it sets up

- **Packages:** `curl`, `fzf`, `ripgrep`, `bat` (the binary is `batcat`) and `btop`, through `apt`. It skips any that are installed. `curl` is a hard prerequisite for the two installs below.
- **Prompt:** `starship` from a pinned GitHub release with a checksum check, and a config that always shows username and hostname. Set `BOOTSTRAP_SKIP_STARSHIP=1` to skip it.
- **Diffs:** `git-delta` from a pinned release into `~/.local/bin` with no `sudo`, wired into your own `git config --global`.
- **Shell:** `vim` runs the system `/opt/nvim`, `htop` runs `btop`, `cat` runs `bat`, and fzf gets its Ctrl-R and Ctrl-T bindings. `~/.local/bin` and `/opt/nvim/bin` join `PATH`.
- **`.bashrc`:** one marker-guarded block that sources the managed `shellrc.sh`. Everything else lives in files the script overwrites on each run.

## What is inside

| File | What it is |
|---|---|
| `bootstrap.sh` | The installer |
| `shellrc.sh`, `aliases.sh` | The managed shell setup and the four aliases |
| `starship.toml` | The prompt config |

## Rules

- Run it only on your own account. `apt install` is the one change that affects everyone.
- The script adds no VSS aliases and never sources the shared NGC credential on login. Run [ngc-env.sh](../.scripts/ngc-env.sh) with `source` when you need it.

## Read more

- [.scripts](../.scripts/README.md): the deploy-lifecycle commands
- [Operations runbook](../.docs/incident-profile-operations.md): running the VM
