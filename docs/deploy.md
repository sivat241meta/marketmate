# Deploying MarketMate on Modal

The app runs as a single Modal container with a persistent Volume for the
database and files.

## Prerequisites

- The project `.venv` with dev extras installed (`pip install -e ".[dev]"`).
- A Modal account.
- Log in once from this repo:

```bash
.venv/bin/modal token new
```

## Secrets

Create the secret from your local `.env` file (never print or commit keys):

```bash
.venv/bin/modal secret create marketmate-secrets --from-dotenv .env
```

To change `PUBLIC_BASE_URL` later (for example to the `*.modal.run` URL from
your first deploy), re-create the secret with `--force` and add the extra
value on the same command line. `--from-dotenv` plus a `KEY=VALUE` argument
works: the file provides the base values and the argument adds or overrides
one key:

```bash
.venv/bin/modal secret create marketmate-secrets --from-dotenv .env --force PUBLIC_BASE_URL=<url>
```

## Deploy

```bash
.venv/bin/modal deploy modal_app.py
```

Useful commands:

```bash
.venv/bin/modal app logs marketmate   # follow the app logs
.venv/bin/modal app stop marketmate   # stop the app
```

## Data

- Volume `marketmate-data` is mounted at `/data` and holds the SQLite
  database, photos, clips and cost ledger.
- One container only (`max_containers=1`), so SQLite has a single writer.
- The app scales to zero after 20 idle minutes and starts again on the next
  request.
- The `DAILY_BUDGET_USD` cap still applies on Modal.

## Smoke test

Run through this checklist on a phone over mobile data:

- [ ] Create a shop (`/new`).
- [ ] Upload a clip and wait for processing to finish.
- [ ] Approve the price list on the review page.
- [ ] Publish the version.
- [ ] Open the public shop page (`/s/<slug>`).
- [ ] Scan the QR code from the PDF price board.
- [ ] Search for an item on `/market`.

### Results

(To fill in after the deploy run.)
