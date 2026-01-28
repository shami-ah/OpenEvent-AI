  PROMPT 1: Event Request Inbox Tab                                                                                                                                                             
                                                                                                                                                                                                
  # Build: Event Request Inbox Tab                                                                                                                                                              
                                                                                                                                                                                                
  Add a new tab "Event Requests" to the existing Inbox page with a 3-panel layout.                                                                                                              
                                                                                                                                                                                                
  ## Layout                                                                                                                                                                                     
                                                                                                                                                                                                
  ┌────────────────┬──────────────────────────────┬─────────────────────┐                                                                                                                       
  │ Thread List    │ Email Thread View            │ Context Panel       │                                                                                                                       
  │ (280px fixed)  │ (flex grow)                  │ (380px fixed)       │                                                                                                                       
  └────────────────┴──────────────────────────────┴─────────────────────┘                                                                                                                       
                                                                                                                                                                                                
  ## Left Panel: Thread List                                                                                                                                                                    
                                                                                                                                                                                                
  Each row shows:                                                                                                                                                                               
  - Avatar circle (initials, 40px)                                                                                                                                                              
  - Client name (bold) + timestamp (right, muted)                                                                                                                                               
  - Star icon (yellow when starred)                                                                                                                                                             
  - Subject line (truncated)                                                                                                                                                                    
  - Preview text (muted, truncated)                                                                                                                                                             
  - Status badge: Lead (gray), Option (amber), Confirmed (green), Cancelled (red)                                                                                                               
                                                                                                                                                                                                
  Selected row: blue-50 background with blue left border.                                                                                                                                       
                                                                                                                                                                                                
  Top: Filter dropdown with options: All, Needs Attention, Leads, Options, Confirmed                                                                                                            
                                                                                                                                                                                                
  ## Center Panel: Email Thread View                                                                                                                                                            
                                                                                                                                                                                                
  Stack of email messages, each showing:                                                                                                                                                        
  - Avatar + sender name + email + timestamp                                                                                                                                                    
  - If AI sent: purple "🤖 AI Sent" badge                                                                                                                                                       
  - Email body text                                                                                                                                                                             
                                                                                                                                                                                                
  At bottom when draft exists, show AI Draft card:                                                                                                                                              
  ┌────────────────────────────────────────────────┐                                                                                                                                            
  │ 🤖 AI Draft - Waiting for approval  [👍] [👎] │                                                                                                                                             
  ├────────────────────────────────────────────────┤                                                                                                                                            
  │ Dear Sarah,                                    │                                                                                                                                            
  │ Thank you for your inquiry...                  │                                                                                                                                            
  ├────────────────────────────────────────────────┤                                                                                                                                            
  │ [Edit Draft] [Send Now] [Discard]              │                                                                                                                                            
  └────────────────────────────────────────────────┘                                                                                                                                            
  Blue dashed border, blue-50 background. Send Now = primary button, Discard = red ghost.                                                                                                       
                                                                                                                                                                                                
  ## Right Panel: Context Panel                                                                                                                                                                 
                                                                                                                                                                                                
  **Alerts section** (only if alerts exist):                                                                                                                                                    
                                                                                                                                                                                                
  Date Conflict alert (amber card):                                                                                                                                                             
  ⚠️ Date Conflict                                                                                                                                                                              
  Conflicts with "Chen Wedding" (CHF 25,000)                                                                                                                                                    
  [Accept New] [Suggest Alternatives] [Keep Existing]                                                                                                                                           
  View in Calendar →                                                                                                                                                                            
                                                                                                                                                                                                
  Special Request alert (blue card):                                                                                                                                                            
  📋 Special Request                                                                                                                                                                            
  Client requesting live-streaming setup.                                                                                                                                                       
  [Accept] [Decline]                                                                                                                                                                            
                                                                                                                                                                                                
  **Event Details section** (white card):                                                                                                                                                       
  - Status: dropdown (Lead/Option/Confirmed/Cancelled)                                                                                                                                          
  - Date, Time, Client, Company, Attendees, Room                                                                                                                                                
  - Show Offer + Deposit only when offer exists                                                                                                                                                 
  - Show Site Visit only when scheduled                                                                                                                                                         
  - "See Full Event →" link at bottom                                                                                                                                                           
                                                                                                                                                                                                
  **Progress bar**:                                                                                                                                                                             
  ●────●────●────○────○                                                                                                                                                                         
  Date Room Offer Deposit Confirmed                                                                                                                                                             
  Green = completed, gray = pending                                                                                                                                                             
                                                                                                                                                                                                
  **AI Activity section** (collapsible):                                                                                                                                                        
  - Show 3 recent items with icon + title + detail + timestamp                                                                                                                                  
  - "Show more" link to expand                                                                                                                                                                  
  - Icons: 📅 calendar, 📄 offer, 👤 client, 🏢 site visit, 💳 deposit, 📤 email                                                                                                                
                                                                                                                                                                                                
  ## Mobile (<768px)                                                                                                                                                                            
                                                                                                                                                                                                
  Full-screen thread list → tap opens full-screen email view with back button → ℹ️ icon opens context panel as slide-over sheet.                                                                
                                                                                                                                                                                                
  ## Placeholder Content                                                                                                                                                                        
                                                                                                                                                                                                
  Thread 1: Sarah Johnson, TechCorp Inc., "Corporate Conference", Lead, has draft + alerts                                                                                                      
  Thread 2: Michael Chen, "Wedding Reception", Option, starred                                                                                                                                  
  Thread 3: Emma Wilson, "Product Launch", Confirmed                                                                                                                                            
                                                            PROMPT 1: Event Request Inbox Tab                                                                                                                                                             
                                                                                                                                                                                                
  # Build: Event Request Inbox Tab                                                                                                                                                              
                                                                                                                                                                                                
  Add a new tab "Event Requests" to the existing Inbox page with a 3-panel layout.                                                                                                              
                                                                                                                                                                                                
  ## Layout                                                                                                                                                                                     
                                                                                                                                                                                                
  ┌────────────────┬──────────────────────────────┬─────────────────────┐                                                                                                                       
  │ Thread List    │ Email Thread View            │ Context Panel       │                                                                                                                       
  │ (280px fixed)  │ (flex grow)                  │ (380px fixed)       │                                                                                                                       
  └────────────────┴──────────────────────────────┴─────────────────────┘                                                                                                                       
                                                                                                                                                                                                
  ## Left Panel: Thread List                                                                                                                                                                    
                                                                                                                                                                                                
  Each row shows:                                                                                                                                                                               
  - Avatar circle (initials, 40px)                                                                                                                                                              
  - Client name (bold) + timestamp (right, muted)                                                                                                                                               
  - Star icon (yellow when starred)                                                                                                                                                             
  - Subject line (truncated)                                                                                                                                                                    
  - Preview text (muted, truncated)                                                                                                                                                             
  - Status badge: Lead (gray), Option (amber), Confirmed (green), Cancelled (red)                                                                                                               
                                                                                                                                                                                                
  Selected row: blue-50 background with blue left border.                                                                                                                                       
                                                                                                                                                                                                
  Top: Filter dropdown with options: All, Needs Attention, Leads, Options, Confirmed                                                                                                            
                                                                                                                                                                                                
  ## Center Panel: Email Thread View                                                                                                                                                            
                                                                                                                                                                                                
  Stack of email messages, each showing:                                                                                                                                                        
  - Avatar + sender name + email + timestamp                                                                                                                                                    
  - If AI sent: purple "🤖 AI Sent" badge                                                                                                                                                       
  - Email body text                                                                                                                                                                             
                                                                                                                                                                                                
  At bottom when draft exists, show AI Draft card:                                                                                                                                              
  ┌────────────────────────────────────────────────┐                                                                                                                                            
  │ 🤖 AI Draft - Waiting for approval  [👍] [👎] │                                                                                                                                             
  ├────────────────────────────────────────────────┤                                                                                                                                            
  │ Dear Sarah,                                    │                                                                                                                                            
  │ Thank you for your inquiry...                  │                                                                                                                                            
  ├────────────────────────────────────────────────┤                                                                                                                                            
  │ [Edit Draft] [Send Now] [Discard]              │                                                                                                                                            
  └────────────────────────────────────────────────┘                                                                                                                                            
  Blue dashed border, blue-50 background. Send Now = primary button, Discard = red ghost.                                                                                                       
                                                                                                                                                                                                
  ## Right Panel: Context Panel                                                                                                                                                                 
                                                                                                                                                                                                
  **Alerts section** (only if alerts exist):                                                                                                                                                    
                                                                                                                                                                                                
  Date Conflict alert (amber card):                                                                                                                                                             
  ⚠️ Date Conflict                                                                                                                                                                              
  Conflicts with "Chen Wedding" (CHF 25,000)                                                                                                                                                    
  [Accept New] [Suggest Alternatives] [Keep Existing]                                                                                                                                           
  View in Calendar →                                                                                                                                                                            
                                                                                                                                                                                                
  Special Request alert (blue card):                                                                                                                                                            
  📋 Special Request                                                                                                                                                                            
  Client requesting live-streaming setup.                                                                                                                                                       
  [Accept] [Decline]                                                                                                                                                                            
                                                                                                                                                                                                
  **Event Details section** (white card):                                                                                                                                                       
  - Status: dropdown (Lead/Option/Confirmed/Cancelled)                                                                                                                                          
  - Date, Time, Client, Company, Attendees, Room                                                                                                                                                
  - Show Offer + Deposit only when offer exists                                                                                                                                                 
  - Show Site Visit only when scheduled                                                                                                                                                         
  - "See Full Event →" link at bottom                                                                                                                                                           
                                                                                                                                                                                                
  **Progress bar**:                                                                                                                                                                             
  ●────●────●────○────○                                                                                                                                                                         
  Date Room Offer Deposit Confirmed                                                                                                                                                             
  Green = completed, gray = pending                                                                                                                                                             
                                                                                                                                                                                                
  **AI Activity section** (collapsible):                                                                                                                                                        
  - Show 3 recent items with icon + title + detail + timestamp                                                                                                                                  
  - "Show more" link to expand                                                                                                                                                                  
  - Icons: 📅 calendar, 📄 offer, 👤 client, 🏢 site visit, 💳 deposit, 📤 email                                                                                                                
                                                                                                                                                                                                
  ## Mobile (<768px)                                                                                                                                                                            
                                                                                                                                                                                                
  Full-screen thread list → tap opens full-screen email view with back button → ℹ️ icon opens context panel as slide-over sheet.                                                                
                                                                                                                                                                                                
  ## Placeholder Content                                                                                                                                                                        
                                                                                                                                                                                                
  Thread 1: Sarah Johnson, TechCorp Inc., "Corporate Conference", Lead, has draft + alerts                                                                                                      
  Thread 2: Michael Chen, "Wedding Reception", Option, starred                                                                                                                                  
  Thread 3: Emma Wilson, "Product Launch", Confirmed                                                                                                                                            
                                                            PROMPT 1: Event Request Inbox Tab                                                                                                                                                             
                                                                                                                                                                                                
  # Build: Event Request Inbox Tab                                                                                                                                                              
                                                                                                                                                                                                
  Add a new tab "Event Requests" to the existing Inbox page with a 3-panel layout.                                                                                                              
                                                                                                                                                                                                
  ## Layout                                                                                                                                                                                     
                                                                                                                                                                                                
  ┌────────────────┬──────────────────────────────┬─────────────────────┐                                                                                                                       
  │ Thread List    │ Email Thread View            │ Context Panel       │                                                                                                                       
  │ (280px fixed)  │ (flex grow)                  │ (380px fixed)       │                                                                                                                       
  └────────────────┴──────────────────────────────┴─────────────────────┘                                                                                                                       
                                                                                                                                                                                                
  ## Left Panel: Thread List                                                                                                                                                                    
                                                                                                                                                                                                
  Each row shows:                                                                                                                                                                               
  - Avatar circle (initials, 40px)                                                                                                                                                              
  - Client name (bold) + timestamp (right, muted)                                                                                                                                               
  - Star icon (yellow when starred)                                                                                                                                                             
  - Subject line (truncated)                                                                                                                                                                    
  - Preview text (muted, truncated)                                                                                                                                                             
  - Status badge: Lead (gray), Option (amber), Confirmed (green), Cancelled (red)                                                                                                               
                                                                                                                                                                                                
  Selected row: blue-50 background with blue left border.                                                                                                                                       
                                                                                                                                                                                                
  Top: Filter dropdown with options: All, Needs Attention, Leads, Options, Confirmed                                                                                                            
                                                                                                                                                                                                
  ## Center Panel: Email Thread View                                                                                                                                                            
                                                                                                                                                                                                
  Stack of email messages, each showing:                                                                                                                                                        
  - Avatar + sender name + email + timestamp                                                                                                                                                    
  - If AI sent: purple "🤖 AI Sent" badge                                                                                                                                                       
  - Email body text                                                                                                                                                                             
                                                                                                                                                                                                
  At bottom when draft exists, show AI Draft card:                                                                                                                                              
  ┌────────────────────────────────────────────────┐                                                                                                                                            
  │ 🤖 AI Draft - Waiting for approval  [👍] [👎] │                                                                                                                                             
  ├────────────────────────────────────────────────┤                                                                                                                                            
  │ Dear Sarah,                                    │                                                                                                                                            
  │ Thank you for your inquiry...                  │                                                                                                                                            
  ├────────────────────────────────────────────────┤                                                                                                                                            
  │ [Edit Draft] [Send Now] [Discard]              │                                                                                                                                            
  └────────────────────────────────────────────────┘                                                                                                                                            
  Blue dashed border, blue-50 background. Send Now = primary button, Discard = red ghost.                                                                                                       
                                                                                                                                                                                                
  ## Right Panel: Context Panel                                                                                                                                                                 
                                                                                                                                                                                                
  **Alerts section** (only if alerts exist):                                                                                                                                                    
                                                                                                                                                                                                
  Date Conflict alert (amber card):                                                                                                                                                             
  ⚠️ Date Conflict                                                                                                                                                                              
  Conflicts with "Chen Wedding" (CHF 25,000)                                                                                                                                                    
  [Accept New] [Suggest Alternatives] [Keep Existing]                                                                                                                                           
  View in Calendar →                                                                                                                                                                            
                                                                                                                                                                                                
  Special Request alert (blue card):                                                                                                                                                            
  📋 Special Request                                                                                                                                                                            
  Client requesting live-streaming setup.                                                                                                                                                       
  [Accept] [Decline]                                                                                                                                                                            
                                                                                                                                                                                                
  **Event Details section** (white card):                                                                                                                                                       
  - Status: dropdown (Lead/Option/Confirmed/Cancelled)                                                                                                                                          
  - Date, Time, Client, Company, Attendees, Room                                                                                                                                                
  - Show Offer + Deposit only when offer exists                                                                                                                                                 
  - Show Site Visit only when scheduled                                                                                                                                                         
  - "See Full Event →" link at bottom                                                                                                                                                           
                                                                                                                                                                                                
  **Progress bar**:                                                                                                                                                                             
  ●────●────●────○────○                                                                                                                                                                         
  Date Room Offer Deposit Confirmed                                                                                                                                                             
  Green = completed, gray = pending                                                                                                                                                             
                                                                                                                                                                                                
  **AI Activity section** (collapsible):                                                                                                                                                        
  - Show 3 recent items with icon + title + detail + timestamp                                                                                                                                  
  - "Show more" link to expand                                                                                                                                                                  
  - Icons: 📅 calendar, 📄 offer, 👤 client, 🏢 site visit, 💳 deposit, 📤 email                                                                                                                
                                                                                                                                                                                                
  ## Mobile (<768px)                                                                                                                                                                            
                                                                                                                                                                                                
  Full-screen thread list → tap opens full-screen email view with back button → ℹ️ icon opens context panel as slide-over sheet.                                                                
                                                                                                                                                                                                
  ## Placeholder Content                                                                                                                                                                        
                                                                                                                                                                                                
  Thread 1: Sarah Johnson, TechCorp Inc., "Corporate Conference", Lead, has draft + alerts                                                                                                      
  Thread 2: Michael Chen, "Wedding Reception", Option, starred                                                                                                                                  
  Thread 3: Emma Wilson, "Product Launch", Confirmed                                                                                                                                            
                                                          # Event Request Frontend Design Specification

