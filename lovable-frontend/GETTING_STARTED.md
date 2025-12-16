# Getting Started with OpenEvent Frontend on Lovable

## What is this?

This is the **frontend** (the visual interface) for the OpenEvent booking system. It's where:
- Clients chat with the AI booking assistant
- Managers review and approve AI-generated messages before they're sent
- You can view room availability and FAQ pages

The frontend talks to a **backend** (the brain) hosted on Hostinger that handles all the AI logic, database, and email sending.

---

## How to Set It Up on Lovable

### Step 1: Import the Project
1. Create a new project in Lovable
2. Upload/import all files from this `lovable-frontend` folder

### Step 2: Set the Backend URL
In Lovable's project settings, add this environment variable:

```
VITE_BACKEND_BASE = https://[your-hostinger-domain-or-ip]:8000
```

Replace `[your-hostinger-domain-or-ip]` with the actual backend URL once Hostinger is set up.

### Step 3: Done!
Lovable will automatically install everything and run the app.

---

## The Three Pages

| URL | What it does |
|-----|--------------|
| `/` | **Main Chat** - The booking conversation + manager approval panel |
| `/info/qna` | **FAQ Page** - Frequently asked questions about the venue |
| `/info/rooms` | **Rooms Page** - Room availability and details |

---

## The Manager Panel (Right Side of Chat)

When you open the main chat (`/`), you'll see two columns:

**Left side:** The chat conversation (client ↔ AI)

**Right side:** Manager controls
- **Pending Tasks** - AI messages waiting for your approval
- **Edit before sending** - You can modify any AI response before it goes to the client
- **Approve & Send** - Sends the message to the client
- **Discard** - Rejects the AI's suggestion
- **Manager Notes** - Add notes for yourself

### How HIL (Human-in-the-Loop) Works
1. Client sends a message
2. AI generates a response
3. Response appears in "Pending Tasks" on the right
4. You review, edit if needed, then approve or discard
5. Only approved messages reach the client

---

## Testing Without Backend

Until the Hostinger backend is running, you'll see connection errors. That's normal - the frontend needs the backend to work.

For now you can:
- Explore the UI layout
- Check the design and styling
- See how the pages are structured

Once the backend is live, everything will connect automatically.

---

## Making Changes

Edit any file in Lovable to change the design:

| Want to change... | Edit this file |
|-------------------|----------------|
| Chat interface | `src/pages/ChatPage.tsx` |
| FAQ page | `src/pages/QnAPage.tsx` |
| Rooms page | `src/pages/RoomsPage.tsx` |
| Colors & fonts | `src/index.css` |
| Deposit settings component | `src/components/DepositSettings.tsx` |

The styling uses **Tailwind CSS** - classes like `bg-blue-500`, `text-white`, `p-4` control the appearance directly in the HTML.

---

## Questions?

- **Frontend not loading?** Check if environment variable `VITE_BACKEND_BASE` is set
- **"Failed to fetch" errors?** Backend isn't running yet - that's expected
- **Want to change something?** Just edit the files in Lovable and it auto-refreshes