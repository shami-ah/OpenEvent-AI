# OpenEvent Frontend Reference

**Purpose:** This document describes the frontend structure of the OpenEvent main application. Use this as context when building integrations.

**Last Updated:** 2025-12-08

---

# 1. APPLICATION OVERVIEW

OpenEvent is a **multi-tenant event management SaaS** built with:
- React 18 + TypeScript + Vite
- Tailwind CSS + Shadcn/ui components
- Supabase (PostgreSQL + Auth)
- Stripe (payments)

**Key Concept:** Everything is scoped to a `team_id`. Users belong to teams, and all data (events, clients, rooms, etc.) is filtered by team.

---

# 2. NAVIGATION STRUCTURE

## 2.1 Main Sidebar Menu

```
┌─────────────────────────────────┐
│  MAIN MENU                      │
├─────────────────────────────────┤
│  📅 Calendar      → /calendar   │
│  📥 Inbox         → /inbox      │
│  👥 CRM           → /crm        │
│  📄 Offers        → /offers     │
│  👤 Staff         → /staff      │
│  ✅ Tasks         → /tasks      │
├─────────────────────────────────┤
│  SETUP (collapsible)            │
├─────────────────────────────────┤
│  🏢 Venue         → /setup/venue     │
│  🚪 Rooms         → /setup/rooms     │
│  📦 Products      → /setup/products  │
│  📄 Offers Setup  → /setup/offers    │
│  ✉️ Templates     → /setup/templates │
├─────────────────────────────────┤
│  OTHER                          │
├─────────────────────────────────┤
│  📊 Dashboard     → /dashboard  │
│  ⚙️ Settings      → /settings   │
│  💬 Feedback      → /feedback   │
└─────────────────────────────────┘
```

## 2.2 All Routes

### Public Routes (No Auth)
| Route | Page | Purpose |
|-------|------|---------|
| `/` | LandingPage | Marketing homepage |
| `/login` | Login | Authentication |
| `/register` | Register | Multi-step signup |
| `/contact` | Contact | Contact form |
| `/terms` | TermsOfService | Legal |
| `/privacy` | PrivacyPolicy | Legal |

### Protected Routes (Requires Auth)
| Route | Page | Purpose |
|-------|------|---------|
| `/dashboard` | Dashboard | Overview with stats |
| `/calendar` | Calendar | Event scheduling (multi-view) |
| `/inbox` | Inbox2 | Email management |
| `/crm` | CRM | Client management |
| `/offers` | Offers | Quote/offer management |
| `/staff` | Staff | Staff scheduling |
| `/tasks` | Tasks | Task management (Kanban) |
| `/profile` | Profile | User profile |
| `/settings` | PreferencesSettings | App settings (tabs) |

### Setup Routes
| Route | Page | Purpose |
|-------|------|---------|
| `/setup/venue` | VenueSetup | Venue info & logo |
| `/setup/rooms` | RoomsSetup | Room management |
| `/setup/products` | ProductsSetup | Product catalog |
| `/setup/knowledge` | KnowledgeSetup | AI knowledge base |
| `/setup/offers` | OffersSetup | Offer templates & deposit settings |
| `/setup/templates` | EmailTemplatesPage | Email templates |

### Event Routes
| Route | Page | Purpose |
|-------|------|---------|
| `/events/:id/:tab?` | EventDetail | Full event details (tabbed) |
| `/events/:eventId/tickets/dashboard/:ticketId` | TicketDashboard | Ticket management |

### Public/External Routes
| Route | Page | Purpose |
|-------|------|---------|
| `/public-offer/:id` | PublicOffer | Client views offer |
| `/confirm-offer/:token` | ConfirmOffer | Client confirms offer |
| `/ticket/:slug` | PublicTicketPage | Public ticket sales |
| `/ticket/:slug/success` | TicketOrderSuccess | Purchase confirmation |

---

