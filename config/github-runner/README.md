# GitHub Actions runner foundation

The dedicated `github-runner` account has no sudo or Docker-group membership. `/srv/builds/github-runner` is reserved for the runner installation and `/srv/repos/github-actions` for checked-out work.

Registration is intentionally not performed. It requires the repository or organization URL plus a short-lived GitHub registration token. After those are supplied, download the current runner archive from the official GitHub Actions runner release, verify its published checksum, extract it as `github-runner`, and run `config.sh` as that user. Install the service only after reviewing which repositories and workflows are trusted.

Giving a runner Docker access is equivalent to giving every accepted workflow root access to this server. Keep this runner out of the Docker group; route container builds through a separately reviewed isolated worker or a remote builder. Never attach it to public-fork pull-request workflows with secrets.

