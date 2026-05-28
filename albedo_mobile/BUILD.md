# Albedo Mobile — Build Guide

## Prerequisites

- Flutter SDK ≥ 3.3.0 (https://docs.flutter.dev/get-started/install/windows)
- Android SDK (comes with Android Studio or via `sdkmanager`)
- Java 11+ in PATH

## One-time setup

```powershell
cd "C:\Users\demon\Desktop\Local Cortana AI\albedo_mobile"

# Check Flutter is working
flutter doctor

# Get dependencies
flutter pub get
```

## Build release APK

```powershell
flutter build apk --release
```

APK output: `build\app\outputs\flutter-apk\app-release.apk`

Transfer to phone (USB, ADB, or file share) and install.

---

## Deploy the relay (Fly.io) — one-time

```powershell
cd "C:\Users\demon\Desktop\Local Cortana AI\relay"

# Install flyctl if not already: https://fly.io/docs/hands-on/install-flyctl/
# Sign up / log in (free tier, no credit card for hobby apps)
fly auth login

# Create the app (first time only)
fly launch --no-deploy

# Deploy
fly deploy
```

Relay will be live at `wss://albedo-relay.fly.dev/ws`.

---

## Pair the phone

1. Start Albedo Mission Control on your PC
2. Open the **MOBILE** tab in the drawer
3. Click **GENERATE CODE** — a QR code appears
4. Open the Albedo app on your phone
5. Tap **Scan QR** and point at the screen
6. Done — the status dot turns green when the phone connects

---

## Install `websockets` in Albedo venv (if not already installed)

```powershell
cd "C:\Users\demon\Desktop\Local Cortana AI"
.venv\Scripts\python -m pip install websockets
```