# 3. MAIN SECTIONS

## 3.1 Calendar (`/calendar`)

**Purpose:** Event scheduling and visualization

**Views Available:**
- Month view
- Week view
- Day view
- List view
- Pipeline view (Kanban-style by status)

**Features:**
- Filter by room
- Filter by status (lead/option/confirmed/cancelled)
- Create events by clicking date
- Drag-and-drop events
- Color-coded by room

**Data Displayed:**
- Event title
- Date/time
- Room assignment
- Status badge
- Client name

---

## 3.2 Inbox (`/inbox`)

**Purpose:** Email management with IMAP/Gmail integration

**Features:**
- Email folder management (Inbox, Sent, Drafts, etc.)
- Conversation threading
- AI-powered reply suggestions
- Email signatures
- Email templates
- Manual follow-up scheduling
- Compact and full-screen views

**Email Record Contains:**
- from_email, to_email
- subject, body_text, body_html
- received_at, is_read, is_starred
- event_id (optional link to event)
- client_id (optional link to client)
- thread_id (for conversation grouping)

---

## 3.3 CRM (`/crm`)

**Purpose:** Client relationship management

**List View Columns:**
- Name
- Company
- Status (badge)
- Last Contact Date

**Client Statuses:**
- `lead` - New inquiry
- `option` - Interested/negotiating
- `confirmed` - Active customer
- `cancelled` - Lost/cancelled

**Client Record Contains:**
- name (required)
- email
- phone
- company
- position
- address
- website_social
- notes
- status
- last_contact_date

**Actions:**
- Add new client
- Edit client
- Delete client
- View client details
- See client's events

---

## 3.4 Offers (`/offers`)

**Purpose:** Create and manage quotes/offers for events

**List View Features:**
- Search by client/offer number
- Filter by status (Draft, Sent, Confirmed)
- Filter by payment status
- Filter by date range
- Filter by amount range
- Sort by multiple fields

**Offer Statuses:**
- Draft
- Sent
- Confirmed
- Cancelled

**Offer Record Contains:**
- offer_number (unique)
- subject
- client info (name, email, company, address)
- provider info (your company details)
- offer_date, valid_until
- subtotal, vat_amount, total_amount
- deposit settings (enabled, type, percentage, amount, paid_at)
- terms_and_conditions
- event_id (linked event)

**Offer Line Items:**
- Products from catalog
- Custom line items
- Room charges

---

## 3.5 Staff (`/staff`)

**Purpose:** Staff scheduling and shift management

**Features:**
- Staff roster with roles
- Shift calendar
- Open shifts board
- Availability tracking

**Available Roles:**
- Bartender
- Waiter
- Host
- Security
- DJ
- Kitchen Staff
- Manager
- Server
- Cleaner

**Shift Record Contains:**
- title
- date, start_time, end_time
- location
- required_roles
- max_assignees
- status

---

## 3.6 Tasks (`/tasks`)

**Purpose:** Task management with Kanban board

**Task Categories:**
- All Tasks
- Event Tasks
- Client Follow-ups
- Email Tasks
- Invoice Tasks

**Task Priorities:**
- Low
- Medium
- High

**Task Record Contains:**
- title
- description
- category
- priority
- status
- due_date
- assignee_id (team member)
- event_id (optional)
- client_name
- completed, completed_at

**Features:**
- Kanban board view
- Filter by team member
- Sort by due date, priority, assignee
- Task comments
- Subtasks

---

# 4. SETUP PAGES

## 4.1 Venue Setup (`/setup/venue`)

**Input Fields:**
| Field | Type | Purpose |
|-------|------|---------|
| Venue name | text | Display name |
| Street address | text | Location |
| City | text | Location |
| Postal code | text | Location |
| Country | text | Location |
| Website URL | url | Marketing |
| Short description | textarea | About |
| Logo | file upload | Branding (max 5MB) |

---

