# OpenEvent Lovable Frontend

Vite + React 18 frontend for Lovable deployment, connecting to the FastAPI backend.

## Quick Start on Lovable

1. **Import this folder** to Lovable (copy all files)

2. **Set environment variable** in Lovable dashboard:
   ```
   VITE_BACKEND_BASE=https://your-hostinger-domain.com
   ```
   (or your VPS IP like `http://123.456.789.0:8000`)

3. **Done!** Lovable will auto-install dependencies and run the dev server.

## Local Development

```bash
# Install dependencies
npm install

# Copy env file and edit
cp .env.example .env
# Edit .env: set VITE_BACKEND_BASE to your backend URL

# Run dev server
npm run dev
```

## Project Structure

```
lovable-frontend/
├── src/
│   ├── main.tsx           # Entry point
│   ├── router.tsx         # React Router routes
│   ├── index.css          # Tailwind + custom styles
│   ├── pages/
│   │   ├── ChatPage.tsx   # Main chat interface
│   │   ├── QnAPage.tsx    # FAQ page
│   │   └── RoomsPage.tsx  # Room availability
│   └── components/
│       └── DepositSettings.tsx
├── index.html
├── package.json
├── vite.config.ts
├── tailwind.config.js
└── .env.example
```

## Routes

| Path | Page | Description |
|------|------|-------------|
| `/` | ChatPage | Main chat interface for booking workflow |
| `/info/qna` | QnAPage | FAQ with category filtering |
| `/info/rooms` | RoomsPage | Room availability display |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `VITE_BACKEND_BASE` | Yes | Backend API URL (e.g., `https://api.yourdomain.com`) |
| `VITE_VERBALIZER_TONE` | No | Tone setting: `plain`, `formal`, `friendly` |

## Backend Connection

The frontend connects to these backend endpoints:
- `POST /chat` - Send messages to booking agent
- `GET /api/snapshots/:id` - Fetch snapshot data
- `GET /api/qna` - Fetch Q&A data
- `GET /api/config/global-deposit` - Deposit settings

Make sure your backend has CORS enabled for the Lovable domain.

## Tech Stack

- React 18.3
- Vite 5
- React Router 6
- Tailwind CSS 3
- TypeScript
- lucide-react (icons)
- react-markdown
