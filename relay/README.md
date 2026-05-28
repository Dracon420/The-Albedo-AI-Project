# Albedo Relay Server

WebSocket relay that connects the Albedo phone app to the Albedo desktop through any home router — no port forwarding required.

## Deploy to Fly.io (one-time)

```bash
# Install flyctl if you don't have it
# Windows: winget install Fly.io.flyctl
# Then:

cd relay/
fly auth login
fly launch --name albedo-relay --region sea --yes
fly deploy
```

That's it. Fly.io gives you `https://albedo-relay.fly.dev` with free TLS.

## How it works

```
Phone App  ←── WSS ──→  albedo-relay.fly.dev  ←── WSS ──→  Albedo Desktop
```

1. Albedo Mission Control calls `POST /pair` once to get a token
2. Token is stored in settings.json and shown as a QR code in the MOBILE drawer tab
3. Phone app scans QR (or manually enters relay URL + token)
4. Both sides connect to the relay using the same token
5. All messages are forwarded in real time

## Local dev / testing

```bash
pip install -r requirements.txt
python main.py
# Server runs at http://localhost:8080
```
