# Changelog

## v1.0.1 — 2026-03-23
- Fix `check_upstream` returning inconsistent tuple size → 500 error on Check Update
- Fix `docker-compose.yml` removing `noip_app` volume that overwrote `/app`
- Fix `pull_policy: never` to prevent Portainer pulling from Docker Hub
- Add `VERSION` file copied into Docker image
- Add version display on all pages (nav + footer)

## v1.0.0 — 2026-03-23
- Initial release
- Flask web UI with landing page, setup guide, config page
- Playwright automation for No-IP login + 2FA + host confirmation
- APScheduler for automatic scheduled runs
- Self-update via Docker socket
- Live log with real-time polling