## 4.2 Rooms Setup (`/setup/rooms`)

**Input Fields per Room:**
| Field | Type | Purpose |
|-------|------|---------|
| Name | text | Room identifier |
| Description | textarea | Details |
| Capacity | number | Max people |
| Amenities | multi-select | Features list |
| Rate type | select | hourly/daily/fixed/consumption |
| Hourly rate | currency | Price if hourly |
| Daily rate | currency | Price if daily |
| Fixed rate | currency | Price if fixed |
| Minimum consumption | currency | If consumption-based |
| VAT rate | percentage | Tax rate |
| Include VAT | toggle | Tax included in price? |
| Color | color picker | Calendar display |

**Layout Capacities (separate fields):**
- Theater capacity
- Cocktail capacity
- Seated dinner capacity
- Standing capacity

---

## 4.3 Products Setup (`/setup/products`)

**Input Fields per Product:**
| Field | Type | Purpose |
|-------|------|---------|
| Name | text | Product name |
| Description | textarea | Details |
| Category | select | Product type |
| Base price | currency | Selling price |
| Internal price | currency | Cost price |
| Price type | select | hourly/daily/fixed |
| VAT rate | percentage | Tax rate |
| Include VAT | toggle | Tax included? |
| Available | toggle | Can be sold? |
| External supplier | toggle | From third party? |
| Supplier name | text | If external |
| Supplier email | email | If external |
| Supplier description | textarea | If external |

---

## 4.4 Offers Setup (`/setup/offers`)

**Company Information:**
| Field | Type | Purpose |
|-------|------|---------|
| Company name | text | Your business name |
| Street address | text | Business address |
| City | text | Business address |
| Postal code | text | Business address |
| Country | text | Business address |

**Offer Settings:**
| Field | Type | Purpose |
|-------|------|---------|
| Validity period | number/select | Days offer is valid |
| Offer numbering | select | Auto or manual |
| Cancellation policy | rich text | Policy text |
| Terms & conditions | rich text | Legal text |

**Deposit Settings:**
| Field | Type | Purpose |
|-------|------|---------|
| Deposit enabled | toggle | Require deposit? |
| Deposit type | select | Percentage or Fixed |
| Deposit percentage | number | If percentage type |
| Deposit amount | currency | If fixed type |
| Deposit deadline | select | 10/30/custom days |

---

## 4.5 Knowledge Base Setup (`/setup/knowledge`)

**Purpose:** Configure AI assistant knowledge

**Sections:**
- Links (URLs with language/currency)
- Documents (uploaded files)
- Notes (rich text content)
- Room suggestions
- Product suggestions

---

# 5. KEY FORMS & DIALOGS

## 5.1 New Event Dialog

**Fields:**
| Field | Type | Required |
|-------|------|----------|
| Event name | text | Yes |
| Event date | date | Yes |
| End date | date | No (multi-day) |
| Start time | time | Yes |
| End time | time | Yes |
| Client | select/create | No |
| Room(s) | multi-select | No |
| Status | select | Yes |
| Attendees | number | No |
| Description | textarea | No |
| Notes | textarea | No |
| Assigned to | select | No |

**If creating new client inline:**
- Contact name
- Contact email
- Contact company
- Contact phone

---

## 5.2 New Client Dialog

**Fields:**
| Field | Type | Required |
|-------|------|----------|
| Name | text | Yes (min 2 chars) |
| Email | email | No |
| Phone | tel | No |
| Company | text | No |
| Position | text | No |
| Address | text | No |
| Website/Social | url | No |
| Notes | textarea | No |
| Status | select | No (default: lead) |

---

## 5.3 New Task Dialog

**Fields:**
| Field | Type | Required |
|-------|------|----------|
| Title | text | Yes |
| Description | textarea | No |
| Category | select | Yes |
| Priority | select | No (default: medium) |
| Due date | date | No |
| Assignee | select | No |
| Event | select | No |

