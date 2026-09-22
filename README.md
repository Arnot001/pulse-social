# Pulse Social

Windows desktop tooling for social account utilities and emerging commerce intelligence.

## X Cleanup

- Delete Posts
- Delete Replies
- Undo Reposts
- Remove Likes
- Dry Run Preview
- Live Cleanup
- Browser Session Persistence
- Separate Activity Logs

## Pulse Commerce (foundation)

Pulse Social now contains the first Commerce Intelligence layer for deal monitoring.

Current foundation:

- Normalized product observations
- SQLite product/price history in `%LOCALAPPDATA%\Pulse Social\commerce.db`
- TikTok Shop adapter boundary for PDH-captured product payloads
- Initial Pulse Deal Score
- Price anomaly scoring
- Seller-confidence scoring
- Specification-confidence scoring
- Sales-momentum scoring
- CLI ingestion path for reconnaissance payloads

The TikTok adapter intentionally does **not** hard-code undocumented/private endpoints. The next step is Pulse Data Hunter reconnaissance on TikTok Shop to identify the stable product payloads already delivered to the browser, then tighten `commerce/tiktok/normalizer.py` around the confirmed schema.

Test a captured product-shaped JSON payload with:

```powershell
python -m commerce.ingest .\captured_product.json
```

## Requirements

- Windows 10/11
- Brave Browser
- Python 3.13+

## Installation

Install the Pulse Social application and launch:

`Pulse Social.bat`

On first launch:

1. Enter your X handle.
2. Click Open Browser / Start Session.
3. Log into X if required.
4. Click Continue Cleanup.
5. Choose Dry Run or Live mode.

Your browser session is saved for future launches.

Pulse Social never stores your X password.


## TikTok Auto Post

Pulse Social now separates TikTok setup into two modes:

- **Customer mode** — users only see `CONNECT TIKTOK`, `TEST`, and `DISCONNECT`. The TikTok Client Secret stays on the Pulse backend.
- **Local development mode** — when no backend URL is configured, maintainers can use `DEV SET APP` to test with local encrypted developer credentials.

Customer builds should set:

```text
PULSE_TIKTOK_BACKEND_URL=https://your-pulse-backend.example
```

The backend implementation lives in `pulse_backend/app.py`. Configure these **server-side only**:

```text
TIKTOK_CLIENT_KEY=...
TIKTOK_CLIENT_SECRET=...
TIKTOK_REDIRECT_URI=http://127.0.0.1:3455/callback/
TIKTOK_SCOPES=user.info.basic,video.publish
```

The intended customer experience is simply:

```text
CONNECT TIKTOK
→ TikTok sign-in / consent
→ return to Pulse Social
→ CONNECTED
```

No customer should need TikTok for Developers, a Client Key, a Client Secret, scopes, redirect-URI setup, or manual access-token pasting.
