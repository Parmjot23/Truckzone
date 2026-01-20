# Mechanics App (React Native + Expo)

Mobile app for mechanics to view assigned jobs, update status, capture photos/signature, manage parts, and sync with the backend.

## Stack
- Expo SDK 53 (React Native 0.79, React 19)
- TypeScript
- React Navigation (stack + tabs)
- React Query (with AsyncStorage persistence)
- Axios
- React Native Paper
- Expo Camera, Notifications, BackgroundFetch, TaskManager

## Requirements
- Node 18+ (Node 22 recommended)
- Android Studio (emulator) or device; iOS requires macOS
- Backend API accessible from device/emulator

## Setup
1. Copy env and set API base URL:
```
cp .env.example .env.development
# Edit EXPO_PUBLIC_API_BASE_URL, e.g.
# Android emulator -> http://10.0.2.2:8000/api
# Physical device (LAN) -> http://<your-computer-LAN-IP>:8000/api
```

2. Install deps (already installed if scaffolded):
```
npm install
```

3. Start Metro / run app:
```
# Start Dev server
npm run start

# Open Android emulator
npm run android

# Or open iOS simulator (macOS only)
npm run ios
```

## Features
- Login with secure token storage
- Jobs list with search and auto polling
- Job details with status workflow and timestamps
- Photo capture and upload to job
- Signature capture and submission
- Parts search and add to job
- Background sync stub (BackgroundFetch)
- Offline cache for queries (AsyncStorage persistence)

## Notes
- Permissions are configured in app.json for Camera and Location.
- Background sync may be limited on simulators; test on device where possible.
- Endpoints expected (adjust to your backend):
  - POST /auth/login/ -> { access: string }
  - POST /auth/logout/
  - GET /jobs/?search=...
  - GET /jobs/:id/
  - POST /jobs/:id/status/ { status }
  - POST /jobs/:id/attachments/ multipart/form-data (file)
  - POST /jobs/:id/signature/ { dataUrl }
  - GET /parts/?search=...
  - POST /jobs/:id/parts/ { partId, quantity }

## Troubleshooting
- Android emulator cannot reach local backend: use 10.0.2.2 instead of localhost.
- Clear Metro cache if bundling issues:
```
npm run clean
```
- Enable LAN in Expo dev tools if device testing.

## Scripts
- npm run start – start dev server
- npm run android / ios / web – open platform
- npm run clean – clear Metro cache
- npm run typecheck – TypeScript checks