**Version:** 1.2
**Date:** 2026-01-26
**Status:** Design Phase — Approved with Fixes
**Audience:** Frontend Developers, Product Team

**Revision History:**
| Version | Changes |
|---------|---------|
| 1.0 | Initial design spec |
| 1.1 | Incorporated UX Review 1: Mobile adaptation, Suggest Alternatives, Source Grounding, Tone/Signature MVP, Task integration |
| 1.2 | Incorporated UX Review 2: View in Calendar link, Supabase Realtime, Suggest Alternatives loading states, cross-feature navigation map, mandatory infrastructure |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [UX Research Foundation](#2-ux-research-foundation)
3. [Event Request Inbox Design](#3-event-request-inbox-design)
4. [Event Request Setup Page Design](#4-event-request-setup-page-design)
5. [Frontend Interactions & Behaviors](#5-frontend-interactions--behaviors)
6. [API Endpoints Specification](#6-api-endpoints-specification)
7. [Implementation Priority](#7-implementation-priority)

---

## 1. Executive Summary

This document specifies the frontend design for **extensions to two existing pages**:

| Feature | Purpose | Location | Status |
|---------|---------|----------|--------|
| **Event Request Inbox** | View and manage AI-processed event inquiries | Tab within `/inbox` | Tab already started |
| **Event Request Setup** | Configure AI automation behavior | Sections within existing Setup page | Extends existing Setup page |

**Note:** These are NOT new pages built from scratch. The Inbox already has the Event Requests tab started, and the Setup page structure already exists — this spec defines the **content and behavior** to be added.

**Design Principles:**
- Use vocabulary familiar to event managers (lead, option, confirmed, site visit, deposit)
- Show only actionable information to reduce cognitive load
- Justify every AI action to build manager trust
- Match existing OpenEvent design patterns (Shadcn/ui components)

---

## 2. UX Research Foundation

### 2.1 Event Manager Persona

Based on research from [Planning Pod](https://planningpod.com/), [Tripleseat](https://tripleseat.com/), and [Perfect Venue](https://www.perfectvenue.com/):

**Daily Reality:**
- Handles 5-15 active inquiries simultaneously
- Spends 40-50% of time on email communication
- Primary fear: double-booking a room
- Primary need: quick status overview without clicking into details
- Works across devices (desktop primary, mobile for quick checks)

**Mental Model:**
Event managers think in terms of a **pipeline**:
```
Inquiry → Lead → Option (hold) → Confirmed → Completed
```

They do NOT think in terms of "AI steps" or "workflow stages." All terminology must map to their existing mental model.

### 2.2 Key UX Research Findings

#### Finding 1: Activity Feeds Reduce Anxiety About Automation

**Source:** [GetStream Activity Feed Design Guide](https://getstream.io/blog/activity-feed-design/)

> "Activity feeds serve as a centralized location where users can view an organized, real-time list of actions... It notifies users and keeps them updated on changes."

**Application:** Event managers need to see what the AI did to trust it. An activity feed showing AI actions (created offer, updated calendar, added client) provides transparency without requiring them to check each system manually.

#### Finding 2: Relevance Filtering is Critical

**Source:** [UI-Patterns.com Activity Stream](https://ui-patterns.com/patterns/ActivityStream)

> "One of the biggest issues when designing activity streams is figuring out what is relevant to the user. The challenge lies in finding the threshold of relevancy."

**Application:** Not all AI actions are equally important. "Created offer for CHF 15,000" matters more than "parsed email successfully." We must filter to show only business-relevant actions.

#### Finding 3: Immediate Visual Feedback for State Changes

**Source:** [Cieden Toggle Switch Best Practices](https://cieden.com/book/atoms/toggle-switch/toggle-switch-ux-best-practices)

> "Toggles are ideal for settings that take effect immediately without requiring further user confirmation."

**Application:** Settings like "Enable Site Visits" should take effect immediately when toggled, with visual confirmation.

#### Finding 4: Settings Need Contextual Descriptions

**Source:** [Toptal Settings UX Guide](https://www.toptal.com/designers/ux/settings-ux)

> "Jargon leads users to look for context outside of settings panels. Settings are best described in plain language that indicates functionality."

**Application:** Every setting needs a one-line description in plain language. Avoid technical terms like "workflow," "LLM," or "automation pipeline."

#### Finding 5: Group Settings by Mental Model

**Source:** [SetProduct Settings UI Design](https://www.setproduct.com/blog/settings-ui-design)

> "When apps have multiple settings, group them into categories... Bring frequently used settings to the forefront."

**Application:** Group settings by what they affect (site visits, notifications) not by technical function.

#### Finding 6: AI Needs Human Oversight Points

**Source:** [Microsoft Dynamics 365 AI Agent Activity Feed](https://www.microsoft.com/en-us/dynamics-365/blog/it-professional/2025/10/08/try-the-ai-agent-activity-feed-in-dynamics-365-customer-service/)

> "Inbox-style UX for AI supervisors to view each action an agent performs in a streamlined interface."

**Application:** The Event Request Inbox serves as a "supervisor view" where managers can see AI decisions and intervene when needed.

---

## 3. Event Request Inbox Design

### 3.1 Page Location & Access

**Route:** `/inbox` with tab "Event Requests"

**Navigation:**
```
Inbox (main)
├── [Tab] All Mail        ← existing
├── [Tab] Event Requests  ← NEW
└── [Tab] Sent            ← existing (if applicable)
```

**Justification:** Event managers already check their inbox frequently ([Planning Pod](https://planningpod.com/) reports 40-50% of time on email). Placing Event Requests as a tab within Inbox matches their existing workflow—they don't need to learn a new location.

**Relationship with Tasks (`/tasks`):**
Items in the Event Request Inbox are specialized, AI-managed workflows. They do **not** appear in the general `/tasks` Kanban board to avoid duplication. However, if a manager clicks "Flag for Follow-up" on a thread, it creates a linked Task entity visible in `/tasks` with category "Event Tasks".

### 3.2 Page Layout Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  [Delete] [Archive] [Flag] [Select]     Event Requests     [Search] [New]   │
├────────────────┬─────────────────────────────────┬──────────────────────────┤
│                │                                 │                          │
│  Thread List   │      Email Thread View          │    Context Panel         │
│  (Left)        │      (Center)                   │    (Right)               │
│                │                                 │                          │
│  - Sarah J.    │   From: sarah@techcorp.com      │  ┌─────────────────────┐ │
│  - Michael C.  │   Subject: Corporate Conf...    │  │ Alerts Panel        │ │
│  - Emma W.     │                                 │  │ (conditional)       │ │
│                │   [Email content...]            │  └─────────────────────┘ │
│                │                                 │                          │
│                │                                 │  ┌─────────────────────┐ │
│                │                                 │  │ Event Details       │ │
│                │                                 │  │ Panel               │ │
│                │                                 │  └─────────────────────┘ │
│                │                                 │                          │
│                │                                 │  ┌─────────────────────┐ │
│                │                                 │  │ AI Activity         │ │
│                │                                 │  │ Panel               │ │
│                │                                 │  └─────────────────────┘ │
│                │                                 │                          │
├────────────────┴─────────────────────────────────┴──────────────────────────┤
│  [Status bar / pagination]                                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Width Ratios:** 20% / 45% / 35% (adjustable, follows existing Inbox pattern)

#### 3.2.1 Mobile Adaptation (<768px)

On mobile devices, the 3-panel layout transforms into a **drill-down navigation**:

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│ Event Requests      │     │ ← Sarah Johnson     │     │ ← Back    [ℹ Info]  │
├─────────────────────┤     ├─────────────────────┤     ├─────────────────────┤
│                     │     │                     │     │                     │
│ Sarah Johnson  12:50│ tap │ Email thread        │ tap │ ┌─────────────────┐ │
│ Corporate Conf...   │ ──→ │ content here...     │ [ℹ] │ │ Slide-over Sheet│ │
│ [Lead]              │     │                     │ ──→ │ │                 │ │
│                     │     │ ┌─────────────────┐ │     │ │ • Alerts        │ │
│ Michael Chen   Yest │     │ │ AI Draft        │ │     │ │ • Event Details │ │
│ Wedding Recept...   │     │ │ [Edit] [Send]   │ │     │ │ • AI Activity   │ │
│ [Option]            │     │ └─────────────────┘ │     │ │                 │ │
│                     │     │                     │     │ └─────────────────┘ │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘
     List View                   Thread View              Context Sheet
```

**Mobile Navigation Flow:**
1. **List View:** Shows only the Thread List (full screen)
2. **Thread View:** Tapping a thread opens email conversation (full screen with back arrow)
3. **Context Sheet:** Tapping [ℹ Info] icon in header opens a slide-over sheet containing Alerts, Event Details, and AI Activity panels

**Touch Targets:** All interactive elements minimum 44px height for accessibility.

### 3.3 Thread List (Left Panel)

**What it shows:** All email threads that the AI has identified as event requests.

**Each list item displays:**
```
┌─────────────────────────────────┐
│ [Avatar] Sarah Johnson    12:50 │
│ ★        Corporate Conf - 150   │
│          Hi, We are planning... │
│ [Status Badge: Lead]            │
└─────────────────────────────────┘
```

| Element | Source | Display Logic |
|---------|--------|---------------|
| Avatar | Client initials or photo | Always visible |
| Client Name | `event_entry.client_name` or email sender | Always visible |
| Timestamp | Email received time | Always visible |
| Star indicator | User-starred | Only if starred |
| Subject line | Email subject (truncated) | Always visible |
| Preview text | First line of email body | Always visible |
| Status Badge | `event_entry.status` | Always visible |

**Status Badge Colors:**
| Status | Color | Reasoning |
|--------|-------|-----------|
| Lead | Gray | Neutral, new inquiry |
| Option | Yellow/Amber | Needs attention, pending |
| Confirmed | Green | Positive, completed |
| Cancelled | Red | Negative, closed |

**Sorting:** By most recent email activity (newest first)

**Filtering options (top of list):**
- All
- Needs Attention (has unresolved alerts)
- Leads only
- Options only
- Confirmed only

**Justification:** [Aubergine Activity Feed Guide](https://www.aubergine.co/insights/a-guide-to-designing-chronological-activity-feeds) recommends chronological sorting for activity-based lists. Status badges provide at-a-glance pipeline view matching how event managers think ([Tripleseat](https://tripleseat.com/)).

### 3.4 Email Thread View (Center Panel)

**What it shows:** The full email conversation for the selected thread.

**Layout:** Standard email thread view (already exists in OpenEvent Inbox).

**Additions for Event Requests:**

1. **AI Draft Indicator** (when applicable)
```
┌─────────────────────────────────────────────────────────────────┐
│ 🤖 AI Draft - Waiting for your approval         [👍] [👎]      │
│ ─────────────────────────────────────────────────────────────── │
│                                                                 │
│ Dear Sarah,                                                     │
│                                                                 │
│ Thank you for your inquiry. I'm pleased to confirm that our    │
│ Main Hall is available on March 15th, 2026...                  │
│                                                                 │
│ ─────────────────────────────────────────────────────────────── │
│ [Edit Draft]  [Send Now]  [Discard]                            │
└─────────────────────────────────────────────────────────────────┘
```

**Visibility:** Only shown when `thread_state.pending_draft` exists.

**Feedback Loop (SOTA Requirement):**
- **👍 Thumbs Up:** "This draft is good" — logs positive feedback for model improvement
- **👎 Thumbs Down:** "This draft needs work" — logs negative feedback before editing

Feedback is captured **before** the manager takes action (Edit/Send/Discard). This explicitly captures AI quality separately from the edit itself, enabling targeted model training for this specific venue's style.

**Justification:** [Microsoft Dynamics 365](https://www.microsoft.com/en-us/dynamics-365/blog/it-professional/2025/10/08/try-the-ai-agent-activity-feed-in-dynamics-365-customer-service/) shows that inline approval within the conversation context is faster than switching to a separate Tasks page. Feedback loops are standard SOTA for enterprise AI (Copilot, ChatGPT Enterprise).

2. **Sent by AI Indicator** (on sent messages)
```
┌─────────────────────────────────────────────────────────────────┐
│ From: events@yourvenue.com           Mon 10:30 AM    🤖 AI Sent │
└─────────────────────────────────────────────────────────────────┘
```

Small robot icon + "AI Sent" label on messages the AI sent automatically.

**Justification:** Transparency about what was automated builds trust ([Eventify AI Guide](https://eventify.io/blog/ai-in-event-management)).

### 3.5 Context Panel (Right Panel)

The right panel contains three stacked sub-panels. Their visibility depends on the state of the selected thread.

#### 3.5.1 Alerts Panel

**Position:** Top of right panel
**Visibility:** Only shown when there are active alerts for this thread

**Alert Types:**

**A) Date Conflict Alert**
```
┌─────────────────────────────────────────┐
│ ⚠️  Date Conflict                       │
│                                         │
│ Conflicts with Chen Wedding             │
│ Planning (CHF 25,000)                   │
│                                         │
│ [Accept New] [Suggest Alternatives] [Keep Existing]
└─────────────────────────────────────────┘
```

**When shown:** When `event_entry.has_date_conflict == true`

**Data displayed:**
- Conflict type (room overlap, date overlap)
- Name of conflicting event
- Value of conflicting event (helps prioritization)

**Actions:**
- "Accept New" → Proceeds with new request, marks conflict as resolved, existing event needs rebooking
- "Suggest Alternatives" → AI finds available dates/times near the requested date and drafts a response offering alternatives to the client (maximizes venue utilization by pivoting conflicts into sales)
- "Keep Existing" → Rejects new date, notifies manager to respond manually
- **"View in Calendar"** → Opens Calendar page filtered to conflict date range (new tab) for visual verification

**"Suggest Alternatives" UX States:**
Since this is a complex backend operation, the UI must handle:
| State | UI Treatment |
|-------|--------------|
| Loading | Button shows spinner, text changes to "Finding alternatives..." |
| Success | Shows list of 2-3 alternative dates/times with "Use This" buttons |
| No Alternatives | Message: "No available slots within 2 weeks. Consider manual outreach." |
| Error | Toast notification, button returns to default state |

**Justification:** Date conflicts are the #1 fear of event managers ([Planning Pod](https://planningpod.com/)). The "Suggest Alternatives" action follows patterns from modern scheduling tools (Calendly, Motion) and competitors like [Tripleseat](https://tripleseat.com/) that maximize venue utilization. Showing the monetary value of the conflict helps prioritization—standard practice in venue management software ([EventPro](https://www.eventpro.net/)). The "View in Calendar" link addresses the UX Review finding that managers trust their eyes—visual verification increases confidence before making decisions.

**B) Special Request Alert**
```
┌─────────────────────────────────────────┐
│ 📋  Special Request                     │
│                                         │
│ The client is requesting professional   │
│ live-streaming setup with cameras for   │
│ remote attendees.                       │
│                                         │
│ [Accept]              [Decline]         │
└─────────────────────────────────────────┘
```

**When shown:** When `event_entry.special_requests[]` contains items with `requires_review == true`

**Data displayed:**
- Summary of the special request (AI-generated plain language)

**Actions:**
- "Accept" → Request is marked as accommodated, added to event requirements
- "Decline" → AI will respond that this cannot be accommodated

**Justification:** Special requests often require human judgment (can we actually provide this? at what cost?). Surfacing them prominently prevents them from being buried in email text ([Tripleseat](https://tripleseat.com/) uses similar "request flags").

**When Alerts Panel is Hidden:**
- When no alerts exist, this panel is completely hidden (not shown as empty)
- The Event Details panel moves up to take its place

#### 3.5.2 Event Details Panel

**Position:** Below Alerts (or top if no alerts)
**Visibility:** Always shown when a thread is selected

```
┌─────────────────────────────────────────┐
│ EVENT DETAILS                           │
├─────────────────────────────────────────┤
│ Status        [Lead ▾]                  │
│ Date          March 15, 2026            │
│ Time          09:00 - 17:00             │
│ Client        Sarah Johnson             │
│               TechCorp Inc.             │
│ Attendees     150                       │
│ Room          Main Hall                 │
│ Offer         CHF 18,000                │
│ Deposit       Not Paid                  │
│ Site Visit    March 1, 2026 14:00       │
├─────────────────────────────────────────┤
│ [See Full Event →]                      │
└─────────────────────────────────────────┘
```

**Field Display Logic:**

Based on [Progressive Disclosure UX patterns](https://blog.logrocket.com/ux-design/progressive-disclosure-ux-types-use-cases/) and [NN/G Empty State guidelines](https://www.nngroup.com/articles/empty-state-interface-design/), fields are divided into two categories:

**Category 1: Core Fields (Always Visible)**
These define what an event IS. Show with "—" placeholder when empty.

| Field | Source | Empty Display |
|-------|--------|---------------|
| Status | `event_entry.status` | Always has value (default: Lead) |
| Date | `event_entry.chosen_date` | "—" |
| Time | `event_entry.start_time` / `end_time` | "—" |
| Client | `event_entry.client_name` | Always has value (from email) |
| Company | `clients.company` | "—" |
| Attendees | `events.attendees` | "—" |
| Room | `rooms.name` via `room_ids` | "—" |

**Category 2: Stage-Dependent Fields (Progressive Disclosure)**
These only appear when their prerequisite exists. Hiding them avoids confusion ("Should there be an offer?").

| Field | Show When | Source | Display |
|-------|-----------|--------|---------|
| Offer | Offer record exists | `offers.total_amount` | "CHF 18,000" |
| Deposit | Offer record exists | `offers.deposit_paid_at` | "Paid" / "Not Paid" |
| Site Visit | Site visit scheduled | `site_visits` | "March 1, 2026 14:00" |

**Why this approach:**
- [UXPin](https://www.uxpin.com/studio/blog/what-is-progressive-disclosure/) notes: "Progressive disclosure reduces cognitive load by gradually revealing more complex information as the user progresses."
- Showing "Offer: —" before any pricing discussion creates confusion about system state
- Once an offer exists, Deposit status becomes relevant and both should always be visible

#### Source Grounding & Confidence Indicators (AI Transparency)

Based on SOTA AI interfaces (Microsoft Copilot for Sales), AI-extracted fields need **source grounding** to build trust.

**Visual Treatment for AI-Extracted Fields:**
```
┌─────────────────────────────────────────┐
│ Attendees     150 ···                   │  ← Dotted underline indicates AI-extracted
│               ⓘ "expecting around 150"  │  ← Tooltip shows source text on hover
└─────────────────────────────────────────┘
```

**Confidence Indicators:**
| Confidence | Visual | Behavior |
|------------|--------|----------|
| High (≥80%) | Normal text, dotted underline | Tooltip shows source on hover |
| Low (<80%) | Yellow background + ⚠️ icon | Tooltip: "Low confidence - please verify" |

**Example Low Confidence:**
```
┌─────────────────────────────────────────┐
│ Date          ⚠️ 01/02/2026             │  ← Ambiguous format (Jan 2 or Feb 1?)
│               "Could be January 2nd or  │
│                February 1st - please    │
│                verify with client"      │
└─────────────────────────────────────────┘
```

**Fields That Show Source Grounding:**
- Date (extracted from email)
- Time (extracted from email)
- Attendees (extracted from email)
- Room (if AI-suggested based on requirements)

**Fields That Do NOT Show Source Grounding:**
- Status (system-managed)
- Client name (from email header, always accurate)
- Offer amount (calculated, not extracted)

**Justification:** Source grounding follows Microsoft Copilot patterns for enterprise AI. When managers can see WHERE a value came from, they trust the AI more and catch errors faster.

**Status Dropdown:** Manager can manually change status directly from this panel.

**"See Full Event" Link:** Opens `/events/:id` in new tab or modal.

**Visual Example - Early Stage (Lead):**
```
┌─────────────────────────────────────────┐
│ EVENT DETAILS                           │
├─────────────────────────────────────────┤
│ Status        [Lead ▾]                  │
│ Date          —                         │
│ Time          —                         │
│ Client        Sarah Johnson             │
│ Company       TechCorp Inc.             │
│ Attendees     150                       │
│ Room          —                         │
├─────────────────────────────────────────┤
│ [See Full Event →]                      │
└─────────────────────────────────────────┘
```

**Visual Example - Later Stage (Option with Offer):**
```
┌─────────────────────────────────────────┐
│ EVENT DETAILS                           │
├─────────────────────────────────────────┤
│ Status        [Option ▾]                │
│ Date          March 15, 2026            │
│ Time          09:00 - 17:00             │
│ Client        Sarah Johnson             │
│ Company       TechCorp Inc.             │
│ Attendees     150                       │
│ Room          Main Hall                 │
│ Offer         CHF 18,000                │
│ Deposit       Not Paid                  │
│ Site Visit    March 1, 2026 14:00       │
├─────────────────────────────────────────┤
│ [See Full Event →]                      │
└─────────────────────────────────────────┘
```

**Justification:** This is the "at-a-glance" view event managers need ([Momentus](https://gomomentus.com/)). They should be able to assess an event's completeness without opening the full event page.

#### 3.5.3 AI Activity Panel

**Position:** Bottom of right panel
**Visibility:** Always shown (may be collapsed by default)

**Header:**
```
┌─────────────────────────────────────────┐
│ AI ACTIVITY                    [Filter] │
├─────────────────────────────────────────┤
```

**Activity Item Structure:**
```
│ 📅  Updated calendar                    │
│     March 15 → March 18, 2026           │
│     2 hours ago                         │
│ ─────────────────────────────────────── │
│ 📄  Created offer                       │
│     CHF 18,000 for Main Hall            │
│     Yesterday                           │
│ ─────────────────────────────────────── │
│ 👤  Added client to CRM                 │
│     Sarah Johnson (TechCorp Inc.)       │
│     2 days ago                          │
└─────────────────────────────────────────┘
```

**Activity Types to Display:**

| Category | Icon | Action Text | Detail Text |
|----------|------|-------------|-------------|
| Calendar | 📅 | "Updated calendar" | What changed (date, time, room) |
| Calendar | 📅 | "Created event" | Event title + date |
| Offer | 📄 | "Created offer" | Amount + room |
| Offer | 📝 | "Updated offer" | What changed |
| Offer | ✅ | "Offer confirmed" | Client accepted |
| CRM | 👤 | "Added client" | Name + company |
| CRM | ✏️ | "Updated client" | What changed (billing address, etc.) |
| Site Visit | 🏢 | "Scheduled site visit" | Date + time |
| Site Visit | ✅ | "Site visit completed" | — |
| Deposit | 💳 | "Deposit received" | Amount |
| Email | 📤 | "Sent response" | Subject line snippet |

**Activities NOT Shown (internal/technical):**

| Hidden Activity | Reason |
|-----------------|--------|
| "Checked availability" | Internal operation, no user impact |
| "Parsed requirements" | Technical, not meaningful to manager |
| "Workflow step changed" | Internal state, use status badge instead |
| "Cache updated" | Technical infrastructure |

**Activity Grouping:**
Related actions should be grouped to prevent noise. Instead of showing 5 separate log lines:
```
❌ Bad: "Parsed email" → "Detected date" → "Checked room" → "Created draft" → "Waiting approval"
✅ Good: "AI handled inquiry - draft ready for review"
```

**Reasoning Tooltips (AI Explainability):**
For high-stakes activities, hovering shows WHY the AI took that action:

```
┌─────────────────────────────────────────┐
│ 📄  Created offer              [?]      │  ← Hover [?] for reasoning
│     CHF 18,000 for Main Hall            │
│     Yesterday                           │
│ ┌─────────────────────────────────────┐ │
│ │ "Based on 'budget around 15k' in    │ │  ← Tooltip on hover
│ │  email + Main Hall standard rate"   │ │
│ └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

**User Actions in Activity Log:**
When a manager edits an AI draft, log it distinctly:
- "Draft edited by Sarah" (distinguishes manager corrections from AI errors)
- "Date conflict resolved by Sarah - kept existing"

This creates an audit trail showing human oversight.

**Filter Dropdown Options:**
- All Activity
- Calendar Changes
- Offers
- CRM Updates
- Emails Sent

**Collapsed State:**
By default, show only the 3 most recent activities with "Show more" link.

**Justification:** [GetStream](https://getstream.io/blog/activity-feed-design/) emphasizes that activity feeds must balance completeness with scannability. Showing only business-relevant actions (not internal operations) follows the "relevance threshold" principle from [UI-Patterns](https://ui-patterns.com/patterns/ActivityStream). Activity grouping and reasoning tooltips follow Microsoft Copilot patterns for enterprise AI transparency.

### 3.6 Progress Indicator

**Position:** Below Event Details panel OR integrated as visual element within Event Details

**Alternative Design (Horizontal Progress Bar):**
```
┌─────────────────────────────────────────┐
│ EVENT PROGRESS                          │
│                                         │
│ ●────●────●────○────○                   │
│ Date  Room  Offer  Deposit  Confirmed   │
│                                         │
└─────────────────────────────────────────┘
```

**States:**
- ● Filled circle = Completed
- ○ Empty circle = Not yet completed
- Current step slightly larger or highlighted

**Steps:**
1. Date confirmed
2. Room assigned
3. Offer sent
4. Deposit received
5. Event confirmed

**Justification:** Progress indicators are standard in sales pipelines ([Tripleseat](https://tripleseat.com/), [Perfect Venue](https://www.perfectvenue.com/)). This maps to the event manager's mental model of moving inquiries through stages.

### 3.7 Empty States

**When no threads exist:**
```
┌─────────────────────────────────────────┐
│                                         │
│         📬                              │
│                                         │
│    No event requests yet                │
│                                         │
│    When clients send booking            │
│    inquiries, they'll appear here.      │
│                                         │
└─────────────────────────────────────────┘
```

**When no thread is selected:**
Center panel shows: "Select a conversation to view details"

---

## 4. Event Request Setup Page Design

### 4.1 Page Location & Access

**Route:** `/setup/event-requests` (or section within existing Setup page)

**Note:** The Setup page structure already exists. This spec defines **new sections** to be added for Event Request configuration.

**Navigation:**
```
SETUP (collapsible section in sidebar)
├── Venue
├── Rooms
├── Products
├── Offers
├── Templates
└── Event Requests  ← NEW SECTION
```

**Justification:** Settings related to feature behavior belong under Setup (alongside Rooms, Products, Offers). User preferences (theme, language) belong under Settings. This follows the separation pattern already established in OpenEvent.

### 4.2 Page Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Event Request Settings                                                      │
│  Configure how AI handles incoming event inquiries                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─ Section 1: Automation Mode ─────────────────────────────────────────┐  │
│  │                                                                       │  │
│  │  ...settings...                                                       │  │
│  │                                                                       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌─ Section 2: Site Visits ─────────────────────────────────────────────┐  │
│  │                                                                       │  │
│  │  ...settings...                                                       │  │
│  │                                                                       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ... more sections ...                                                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Page Header:**
- Title: "Event Request Settings"
- Subtitle: "Configure how AI handles incoming event inquiries"

**Section Styling:** Use Card component with section title as header (matches existing Setup pages like Offers Setup).

### 4.3 Section 1: Automation Mode (MVP)

**Section Title:** "Automation Mode"
**Section Description:** "Control how much the AI handles automatically"

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Automation Mode                                                            │
│  Control how much the AI handles automatically                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ○  Review all replies                                                      │
│     AI drafts responses, you review and send each one manually.             │
│     Best for: High-value clients, complex negotiations                      │
│                                                                             │
│  ●  Semi-automatic (Recommended)                                            │
│     AI sends routine replies automatically. Asks your approval for          │
│     offers, confirmations, and anything unusual.                            │
│     Best for: Most venues                                                   │
│                                                                             │
│  ○  Full automatic                                                          │
│     AI handles the complete booking flow. You get notified when             │
│     bookings are confirmed or issues need attention.                        │
│     Best for: High-volume, standardized events                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Component:** Radio button group (single selection)

**Options:**

| Value | Label | Description | When to Use |
|-------|-------|-------------|-------------|
| `review_all` | Review all replies | AI drafts responses, you review and send each one manually. | High-value clients, complex negotiations |
| `semi_auto` | Semi-automatic (Recommended) | AI sends routine replies automatically. Asks your approval for offers, confirmations, and anything unusual. | Most venues |
| `full_auto` | Full automatic | AI handles the complete booking flow. You get notified when bookings are confirmed or issues need attention. | High-volume, standardized events |

**Default Value:** `semi_auto`

**Backend Mapping:** `team_settings.automation_level`

**Justification:** [Glue Up AI Guide](https://www.glueup.com/blog/ai-powered-event-planning-software) emphasizes that AI should have "human oversight points." Offering three levels lets venues choose their comfort level. The "Recommended" label guides new users while giving experienced users flexibility. "Best for" hints help managers self-select appropriately.

### 4.4 Section 2: Site Visits (MVP)

**Section Title:** "Site Visits"
**Section Description:** "Offer venue tours to potential clients"

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Site Visits                                                                │
│  Offer venue tours to potential clients                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Enable Site Visits                                              [Toggle]   │
│  Allow clients to schedule a venue tour before booking                      │
│                                                                             │
│  ─────────────────────────────────────────────────────────────────────────  │
│  (Settings below only shown when toggle is ON)                              │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  Default Timing                                                             │
│  How many days before the event should site visits be offered?              │
│  [Dropdown: 7 days / 10 days / 14 days / 21 days / 30 days]                │
│                                                                             │
│  Available Days                                                             │
│  When can site visits be scheduled?                                         │
│  [✓] Weekday mornings (9:00 - 12:00)                                       │
│  [✓] Weekday afternoons (13:00 - 17:00)                                    │
│  [ ] Saturdays                                                              │
│  [ ] Sundays                                                                │
│                                                                             │
│  Minimum Event Size                                                         │
│  Only offer site visits for events with at least this many attendees        │
│  [Number input: 50] attendees                                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Components:**

| Setting | Component | Default | Backend Mapping |
|---------|-----------|---------|-----------------|
| Enable Site Visits | Toggle | OFF | `team_settings.site_visits_enabled` |
| Default Timing | Dropdown | 14 days | `team_settings.site_visit_days_before` |
| Available Days | Checkbox group | Weekday mornings + afternoons | `team_settings.site_visit_availability[]` |
| Minimum Event Size | Number input | 50 | `team_settings.site_visit_min_attendees` |

**Conditional Display:** The timing, availability, and minimum size settings only appear when the toggle is ON.

**Justification:** Site visits are a key differentiator in venue sales ([Perfect Venue](https://www.perfectvenue.com/)). Not all venues offer them, so it's a toggle. The "minimum attendees" filter prevents unnecessary site visits for small events—this is common practice to optimize sales team time.

### 4.5 Section 3: Notifications (MVP - Optional)

**Section Title:** "Notifications"
**Section Description:** "Choose what you want to be alerted about"

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Notifications                                                              │
│  Choose what you want to be alerted about                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Date Conflicts                                                  [Toggle]   │
│  Alert when a requested date overlaps with an existing event                │
│                                                                             │
│  Special Requests                                                [Toggle]   │
│  Alert when a client has requirements that need your review                 │
│                                                                             │
│  New Inquiries                                                   [Toggle]   │
│  Alert for every new event request received                                 │
│                                                                             │
│  Event Confirmations                                             [Toggle]   │
│  Alert when an event is fully confirmed                                     │
│                                                                             │
│  Deposit Received                                                [Toggle]   │
│  Alert when a client pays their deposit                                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Default Values:**

| Setting | Default | Reasoning |
|---------|---------|-----------|
| Date Conflicts | ON | Critical—must not be missed |
| Special Requests | ON | Requires human judgment |
| New Inquiries | OFF | Could be noisy for high-volume venues |
| Event Confirmations | OFF | Nice to know, not urgent |
| Deposit Received | OFF | Nice to know, not urgent |

**Backend Mapping:** `team_settings.notifications.{type}: boolean`

**Justification:** [SuprSend Activity Feed Guide](https://www.suprsend.com/post/activity-feed) emphasizes that "notification preferences enable users to opt out of specific notification categories... reducing the risk of users disabling all notifications." By defaulting critical alerts ON and nice-to-have alerts OFF, we balance awareness with noise reduction.

### 4.6 Section 4: Offer Behavior (NOT MVP - Later)

**Section Title:** "Offer Settings"
**Section Description:** "Configure automatic offer generation"

**Status Banner:**
```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ℹ️  Coming Soon                                                            │
│  These settings will be available in a future update.                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Offer Settings                                                             │
│  Configure automatic offer generation                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│  ℹ️  Coming Soon - These settings will be available in a future update.    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Auto-generate Offers                                    [Toggle - disabled]│
│  Automatically create offers when room and date are confirmed               │
│                                                                             │
│  Include Deposit Terms                                   [Toggle - disabled]│
│  Always include deposit requirements in generated offers                    │
│                                                                             │
│  Default Validity                                                           │
│  How long should offers be valid?                                           │
│  [Dropdown - disabled: 7 days / 14 days / 30 days]                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Implementation Note:** Render this section with all controls disabled (grayed out) and the "Coming Soon" banner. This shows users what's planned without cluttering the interface.

**Why This Exists (for future reference):**
These settings control how the AI generates offers:
- Auto-generate: Should offers be created automatically when date + room are confirmed?
- Include Deposit: Should deposit terms always be included? (Some venues only require deposits for large events)
- Validity: Default number of days before offer expires

**Justification:** Offer generation has financial implications. While the AI can generate offers, the settings for HOW offers are structured should be configurable. This is deferred to post-MVP because the current workflow already has sensible defaults.

### 4.7 Section 5: Response Style (PARTIAL MVP)

**Section Title:** "Response Style"
**Section Description:** "Customize how AI communicates with clients"

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Response Style                                                             │
│  Customize how AI communicates with clients                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Tone                                                          [MVP]        │
│  Choose the communication style for AI responses                            │
│  [Toggle: Formal ←─────○─────→ Friendly]                                   │
│                                                                             │
│  Email Signature                                               [MVP]        │
│  Which signature should AI use?                                             │
│  [Dropdown: Team signature / Personal signature / None]                    │
│  Preview: "Best regards, The [Venue Name] Team"                             │
│                                                                             │
│  ─────────────────────────────────────────────────────────────────────────  │
│  ℹ️  Coming Soon - More settings in a future update                        │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  Language                                                                   │
│  Which language should AI use for responses?                                │
│  [Dropdown - disabled: Match client / German / English / French]           │
│                                                                             │
│  Custom Instructions                                                        │
│  Additional instructions for the AI when writing responses                  │
│  [Textarea - disabled]                                                      │
│  Example: "Always mention our award-winning catering service"               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**MVP Settings (Essential for Day 1):**

| Setting | Component | Default | Backend Mapping |
|---------|-----------|---------|-----------------|
| Tone | Toggle (binary) | Formal | `team_settings.response_tone` |
| Email Signature | Dropdown | Team signature | `team_settings.email_signature_type` |

**Tone Toggle:** Simple binary choice (Formal/Friendly) for MVP. More nuanced options (match client's tone) in future.

**Email Signature Options:**
- **Team signature:** Uses venue-level signature (e.g., "Best regards, The [Venue Name] Team")
- **Personal signature:** Uses assigned manager's signature (requires signature setup in Profile)
- **None:** No signature appended

**Coming Soon Settings (Deferred):**
- Language: Multi-lingual support for Swiss/international markets
- Custom Instructions: Venue-specific messaging (unique selling points)

**Justification:** [Glue Up](https://www.glueup.com/blog/ai-powered-event-planning-software) notes that AI should be able to "adapt to your brand voice." **Critical for MVP:** UX Review identified that managers will not trust AI-generated emails that don't sound like them or lack their signature. A robotic tone or unsigned email destroys first impressions. The simple Formal/Friendly toggle and signature selection address 90% of personalization needs with minimal complexity.

---

## 5. Frontend Interactions & Behaviors

This section defines all interactive behaviors, visibility logic, and state management for implementation.

### 5.1 Event Request Inbox — Interactions

#### 5.1.1 Thread List Interactions

| Element | Trigger | Behavior | API Call |
|---------|---------|----------|----------|
| Thread item | Click | Select thread, load details in center + right panels | `GET /api/event-requests/:threadId` |
| Thread item | Hover | Subtle highlight (background color change) | None |
| Star icon | Click | Toggle starred state | `PATCH /api/event-requests/:threadId` `{starred: true/false}` |
| Status badge | — | Read-only display | None |
| Filter dropdown | Change | Filter thread list, persist selection | Client-side filter OR `GET /api/event-requests?status=lead` |
| Search input | Input (debounced 300ms) | Filter threads by client name, subject, company | `GET /api/event-requests?q=searchterm` |

**Visibility Logic:**
| Condition | Show/Hide |
|-----------|-----------|
| No threads exist | Hide Thread List, show Empty State |
| Threads loading | Show skeleton loader (3-5 placeholder items) |
| Filter returns no results | Show "No matching requests" message in list area |

#### 5.1.2 Email Thread View Interactions

| Element | Trigger | Behavior | API Call |
|---------|---------|----------|----------|
| Email message | — | Read-only display | Loaded with thread |
| Reply button | Click | Open compose area (existing Inbox behavior) | None |
| AI Draft "Edit Draft" | Click | Open draft in editable compose mode | None (client-side) |
| AI Draft "Send Now" | Click | Show confirmation dialog, then send | `POST /api/event-requests/:threadId/approve` |
| AI Draft "Discard" | Click | Show confirmation dialog, then discard | `POST /api/event-requests/:threadId/reject` `{action: 'discard'}` |
| "🤖 AI Sent" indicator | Hover | Tooltip: "This response was sent automatically by AI" | None |

**Visibility Logic:**
| Condition | Show/Hide |
|-----------|-----------|
| No thread selected | Show placeholder: "Select a conversation to view details" |
| Thread loading | Show skeleton loader |
| `thread_state.pending_draft` exists | Show AI Draft panel at bottom of thread |
| `thread_state.pending_draft` is null | Hide AI Draft panel |
| Email has `sent_by_ai: true` | Show "🤖 AI Sent" indicator on that message |

**Confirmation Dialogs:**
| Action | Dialog Title | Dialog Message | Confirm Button | Cancel Button |
|--------|--------------|----------------|----------------|---------------|
| Send AI Draft | "Send Response?" | "This will send the AI-generated response to {client_name}." | "Send" (primary) | "Cancel" |
| Discard AI Draft | "Discard Draft?" | "The AI draft will be deleted. You can write your own response instead." | "Discard" (destructive) | "Keep Draft" |

#### 5.1.3 Alerts Panel Interactions

| Element | Trigger | Behavior | API Call |
|---------|---------|----------|----------|
| Date Conflict "Accept New" | Click | Resolve conflict in favor of new request | `POST /api/event-requests/:threadId/resolve-conflict` `{resolution: 'accept_new'}` |
| Date Conflict "Keep Existing" | Click | Reject new date, AI will suggest alternatives | `POST /api/event-requests/:threadId/resolve-conflict` `{resolution: 'keep_existing'}` |
| Special Request "Accept" | Click | Mark request as accommodated | `POST /api/event-requests/:threadId/special-request/:requestId` `{accepted: true}` |
| Special Request "Decline" | Click | Mark request as declined | `POST /api/event-requests/:threadId/special-request/:requestId` `{accepted: false}` |
| Alert panel | — | Auto-dismiss animation after action | Client-side |

**Visibility Logic:**
| Condition | Show/Hide |
|-----------|-----------|
| `alerts.length === 0` | Hide entire Alerts Panel |
| `alerts.length > 0` | Show Alerts Panel at top of right sidebar |
| Alert resolved | Animate out (fade + slide), remove from list |
| Multiple alerts | Stack vertically, most recent first |

#### 5.1.4 Event Details Panel Interactions

| Element | Trigger | Behavior | API Call |
|---------|---------|----------|----------|
| Status dropdown | Change | Update event status | `PATCH /api/events/:eventId` `{status: 'option'}` |
| "See Full Event →" link | Click | Navigate to `/events/:eventId` | None (navigation) |
| Field values | — | Read-only display | None |

**Visibility Logic (Progressive Disclosure):**
| Condition | Show/Hide Fields |
|-----------|------------------|
| Always | Status, Date, Time, Client, Company, Attendees, Room |
| `offers` record exists for this event | + Offer, Deposit |
| `site_visits` record exists for this event | + Site Visit |
| Field value is null/empty | Show "—" for core fields, hide stage-dependent fields |

#### 5.1.5 AI Activity Panel Interactions

| Element | Trigger | Behavior | API Call |
|---------|---------|----------|----------|
| Activity item | Click | Navigate to related entity (offer, event, client) | None (navigation) |
| Filter dropdown | Change | Filter activities by type | Client-side filter |
| "Show more" link | Click | Expand to show all activities | Client-side expand |
| Panel header collapse | Click | Toggle panel collapsed/expanded | Client-side, persist to localStorage |

**Visibility Logic:**
| Condition | Show/Hide |
|-----------|-----------|
| Always | Show panel (may be collapsed) |
| `activities.length === 0` | Show "No activity yet" message |
| `activities.length > 3` (collapsed) | Show 3 items + "Show more ({count} more)" link |
| Panel expanded | Show all activities |

#### 5.1.6 Loading & Error States

| State | UI Behavior |
|-------|-------------|
| Initial page load | Show skeleton loaders for Thread List |
| Thread selection | Show skeleton loaders for center + right panels |
| API error (4xx/5xx) | Show toast notification with error message, keep previous state |
| Network offline | Show banner at top: "You're offline. Some features may not work." |
| Action in progress | Disable button, show spinner inside button |
| Action success | Show success toast, update UI optimistically |
| Action failure | Show error toast, revert optimistic update |

### 5.2 Event Request Setup — Interactions

#### 5.2.1 Automation Mode Section

| Element | Trigger | Behavior | API Call |
|---------|---------|----------|----------|
| Radio button | Click | Select option, auto-save | `PUT /api/settings/event-requests` `{automation_level: 'semi_auto'}` |
| Radio group | — | Single selection only | — |

**Feedback:** Show subtle checkmark or "Saved" toast after successful save.

#### 5.2.2 Site Visits Section

| Element | Trigger | Behavior | API Call |
|---------|---------|----------|----------|
| Enable toggle | Click | Toggle ON/OFF, show/hide sub-settings | `PUT /api/settings/event-requests` `{site_visits_enabled: true}` |
| Default Timing dropdown | Change | Save selection | `PUT /api/settings/event-requests` `{site_visit_days_before: 14}` |
| Available Days checkboxes | Change | Save selection | `PUT /api/settings/event-requests` `{site_visit_availability: ['weekday_morning', 'weekday_afternoon']}` |
| Minimum Event Size input | Blur/Enter | Validate (min 1), save | `PUT /api/settings/event-requests` `{site_visit_min_attendees: 50}` |

**Visibility Logic:**
| Condition | Show/Hide |
|-----------|-----------|
| `site_visits_enabled: false` | Hide all sub-settings (timing, days, minimum) |
| `site_visits_enabled: true` | Show all sub-settings with animation (slide down) |

**Validation:**
| Field | Rule | Error Message |
|-------|------|---------------|
| Minimum Event Size | Must be ≥ 1 | "Please enter a number of at least 1" |
| Available Days | At least 1 must be selected | "Please select at least one time slot" |

#### 5.2.3 Notifications Section

| Element | Trigger | Behavior | API Call |
|---------|---------|----------|----------|
| Each toggle | Click | Toggle ON/OFF, auto-save | `PUT /api/settings/event-requests` `{notifications: {date_conflicts: true, ...}}` |

**Feedback:** Each toggle saves independently. Show subtle feedback per toggle.

#### 5.2.4 Coming Soon Sections (Offer Settings, Response Style)

| Element | Trigger | Behavior | API Call |
|---------|---------|----------|----------|
| All controls | — | Disabled state (grayed out, not clickable) | None |
| Hover on disabled | Hover | Tooltip: "Coming soon in a future update" | None |

### 5.3 Real-Time Updates

**Mechanism:** Supabase Realtime (consistent with existing app patterns)

| Event | Update Behavior |
|-------|-----------------|
| New email arrives in thread | Add to thread view, update Thread List preview |
| AI sends response | Add to thread view with "🤖 AI Sent" indicator |
| AI generates draft | Show AI Draft panel in thread view |
| Status changes (from another user) | Update status badge in Thread List and Event Details |
| New activity logged | Add to AI Activity Panel |

**Implementation:** Use `supabase.channel` subscriptions, consistent with existing patterns in `useTasksQuery.ts`, `useEvents.ts`, and `useOffers.ts`.

```typescript
// Pattern from existing codebase:
const channel = supabase
  .channel('event-requests')
  .on('postgres_changes',
    { event: '*', schema: 'public', table: 'event_request_threads' },
    (payload) => { /* update local state */ }
  )
  .subscribe();
```

**Why Not Polling:** The rest of OpenEvent uses Supabase Realtime. Using polling for Event Requests would create inconsistent UX where some features update instantly and others lag.

---

## 6. API Endpoints Specification

### 6.1 Event Request Endpoints

| Method | Endpoint | Purpose | Request Body | Response |
|--------|----------|---------|--------------|----------|
| `GET` | `/api/event-requests` | List all event request threads | Query: `?status=lead&q=search` | `{threads: [...], total: number}` |
| `GET` | `/api/event-requests/:threadId` | Get thread details | — | `{thread: {...}, emails: [...], activities: [...], alerts: [...], event: {...}}` |
| `PATCH` | `/api/event-requests/:threadId` | Update thread (star, read) | `{starred?: boolean, read?: boolean}` | `{thread: {...}}` |
| `POST` | `/api/event-requests/:threadId/approve` | Approve and send AI draft | `{draft_id: string}` | `{success: true, email_id: string}` |
| `POST` | `/api/event-requests/:threadId/reject` | Reject/discard AI draft | `{action: 'discard' \| 'edit', draft_id: string}` | `{success: true}` |
| `POST` | `/api/event-requests/:threadId/resolve-conflict` | Resolve date conflict | `{resolution: 'accept_new' \| 'keep_existing', conflict_id: string}` | `{success: true, next_action: string}` |
| `POST` | `/api/event-requests/:threadId/special-request/:requestId` | Accept/decline special request | `{accepted: boolean}` | `{success: true}` |
| `POST` | `/api/event-requests/:threadId/draft-feedback` | Submit 👍/👎 feedback on AI draft | `{draft_id: string, rating: 'positive' \| 'negative'}` | `{success: true}` |
| `POST` | `/api/event-requests/:threadId/suggest-alternatives` | AI finds alternative dates/times | `{conflict_id: string}` | `{alternatives: [...], draft_id: string}` |

### 6.2 Settings Endpoints

| Method | Endpoint | Purpose | Request Body | Response |
|--------|----------|---------|--------------|----------|
| `GET` | `/api/settings/event-requests` | Get all event request settings | — | `{automation_level, site_visits_enabled, ...}` |
| `PUT` | `/api/settings/event-requests` | Update settings (partial) | Any subset of settings fields | `{...updated settings}` |

### 6.3 Existing Endpoints Used

| Method | Endpoint | Purpose | Notes |
|--------|----------|---------|-------|
| `PATCH` | `/api/events/:eventId` | Update event status | Existing endpoint |
| `GET` | `/api/events/:eventId` | Get event details | For "See Full Event" navigation |

### 6.4 Response Schemas

**Thread List Item:**
```json
{
  "id": "uuid",
  "client_name": "Sarah Johnson",
  "client_email": "sarah@techcorp.com",
  "company": "TechCorp Inc.",
  "subject": "Corporate Conference - 150 Guests",
  "preview": "Hi, We are planning our annual...",
  "status": "lead",
  "starred": false,
  "read": true,
  "has_alerts": true,
  "has_pending_draft": false,
  "last_activity_at": "2026-01-26T12:50:00Z",
  "event_id": "uuid"
}
```

**Thread Details:**
```json
{
  "thread": { /* Thread List Item */ },
  "emails": [
    {
      "id": "uuid",
      "from_email": "sarah@techcorp.com",
      "to_email": "events@venue.com",
      "subject": "...",
      "body_html": "...",
      "body_text": "...",
      "sent_at": "2026-01-26T12:50:00Z",
      "sent_by_ai": false
    }
  ],
  "pending_draft": {
    "id": "uuid",
    "body_html": "...",
    "body_text": "...",
    "created_at": "2026-01-26T13:00:00Z"
  } | null,
  "alerts": [
    {
      "id": "uuid",
      "type": "date_conflict",
      "title": "Date Conflict",
      "description": "Conflicts with Chen Wedding Planning (CHF 25,000)",
      "conflicting_event_id": "uuid",
      "created_at": "2026-01-26T12:55:00Z"
    }
  ],
  "activities": [
    {
      "id": "uuid",
      "type": "offer_created",
      "icon": "📄",
      "title": "Created offer",
      "detail": "CHF 18,000 for Main Hall",
      "timestamp": "2026-01-25T10:30:00Z",
      "link": "/offers/uuid"
    }
  ],
  "event": {
    "id": "uuid",
    "status": "lead",
    "event_date": null,
    "start_time": null,
    "end_time": null,
    "attendees": 150,
    "room_ids": [],
    "room_names": []
  },
  "client": {
    "id": "uuid",
    "name": "Sarah Johnson",
    "company": "TechCorp Inc."
  },
  "offer": null | {
    "id": "uuid",
    "total_amount": 18000,
    "currency": "CHF",
    "deposit_paid_at": null
  },
  "site_visit": null | {
    "id": "uuid",
    "confirmed_date": "2026-03-01",
    "confirmed_time": "14:00"
  }
}
```

**Settings:**
```json
{
  "automation_level": "semi_auto",
  "site_visits_enabled": true,
  "site_visit_days_before": 14,
  "site_visit_availability": ["weekday_morning", "weekday_afternoon"],
  "site_visit_min_attendees": 50,
  "notifications": {
    "date_conflicts": true,
    "special_requests": true,
    "new_inquiries": false,
    "event_confirmations": false,
    "deposit_received": false
  },
  "response_tone": "formal",
  "email_signature_type": "team"
}
```

---

## 7. Implementation Priority

### 7.1 MVP Scope

**Event Request Inbox:**
| Component | Priority | Effort |
|-----------|----------|--------|
| Tab in Inbox | P0 | Low |
| Thread List with status badges | P0 | Medium |
| Email Thread View (reuse existing) | P0 | Low |
| Event Details Panel | P0 | Medium |
| Date Conflict Alert | P0 | Medium |
| Special Request Alert | P0 | Medium |
| AI Activity Panel | P1 | Medium |
| Progress Indicator | P2 | Low |
| AI Draft approval in thread | P1 | Medium |

**Event Request Setup:**
| Section | Priority | Effort |
|---------|----------|--------|
| Page route + navigation | P0 | Low |
| Section 1: Automation Mode | P0 | Low |
| Section 2: Site Visits | P0 | Medium |
| Section 3: Notifications | P1 | Low |
| Section 4: Offer Settings (disabled) | P2 | Low |
| Section 5: Response Style - Tone & Signature | P0 | Low |
| Section 5: Response Style - Language & Instructions (disabled) | P2 | Low |

### 7.2 Database & Infrastructure Required

**Note:** API endpoints are fully specified in Section 6.

**⚠️ Infrastructure Requirements:**
Verify the following exist or need to be created/extended:

| Item | Type | Required For | Notes |
|------|------|--------------|-------|
| `team_settings` table | Database | Setup page settings storage | May need new columns for event request fields |
| `useTeamSettings` hook | Frontend | Fetching/updating settings | Pattern after `useUserPreferences` |
| `event_request_threads` table | Database | Storing thread data for Inbox | Check if already exists from backend |

**New Database Fields:**

For `team_settings` table (must be created):
```
automation_level: enum ('review_all', 'semi_auto', 'full_auto')
site_visits_enabled: boolean
site_visit_days_before: integer
site_visit_availability: string[]
site_visit_min_attendees: integer
notifications: jsonb {
  date_conflicts: boolean,
  special_requests: boolean,
  new_inquiries: boolean,
  event_confirmations: boolean,
  deposit_received: boolean
}
response_tone: enum ('formal', 'friendly')
email_signature_type: enum ('team', 'personal', 'none')
```

### 7.3 Design Assets Needed

- [ ] Status badge color tokens (Lead/Option/Confirmed/Cancelled)
- [ ] Activity icons (calendar, offer, CRM, site visit, deposit, email)
- [ ] AI indicator icon/badge ("🤖 AI Sent", "🤖 AI Draft")
- [ ] Progress indicator component (5-step horizontal)
- [ ] Empty state illustrations (optional)

---

## Appendix A: Vocabulary Consistency Guide

This section ensures all terminology matches the existing OpenEvent frontend.

### A.1 Canonical Terms (USE THESE)

| Canonical Term | DO NOT USE | Notes |
|----------------|------------|-------|
| **Client** | Customer, Contact, Guest | Entity name |
| **Event** | Booking (as noun) | Entity name for the event/booking record |
| **Offer** | Quote, Proposal | Entity name |
| **Room** | Space, Venue, Hall | Entity name (venue = the whole building) |
| **Attendees** | Guests, Participants, People | Number of people attending |
| **Company** | Organization, Firm | Client's company name (display label) |
| **Site Visit** | Venue Tour, Viewing | Scheduled tour before booking |
| **Deposit** | Prepayment, Down payment | Advance payment to secure event |

### A.2 Status Values (Exact Match Required)

**Event/Client Status:** `lead` → `option` → `confirmed` → `cancelled`

| Status | UI Label | Color | Used In Event Requests |
|--------|----------|-------|------------------------|
| `lead` | Lead | Gray | Yes |
| `option` | Option | Yellow/Amber | Yes |
| `confirmed` | Confirmed | Green | Yes |
| `cancelled` | Cancelled | Red | Yes |
| `blocked` | Blocked | — | No (internal calendar use only) |

**Note:** The `blocked` status exists in the events table for internal calendar blocking but is not part of the Event Request workflow.

**Offer Status:** `Draft` → `Sent` → `Confirmed` → `Cancelled`

### A.3 Field Labels vs Backend Names

| UI Label (Display) | Backend Field | Notes |
|--------------------|---------------|-------|
| Date | `event_date` / `chosen_date` | |
| Time | `start_time` + `end_time` | Format: "09:00 - 17:00" |
| Client | `client_name` | |
| Company | `organization` / `company` | Backend varies, always display as "Company" |
| Attendees | `attendees` / `number_of_participants` | Backend varies, always display as "Attendees" |
| Room | `rooms.name` via `room_ids` | |
| Offer | `offers.total_amount` | Display with currency: "CHF 18,000" |
| Deposit | `deposit_paid_at` | Display as "Paid" / "Not Paid" |
| Site Visit | `site_visits` table | Display date + time |

### A.4 Action Labels

| Action Type | Correct Label | Notes |
|-------------|---------------|-------|
| View full record | "See Full Event" | Matches "See client's events" pattern |
| Create new | "Add [Entity]" | e.g., "Add Client" |
| Modify | "Edit [Entity]" | |
| Remove | "Delete [Entity]" | |
| Approve AI draft | "Send Now" | Clear intent |
| Reject AI draft | "Discard" | |
| Modify AI draft | "Edit Draft" | |

### A.5 Terms NOT Used in UI

| Term | Reason | Internal Only? |
|------|--------|----------------|
| Booking | Use "Event" for entity name | OK in phrases like "booking flow" |
| BEO | Too technical for UI | Yes |
| HIL | Technical jargon | Yes |
| Workflow | Technical jargon | Yes |
| Pipeline | OK in CRM context | Marketing only |
| LLM / AI Agent | Use "AI" simply | Yes |

### A.6 Glossary

| Term | Definition | Used In |
|------|------------|---------|
| Lead | New inquiry, not yet qualified | Status badges, filters |
| Option | Client interested, date tentatively held | Status badges, filters |
| Confirmed | Event finalized, contract signed | Status badges, filters |
| Site Visit | Venue tour scheduled before event | Settings, details panel |
| Deposit | Advance payment to secure event | Details panel, alerts |
| Event Request | Incoming email identified as event inquiry | Tab name, feature name |

---

## Appendix B: Research Sources

### Activity Feed & Dashboard Design
1. [GetStream - Activity Feed Design Guide](https://getstream.io/blog/activity-feed-design/)
2. [UI-Patterns - Activity Stream](https://ui-patterns.com/patterns/ActivityStream)
3. [Aubergine - Chronological Activity Feed Guide](https://www.aubergine.co/insights/a-guide-to-designing-chronological-activity-feeds)
4. [Microsoft Dynamics 365 - AI Agent Activity Feed](https://www.microsoft.com/en-us/dynamics-365/blog/it-professional/2025/10/08/try-the-ai-agent-activity-feed-in-dynamics-365-customer-service/)
5. [SuprSend - Activity Feed Guide](https://www.suprsend.com/post/activity-feed)

### Settings & Form Design
6. [Toptal - Settings UX Guide](https://www.toptal.com/designers/ux/settings-ux)
7. [SetProduct - Settings UI Design](https://www.setproduct.com/blog/settings-ui-design)
8. [Cieden - Toggle Switch Best Practices](https://cieden.com/book/atoms/toggle-switch/toggle-switch-ux-best-practices)

### Empty States & Progressive Disclosure
9. [NN/G - Designing Empty States in Complex Applications](https://www.nngroup.com/articles/empty-state-interface-design/)
10. [Toptal - Empty States: The Most Overlooked Aspect of UX](https://www.toptal.com/designers/ux/empty-state-ux-design)
11. [Eleken - Empty State UX Examples and Design Rules](https://www.eleken.co/blog-posts/empty-state-ux)
12. [LogRocket - Progressive Disclosure in UX Design](https://blog.logrocket.com/ux-design/progressive-disclosure-ux-types-use-cases/)
13. [UXPin - What is Progressive Disclosure?](https://www.uxpin.com/studio/blog/what-is-progressive-disclosure/)
14. [Carbon Design System - Empty States Pattern](https://carbondesignsystem.com/patterns/empty-states-pattern/)

### AI in Event Management
15. [Eventify - AI in Event Management](https://eventify.io/blog/ai-in-event-management)
16. [Glue Up - AI-Powered Event Planning](https://www.glueup.com/blog/ai-powered-event-planning-software)

### Event Management Industry
17. [Planning Pod - Venue Management](https://planningpod.com/)
18. [Tripleseat - Event Management Software](https://tripleseat.com/)
19. [Perfect Venue - Event Management](https://www.perfectvenue.com/)
20. [EventPro - Venue Booking](https://www.eventpro.net/)
21. [Momentus - Venue Management](https://gomomentus.com/)

---

## Appendix C: UX Review Prompt for Second Specialist

Use this prompt to guide the UX review before implementation.

---

### REVIEW PROMPT: Event Request Feature UX Validation

**Context:**
You are reviewing the UX design specification for OpenEvent's new "Event Requests" feature. This feature connects an AI email workflow backend to the frontend, allowing event managers to supervise and interact with AI-processed event inquiries.

**Target User:**
Event managers at venues (hotels, conference centers, event spaces) who handle 5-15 active inquiries daily, spend 40-50% of their time on email, and fear double-booking rooms.

**Documents to Review:**
- `EVENT_REQUEST_UX_DESIGN_SPEC.md` (this document)
- `FRONTEND_REFERENCE.md` (existing OpenEvent frontend patterns)
- `Design_Frontend_Event_Requests_Setup.pdf` (original requirements from CO)

---

### REVIEW CHECKLIST

#### 1. Information Architecture
**Design sources:** [Planning Pod](https://planningpod.com/), [Tripleseat](https://tripleseat.com/) — event managers spend 40-50% time in email

- [ ] Does the Event Requests tab placement within Inbox match user mental models?
- [ ] Is the three-panel layout (Thread List / Email / Context) appropriate for the task?
- [ ] Are the right-panel sections (Alerts, Event Details, AI Activity) prioritized correctly?
- [ ] Should any information be moved between panels?

#### 2. Vocabulary & Terminology
**Design sources:** [Tripleseat](https://tripleseat.com/), [Perfect Venue](https://www.perfectvenue.com/), [EventPro](https://www.eventpro.net/) — industry-standard terminology

- [ ] Review Appendix A: Are all terms consistent with existing OpenEvent pages?
- [ ] Are there any terms that would confuse event managers?
- [ ] Is "Event Requests" the right name for this tab? Alternatives: "Inquiries", "AI Inbox", "Booking Requests"

#### 3. Event Details Panel — Progressive Disclosure
**Design sources:** [NN/G Empty States](https://www.nngroup.com/articles/empty-state-interface-design/), [LogRocket Progressive Disclosure](https://blog.logrocket.com/ux-design/progressive-disclosure-ux-types-use-cases/), [UXPin Progressive Disclosure](https://www.uxpin.com/studio/blog/what-is-progressive-disclosure/)

- [ ] Is the split between "always show" and "show when available" fields correct?
- [ ] Core fields (Status, Date, Time, Client, Company, Attendees, Room) — any missing?
- [ ] Stage-dependent fields (Offer, Deposit, Site Visit) — is the logic correct?
- [ ] Should any other fields appear conditionally?

#### 4. Alerts Panel — Decision Making
**Design sources:** [Planning Pod](https://planningpod.com/) — #1 fear is double-booking; [EventPro](https://www.eventpro.net/) — conflict resolution patterns

- [ ] Date Conflict Alert: Are "Accept New" / "Keep Existing" clear enough?
- [ ] Special Request Alert: Are "Accept" / "Decline" sufficient? Need "Accept with conditions"?
- [ ] Should alerts have priority levels (critical vs. informational)?
- [ ] Is the auto-dismiss behavior after action appropriate?

#### 5. AI Activity Panel — Transparency
**Design sources:** [GetStream Activity Feed](https://getstream.io/blog/activity-feed-design/), [UI-Patterns Activity Stream](https://ui-patterns.com/patterns/ActivityStream), [Microsoft Dynamics 365 AI Agent Feed](https://www.microsoft.com/en-us/dynamics-365/blog/it-professional/2025/10/08/try-the-ai-agent-activity-feed-in-dynamics-365-customer-service/)

- [ ] Are the listed activity types comprehensive? Missing any important AI actions?
- [ ] Is the "hidden activities" list correct (internal ops that shouldn't show)?
- [ ] Is 3 items (collapsed) the right default? Too few? Too many?
- [ ] Should activities be grouped by day or shown as flat list?

#### 6. AI Draft Approval Flow
**Design sources:** [Microsoft Dynamics 365](https://www.microsoft.com/en-us/dynamics-365/blog/it-professional/2025/10/08/try-the-ai-agent-activity-feed-in-dynamics-365-customer-service/) — inline approval faster than separate page; [Glue Up AI Guide](https://www.glueup.com/blog/ai-powered-event-planning-software) — human oversight points

- [ ] Is inline approval (in email thread) better than separate Tasks page?
- [ ] Are "Edit Draft" / "Send Now" / "Discard" the right actions?
- [ ] Should there be a "Send with edits" combined action?
- [ ] Is the confirmation dialog necessary or friction?

#### 7. Setup Page — Settings Design
**Design sources:** [Toptal Settings UX](https://www.toptal.com/designers/ux/settings-ux), [SetProduct Settings UI](https://www.setproduct.com/blog/settings-ui-design), [Cieden Toggle Best Practices](https://cieden.com/book/atoms/toggle-switch/toggle-switch-ux-best-practices)

- [ ] Section 1 (Automation Mode): Are 3 levels right? Need 2 or 4?
- [ ] Section 2 (Site Visits): Any missing configuration options?
- [ ] Section 3 (Notifications): Any missing notification types?
- [ ] Are "Coming Soon" sections (4-5) appropriate to show disabled?

#### 8. Interaction Design
**Design sources:** [Aubergine Activity Feed Guide](https://www.aubergine.co/insights/a-guide-to-designing-chronological-activity-feeds), [SuprSend Notification Preferences](https://www.suprsend.com/post/activity-feed)

- [ ] Review Section 5: Are all click/hover/change interactions specified?
- [ ] Are loading states defined for all async operations?
- [ ] Are error states and recovery paths clear?
- [ ] Is real-time update strategy (polling vs. WebSocket) appropriate for MVP?

#### 9. API Completeness
**Design sources:** Section 5 interaction requirements → API mapping

- [ ] Review Section 6: Do the endpoints cover all frontend interactions?
- [ ] Are request/response schemas complete?
- [ ] Any missing endpoints for actions defined in Section 5?
- [ ] Is partial update (`PUT` settings) correct or should it be `PATCH`?

#### 10. Edge Cases
**Design sources:** [Eventify AI Guide](https://eventify.io/blog/ai-in-event-management) — AI error handling; [Momentus](https://gomomentus.com/) — multi-user venue scenarios

- [ ] What happens when AI makes a mistake and manager needs to undo?
- [ ] What if multiple managers view the same thread simultaneously?
- [ ] What if client responds while manager is reviewing draft?
- [ ] What if date conflict involves 3+ events, not just 2?

#### 11. Accessibility
**Design sources:** [Carbon Design System Empty States](https://carbondesignsystem.com/patterns/empty-states-pattern/), [Toptal Empty States](https://www.toptal.com/designers/ux/empty-state-ux-design)

- [ ] Are all interactive elements keyboard accessible?
- [ ] Do color-coded status badges have text labels?
- [ ] Are confirmation dialogs screen-reader friendly?
- [ ] Is there sufficient color contrast for all states?

#### 12. Mobile Responsiveness
**Design sources:** General responsive design principles; existing OpenEvent patterns

- [ ] How should the three-panel layout adapt on tablet/mobile?
- [ ] Which panels collapse or become tabs on smaller screens?
- [ ] Are touch targets large enough (minimum 44px)?

---

### DELIVERABLES

After review, provide:

1. **Approved** — Ready for implementation
2. **Approved with minor changes** — List specific changes needed
3. **Needs revision** — List major issues that require redesign

For each issue found:
- Severity: Critical / Major / Minor / Suggestion
- Location: Section number and specific element
- Issue: What's wrong
- Recommendation: How to fix

---

### QUESTIONS TO ANSWER

1. Is this design **complete** enough for frontend developers to implement without ambiguity?
2. Are there any **conflicts** with existing OpenEvent patterns or components?
3. Are there any **missing interactions** that users would expect?
4. Are the **API endpoints** sufficient for all frontend requirements?
5. Would you **recommend** this design for implementation?

---

*End of Review Prompt*

---

## Appendix C.2: Final Validation Review Prompt (Post-Revision)

Use this prompt for a second specialist to validate the design after incorporating UX Review feedback.

---

### FINAL VALIDATION REVIEW: Event Request Feature — Platform Integration & Implementation Readiness

**Context:**
This design specification has been revised based on an initial UX review. The following changes were incorporated:

| Priority | Change Applied |
|----------|----------------|
| P1 | Mobile Adaptation added (Section 3.2.1) — drill-down navigation on <768px |
| P2 | "Suggest Alternatives" action added to Date Conflict alerts |
| P3 | Source Grounding & Confidence Indicators added (Section 3.5.2) |
| P4 | Tone & Email Signature moved to MVP (Section 4.7) |
| P5 | Task Integration clarified — Event Requests don't appear in /tasks unless flagged |

Additionally, Appendix D was added to document existing OpenEvent components that MUST be reused.

**Your Role:**
1. Validate that the design is **implementation-ready** — complete, unambiguous
2. **CRITICAL:** Validate that Event Requests integrates optimally with the **entire OpenEvent platform** — not as an isolated feature, but as a natural extension of existing workflows

**OpenEvent Platform Context:**
The Event Requests feature connects to:
- `/inbox` — Email management (Inbox2.tsx)
- `/events/:id` — Event detail pages with offers, tasks, documents
- `/calendar` — Room availability and date conflicts
- `/crm` — Client management
- `/tasks` — Task kanban board
- `/offers` — Offer creation and management
- `/setup/*` — Configuration pages (Rooms, Products, Offers, Templates)

---

### VALIDATION CHECKLIST

#### 1. Completeness Check
- [ ] Can a frontend developer implement each component without asking clarifying questions?
- [ ] Are all user interactions specified (click, hover, input, submit)?
- [ ] Are all visibility conditions defined (when to show/hide elements)?
- [ ] Are all error states and loading states covered?
- [ ] Are all API request/response schemas complete?

#### 2. Consistency with OpenEvent Patterns
**Reference:** Appendix D (Component Reuse Guide)

- [ ] Does the design use existing UI components (Badge, Card, Dialog, etc.)?
- [ ] Does special request handling use `ProductCombobox` as specified?
- [ ] Are status badge colors consistent with Calendar/CRM pages?
- [ ] Does email display reuse Inbox2 patterns (sanitizeHTML, formatEmailTime)?
- [ ] Are hooks properly referenced (useToast, useSelectedTeam, etc.)?

#### 3. Mobile Experience (P1 Validation)
**Reference:** Section 3.2.1

- [ ] Is the drill-down navigation clearly specified?
- [ ] Is the slide-over sheet for Context Panel well-defined?
- [ ] Are touch targets specified (44px minimum)?
- [ ] Is the [ℹ Info] icon placement clear in thread view header?

#### 4. AI Transparency (P3 Validation)
**Reference:** Section 3.5.2

- [ ] Is source grounding visual treatment specified (dotted underline)?
- [ ] Are confidence thresholds defined (80% cutoff)?
- [ ] Is the low-confidence warning treatment clear (yellow + ⚠️)?
- [ ] Which fields show source grounding vs. which don't?

#### 5. Response Style MVP (P4 Validation)
**Reference:** Section 4.7

- [ ] Is the Tone toggle interaction specified?
- [ ] Is the Email Signature dropdown complete with all options?
- [ ] Are default values defined?
- [ ] Is the signature preview behavior specified?

#### 6. Edge Cases & Error Handling

- [ ] What happens if AI extraction confidence is 0% (complete failure)?
- [ ] What if a thread has no associated event yet?
- [ ] What if the manager is offline when approving a draft?
- [ ] What if multiple alerts exist (order, max displayed)?
- [ ] What if "Suggest Alternatives" finds no available dates?

#### 7. API Contract Verification

- [ ] Do all interactions in Section 5 have matching endpoints in Section 6?
- [ ] Are the new settings (response_tone, email_signature_type) in the schema?
- [ ] Is the feedback endpoint for 👍/👎 on AI drafts specified?
- [ ] Is the "Suggest Alternatives" endpoint specified?

#### 8. Accessibility Validation

- [ ] Are AI-extracted field indicators accessible (not color-only)?
- [ ] Does source grounding work with screen readers (tooltip content)?
- [ ] Are mobile gestures (slide-over sheet) keyboard accessible?
- [ ] Is there sufficient contrast for confidence indicators?

#### 9. Platform Integration — Cross-Feature Flows

**This is the most critical section.** Event Requests must feel like a natural part of OpenEvent, not a bolted-on feature.

##### 9.1 Inbox Integration
- [ ] Does the Event Requests tab feel native to the existing Inbox?
- [ ] Can users easily switch between regular emails and Event Requests?
- [ ] Is the email compose/reply flow consistent with existing Inbox behavior?
- [ ] If a regular email is reclassified as an event request, what happens?

##### 9.2 Calendar Integration
- [ ] When "Suggest Alternatives" runs, does it use the same availability logic as Calendar?
- [ ] Are date conflicts detected using the same source of truth as Calendar blocking?
- [ ] Can managers click from a conflict alert to view the Calendar?
- [ ] When an event is confirmed, does it immediately appear on Calendar?

##### 9.3 CRM Integration
- [ ] When AI creates a client, does it appear in CRM immediately?
- [ ] Can managers click client name in Event Details to go to CRM profile?
- [ ] Are client preferences (from previous events) available to AI?
- [ ] Is company/organization data synced bidirectionally?

##### 9.4 Events & Offers Integration
- [ ] Does "See Full Event →" link to the correct EventDetail tab?
- [ ] When AI creates an offer, does it use the same offer structure as manual offers?
- [ ] Can managers navigate from Event Request to Offers page to see all offers?
- [ ] Are products added via special requests visible in the Event's offer tab?

##### 9.5 Tasks Integration
- [ ] When "Flag for Follow-up" creates a task, does it appear in Tasks kanban?
- [ ] Does the task link back to the Event Request thread?
- [ ] Are task categories consistent with existing task types?
- [ ] Can managers assign flagged tasks to team members?

##### 9.6 Setup Pages Integration
- [ ] Does Event Request Setup follow the same layout pattern as other Setup pages?
- [ ] Are room references pulling from the same Rooms data as Room Setup?
- [ ] Is the signature setting connected to existing signature management (if any)?
- [ ] Do product references in Special Requests use Products from Products Setup?

##### 9.7 Navigation Coherence
- [ ] Is there a clear mental model of where Event Requests "lives" in the app?
- [ ] Are breadcrumbs/back navigation consistent?
- [ ] Do all cross-feature links open in appropriate context (same tab vs new tab)?
- [ ] Is sidebar navigation updated to reflect Event Request Setup?

##### 9.8 Data Consistency
- [ ] Is there a single source of truth for event status (Lead/Option/Confirmed)?
- [ ] If status changes in Event Requests, does it update in Calendar, CRM, Events?
- [ ] Are timestamps consistent across features (same timezone handling)?
- [ ] Is currency formatting consistent with Offers and other financial displays?

##### 9.9 User Journey Completeness
Review these end-to-end user journeys:

**Journey 1: New Inquiry → Confirmed Event**
```
Email arrives → AI creates thread → Manager reviews →
Offer sent → Client confirms → Deposit paid → Event confirmed
```
- [ ] Is every step in this journey covered?
- [ ] Can the manager complete this journey without leaving Event Requests (except for "See Full Event")?

**Journey 2: Date Conflict Resolution**
```
Conflict detected → Manager reviews both events →
Decides to suggest alternatives → Client picks new date → Resolved
```
- [ ] Can the manager see both conflicting events' details?
- [ ] Is the alternative suggestion flow smooth?

**Journey 3: Special Request with New Product**
```
Client requests live-streaming → Alert shown →
Manager accepts → Needs to add product → Product added to offer
```
- [ ] Does this flow use existing ProductCombobox?
- [ ] Is the product immediately visible in the event's offer?

**Journey 4: Site Visit Scheduling**
```
AI offers site visit → Client accepts → Time scheduled →
Visit completed → Status updated
```
- [ ] Does site visit appear in a calendar view anywhere?
- [ ] Is the manager notified of upcoming site visits?

---

### SPECIFIC QUESTIONS TO ANSWER

1. **Is the design complete?**
   List any missing specifications that would block implementation.

2. **Are there any conflicts with existing OpenEvent code?**
   Reference specific files from Appendix D if conflicts exist.

3. **Rate the mobile adaptation:**
   - Excellent: Ready for implementation
   - Good: Minor clarifications needed
   - Needs work: Significant gaps

4. **Rate the AI transparency features:**
   - Excellent: Clear, implementable
   - Good: Minor clarifications needed
   - Needs work: Significant gaps

5. **Is Appendix D sufficient?**
   Are there other existing components that should be referenced?

6. **Platform Integration Assessment (CRITICAL):**
   - Does Event Requests feel like a **native part** of OpenEvent or a **separate addon**?
   - Are all cross-feature navigation paths clear and consistent?
   - Will users be confused about where data lives or how features connect?
   - Rate overall integration: Seamless / Good / Fragmented

7. **Missing Integration Points:**
   List any connections between Event Requests and other OpenEvent features that are:
   - Undefined (not mentioned)
   - Unclear (mentioned but vague)
   - Potentially conflicting with existing patterns

8. **User Journey Gaps:**
   For the 4 journeys in Section 9.9, identify any steps that are:
   - Not covered in the spec
   - Would require leaving the Event Requests flow unexpectedly
   - Could cause data inconsistency

9. **Final recommendation:**
   - ✅ **Approved for implementation**
   - ⚠️ **Approved with minor fixes** (list fixes)
   - ❌ **Needs revision** (list blockers)

---

### OUTPUT FORMAT

Provide your review in this structure:

```markdown
## Final Validation Report

**Reviewer:** [Name]
**Date:** [Date]
**Status:** [Approved / Approved with Fixes / Needs Revision]

### Executive Summary
[2-3 sentence overall assessment including platform integration verdict]

---

## Part 1: Feature Design Quality

### Completeness Score: X/10
[List any gaps]

### Mobile Adaptation: [Excellent/Good/Needs Work]
[Specific feedback]

### AI Transparency: [Excellent/Good/Needs Work]
[Specific feedback]

---

## Part 2: Platform Integration (CRITICAL)

### Integration Score: X/10
[How well does Event Requests integrate with the broader OpenEvent platform?]

### Integration Assessment: [Seamless/Good/Fragmented]
[Does it feel native or bolted-on?]

### Cross-Feature Navigation
| From → To | Status | Notes |
|-----------|--------|-------|
| Event Requests → Calendar | ✅/⚠️/❌ | [Notes] |
| Event Requests → CRM | ✅/⚠️/❌ | [Notes] |
| Event Requests → Events | ✅/⚠️/❌ | [Notes] |
| Event Requests → Tasks | ✅/⚠️/❌ | [Notes] |
| Event Requests → Offers | ✅/⚠️/❌ | [Notes] |

### Data Consistency Check
| Data Element | Consistent? | Issue (if any) |
|--------------|-------------|----------------|
| Event Status | ✅/❌ | [Notes] |
| Client Data | ✅/❌ | [Notes] |
| Offer Data | ✅/❌ | [Notes] |
| Room/Calendar | ✅/❌ | [Notes] |

### User Journey Assessment
| Journey | Complete? | Gap Description |
|---------|-----------|-----------------|
| Inquiry → Confirmed | ✅/⚠️/❌ | [Notes] |
| Date Conflict Resolution | ✅/⚠️/❌ | [Notes] |
| Special Request Flow | ✅/⚠️/❌ | [Notes] |
| Site Visit Scheduling | ✅/⚠️/❌ | [Notes] |

---

## Part 3: Implementation Readiness

### Component Reuse: [Good/Needs Additions]
[Is Appendix D sufficient?]

### Missing Specifications
1. [Gap 1]
2. [Gap 2]
...

### Missing API Endpoints
- [List any missing endpoints]

### Conflicts with Existing Code
- [List any conflicts, reference files]

---

## Part 4: Action Items

### Required Fixes Before Implementation (Blockers)
1. [Fix 1 - Severity: Critical/Major]
2. [Fix 2 - Severity: Critical/Major]
...

### Recommended Improvements (Non-blocking)
1. [Recommendation 1]
2. [Recommendation 2]
...

### Integration Improvements Needed
1. [Integration fix 1]
2. [Integration fix 2]
...

---

## Final Sign-off

| Criterion | Verdict |
|-----------|---------|
| Feature Design Complete | ✅/❌ |
| Platform Integration Acceptable | ✅/❌ |
| Component Reuse Verified | ✅/❌ |
| API Contract Complete | ✅/❌ |

**Approved for Implementation:** [Yes / Yes with Fixes / No]

**Estimated Effort:** [Low / Medium / High]

**Priority Integration Fixes:** [List top 3 if any]
```

---

*End of Final Validation Review Prompt*

---

## Appendix D: Existing OpenEvent Components to Reuse

This section identifies existing components that MUST be reused to avoid redundancy and maintain consistency.

### D.1 UI Components (src/components/ui/)

| Component | Location | Use In Event Requests |
|-----------|----------|----------------------|
| `Badge` | ui/badge.tsx | Status badges (Lead, Option, Confirmed) |
| `Card` | ui/card.tsx | Section containers in Setup page |
| `Tabs` | ui/tabs.tsx | Already used for Inbox tabs |
| `Dialog` | ui/dialog.tsx | Confirmation dialogs, full event view |
| `DropdownMenu` | ui/dropdown-menu.tsx | Filter dropdowns, status selector |
| `Select` | ui/select.tsx | All dropdown selections |
| `Switch` | ui/switch.tsx | Toggle settings (Site Visits, Notifications) |
| `Checkbox` | ui/checkbox.tsx | Multi-select options (Available Days) |
| `Input` | ui/input.tsx | Number inputs, search |
| `ScrollArea` | ui/scroll-area.tsx | Thread list, activity panel |
| `Avatar` | ui/avatar.tsx | Client avatars in thread list |
| `Tooltip` | ui/tooltip.tsx | Source grounding hover, AI reasoning |
| `Accordion` | ui/accordion.tsx | Collapsible activity panel |

### D.2 Feature Components to Reuse

#### Product Selection (Special Requests)
**When client requests a product/service (e.g., live-streaming, catering upgrade):**

DO NOT create a new product selector. Instead:
1. **Use `EnhancedProductCombobox`** from `src/components/offers/EnhancedProductCombobox.tsx` (preferred — handles searching, custom entries, and category filtering)
2. Link to existing "Add Product" flow from Offers tab

**Pattern:** Special Request Alert → "Accept" → Opens product dialog with `EnhancedProductCombobox` pre-filled

#### AI Draft Panel Styling
**For the AI Draft review panel in email thread:**

The AI Draft panel should share underlying UI styles with existing `AIReplyInput` component to maintain visual consistency across AI-assisted features.

#### Email Thread Display
**For displaying email conversations:**

Reuse patterns from `src/pages/Inbox2.tsx`:
- Email sanitization: `sanitizeHTML()` function
- Time formatting: `formatEmailTime()` helper
- Email content styling: `emailContentStyles` CSS

#### Tasks Integration
**For "Flag for Follow-up" action:**

Reuse existing task creation:
- `NewTaskDialog` from `src/components/NewTaskDialog.tsx`
- `useTasks` hook from `src/hooks/useTasksQuery.ts`
- Task entity structure from existing Tasks page

```typescript
// When flagging a thread for follow-up:
createTask({
  title: `Follow up: ${thread.client_name} - ${thread.subject}`,
  category: "events",  // IMPORTANT: lowercase 'events' to match NewTaskDialog.tsx
  event_id: thread.event_id,
  // ... other fields
});
```

**⚠️ Integration Note:** The category MUST be lowercase `'events'` (not "Events" or "event") to match the existing task category logic in `NewTaskDialog.tsx`.

#### Offer Display
**For showing offer amount in Event Details:**

Format currency using existing pattern:
- `usePreferences` hook for `formatCurrency`
- Match display from `src/pages/EventDetail.tsx`

### D.3 Existing Page Patterns to Follow

#### EventDetail.tsx Pattern
The Event Details Panel should follow patterns from `src/pages/EventDetail.tsx`:
- Tabs for different sections (if expanded view needed)
- Card-based layout for information groups
- Edit dialogs for field modifications

#### Tasks.tsx Pattern
The AI Activity Panel can follow patterns from `src/pages/Tasks.tsx`:
- `TeamMemberFilters` pattern for activity type filtering
- `Accordion` for collapsible sections
- Sort controls for activity ordering

#### Offers.tsx Pattern
The Thread List should follow patterns from `src/pages/Offers.tsx`:
- Table/List with filtering
- Search input with debouncing
- Status filtering

### D.4 Hooks to Reuse

| Hook | Location | Use Case |
|------|----------|----------|
| `useToast` | hooks/use-toast.ts | Success/error notifications |
| `useSelectedTeam` | hooks/useSelectedTeam.ts | Team context for all operations |
| `useRooms` | hooks/useRooms.ts | Room display in Event Details |
| `useClients` | hooks/useClientsQuery.ts | Client information |
| `useTasks` | hooks/useTasksQuery.ts | Task creation for follow-ups |
| `useOffers` | hooks/useOffers.ts | Offer display in Event Details |

### D.5 Things NOT to Recreate

| Feature | Why Not Recreate | Instead |
|---------|------------------|---------|
| Product catalog | Already exists in Products | Link to existing Add Product dialog |
| Client edit form | Already exists | Use `EditClientDialog.tsx` |
| Offer creation | Complex existing logic | Link to "See Full Event" → Offer tab |
| Room availability calendar | Exists in Calendar page | Link to Calendar or show summary |
| Email compose | Already in Inbox | Reuse existing compose flow |

### D.6 Cross-Feature Navigation Map

Event Requests connects to other OpenEvent pages. These navigation paths must be implemented:

| From Event Requests | To | Trigger | Behavior |
|--------------------|----|---------|----------|
| Event Details Panel | `/events/:id` | Click "See Full Event →" | Opens event detail page |
| Event Details Panel | `/events/:id/offer` | Click Offer amount | Opens event with Offer tab active |
| Date Conflict Alert | `/calendar?date=YYYY-MM-DD` | Click "View in Calendar" | Opens Calendar filtered to conflict date (new tab) |
| Client name | `/crm/clients/:id` | Click client name | Opens client profile in CRM |
| AI Activity "Created offer" | `/offers/:id` | Click activity item | Opens offer detail |
| AI Activity "Added client" | `/crm/clients/:id` | Click activity item | Opens client in CRM |
| Special Request "Accept" | Product dialog | Click Accept | Opens `EnhancedProductCombobox` dialog |
| "Flag for Follow-up" | Creates task | Click action | Task appears in `/tasks` kanban with `category: 'events'` |

**Navigation Patterns:**
- **Same tab:** CRM, Events, Offers (user expects to return)
- **New tab:** Calendar view (reference while working)
- **Dialog/Modal:** Product selection, confirmations

### D.7 Implementation Notes

#### Creating New Event from Thread
When AI creates a new event from an email thread, it should:
1. Create event record using existing patterns
2. Associate with client (create if needed via existing flow)
3. The Event Details Panel links to the full event page

```typescript
// Navigation pattern:
navigate(`/events/${eventId}/offer`);  // With tab parameter like existing code
```

#### Status Badge Colors
Reuse existing color tokens. Check `src/components/calendar/StatusLegend.tsx` for color definitions:
```typescript
// Status colors should match Calendar legend
const statusColors = {
  lead: "bg-gray-100 text-gray-800",
  option: "bg-yellow-100 text-yellow-800",
  confirmed: "bg-green-100 text-green-800",
  cancelled: "bg-red-100 text-red-800"
};
```

---

*End of Document*
