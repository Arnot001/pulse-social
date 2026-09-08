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