---

## 5.4 Create Offer Dialog

**Fields:**
| Field | Type | Required |
|-------|------|----------|
| Event | select | Optional |
| Client | select/input | Yes |
| Subject | text | Yes |
| Offer date | date | Yes |
| Valid until | date | Yes |
| Products | multi-select | No |
| Custom items | dynamic list | No |

---

# 6. SETTINGS PAGE TABS

## Tab 1: Emails
- Connect email accounts (IMAP, Gmail)
- Manage connected accounts
- Set account scope (personal/team)

## Tab 2: Payments
- Connect Stripe account
- Manage saved payment methods
- View payment settings

## Tab 3: Teams
- View team members
- Invite new members
- Manage roles
- Remove members
- Pending invitations

## Tab 4: Preferences
- Default calendar view
- Default view mode
- Currency selection
- VAT options
- Theme (Light/Dark)
- Notifications
- Auto-refresh settings

---

# 7. DATA ENTITIES SUMMARY

| Entity | Primary Fields | Status Field |
|--------|----------------|--------------|
| **Client** | name, email, phone, company | lead/option/confirmed/cancelled |
| **Event** | title, event_date, start_time, end_time, room_ids | lead/option/confirmed/cancelled/blocked |
| **Offer** | offer_number, subject, total_amount | draft/sent/confirmed |
| **Task** | title, category, priority, due_date | pending/in_progress/completed |
| **Room** | name, capacity, amenities, rate_type | - |
| **Product** | name, base_price, category_id | available (boolean) |
| **Email** | from_email, subject, body_text | is_read, is_sent |

---

# 8. IMPLEMENTATION STATUS

## Fully Implemented (Production Ready)
- Calendar (all views)
- CRM (client management)
- Tasks (Kanban board)
- Offers (quote management + PDF export)
- Staff (scheduling)
- All Setup Pages
- Inbox (email with IMAP/Gmail)
- Dashboard
- Settings & Preferences
- Authentication

## Partially Implemented
- Feedback/Forum (basic structure)
- Ticket system (preview mode)

## Future Extensions (Not Yet Built)
- Client preference tracking
- Advanced analytics
- Automated follow-ups
- Multi-language support

---

# 9. INTEGRATION POINTS FOR EMAIL WORKFLOW

## What the Email Workflow Creates/Updates:

| Entity | Action | Key Fields |
|--------|--------|------------|
| **Client** | Create or find | name, email, company (team_id, user_id required) |
| **Event** | Create | title, event_date, start_time, end_time, status, room_ids, attendees |
| **Offer** | Create | offer_number, subject, total_amount, deposit fields |
| **Task** | Create | title, category, event_id (for HIL approvals) |
| **Email** | Create | Store conversation history |

## What the Email Workflow Reads:

| Entity | Purpose |
|--------|---------|
| **Rooms** | Check availability, get capacity, get deposit settings |
| **Products** | Build offer line items |
| **Clients** | Find existing client by email |
| **Events** | Check existing bookings for date conflicts |

## Required Configuration:

| Item | Purpose |
|------|---------|
| `team_id` | Which team the workflow operates for |
| `user_id` | System user identity for database writes |
| `email_account_id` | Email account for sending/receiving |

---

# 10. FRONTEND PATTERNS

## Form Validation
Uses custom `useFormValidation` hook with:
- Required field checking
- Type validation (email, tel, url, number)
- Length constraints
- Pattern matching

## Data Fetching
Uses React Query with:
- Team-based filtering (`eq("team_id", team_id)`)
- Optimistic updates
- Cache invalidation

## State Management
- Server state: React Query
- Auth state: AuthContext
- Local state: useState/useReducer

## Component Library
Shadcn/ui components:
- Dialog, Sheet, Popover
- Select, Input, Textarea
- Button, Badge, Card
- Table, Tabs
- Calendar, DatePicker

---

*End of Frontend Reference*