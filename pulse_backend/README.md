# Pulse Social TikTok OAuth backend

This small service keeps the TikTok **Client Secret** out of distributed Pulse Social desktop builds.

## Environment

Set these on the server only:

```text
TIKTOK_CLIENT_KEY=...
TIKTOK_CLIENT_SECRET=...
TIKTOK_REDIRECT_URI=http://127.0.0.1:3455/callback/
TIKTOK_SCOPES=user.info.basic,video.publish
```

Never ship `TIKTOK_CLIENT_SECRET` inside the desktop application.

## Run locally for development

```powershell
uvicorn pulse_backend.app:app --host 127.0.0.1 --port 8765
```

Then launch the desktop app with:

```powershell
$env:PULSE_TIKTOK_BACKEND_URL="http://127.0.0.1:8765"
py pulse_social_launcher.py
```

For a customer build, set `PULSE_TIKTOK_BACKEND_URL` to the deployed HTTPS Pulse backend. The TikTok Auto Post UI then hides all app-secret setup and shows only **CONNECT TIKTOK**, **TEST**, and **DISCONNECT**.

The current desktop stores each user's TikTok access/refresh token encrypted with Windows DPAPI. A later backend-account phase can move user refresh-token custody fully server-side.
