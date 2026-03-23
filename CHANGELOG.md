# Changelog

## v1.0.1 — 2026-03-23 17:45:00 GMT+7
- Fix `check_upstream` returning inconsistent tuple → 500 error on Check Update
- Fix `docker-compose.yml` removing `noip_app` volume that overwrote `/app`
- Fix `pull_policy: never` to prevent Portainer pulling from Docker Hub
- Add `VERSION` file copied into Docker image
- Add version + build datetime on all pages (nav + footer)
- Add `CHANGELOG.md`

## v1.0.0 — 2026-03-23 09:00:00 GMT+7
- Initial release
- Flask web UI: landing page, setup guide, config page
- Playwright automation: No-IP login + 2FA TOTP + host confirmation
- APScheduler for automatic scheduled runs
- Self-update via Docker socket
- Live log with real-time polling
- Persistent config in Docker volume
