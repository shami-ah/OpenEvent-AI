"""Legacy conversation helpers for the deprecated UI flow."""

# DEPRECATED: Legacy wrapper kept for compatibility. Do not add workflow logic here.
# Intake/Date/Availability live in backend/workflows/groups/* and are orchestrated by workflow_email.py.

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

from backend.domain import ConversationState, EventInformation, IntentLabel
from backend.utils.openai_key import load_openai_api_key
from backend.workflow_email import DB_PATH as WF_DB_PATH, load_db as wf_load_db, save_db as wf_save_db
from backend.workflows.common.types import IncomingMessage, WorkflowState
from backend.workflows.steps.step3_room_availability.trigger import process as step3_process

load_dotenv(override=False)

client = OpenAI(api_key=load_openai_api_key())

# In-memory storage for demo
active_conversations: dict[str, ConversationState] = {}

# Resolve static data paths relative to this module so imports work from any CWD.
BASE_PATH = Path(__file__).resolve().parent

STEP3_DRAFT_CACHE: Dict[str, str] = {}
STEP3_PAYLOAD_CACHE: Dict[str, Dict[str, Any]] = {}


def _step3_cache_key(session_id: Optional[str]) -> str:
    return session_id or "__default__"


def _normalise_step3_draft(session_id: Optional[str], drafts: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    if not drafts:
        return None
    cache_key = _step3_cache_key(session_id)
    for draft in drafts:
        step_raw = draft.get("step")
        is_step_three = False
        if isinstance(step_raw, int):
            is_step_three = step_raw == 3
        else:
            step_str = str(step_raw or "").strip()
            if step_str.lower().startswith("step3"):
                is_step_three = True
            else:
                match = re.match(r"^(\d+)", step_str)
                if match:
                    is_step_three = int(match.group(1)) == 3
        if not is_step_three:
            continue
        body_md = draft.get("body_markdown") or draft.get("body_md") or draft.get("body")
        if not isinstance(body_md, str) or not body_md.strip():
            continue
        signature = body_md.strip()
        cached = STEP3_DRAFT_CACHE.get(cache_key)
        if cached and cached == signature:
            return None
        STEP3_DRAFT_CACHE[cache_key] = signature
        payload = {
            "subject": draft.get("subject") or "Room options and available dates",
            "body_markdown": body_md,
            "body": draft.get("body") or body_md,
            "actions": draft.get("actions") or [],
            "footer": draft.get("footer"),
        }
        STEP3_PAYLOAD_CACHE[cache_key] = payload
        return payload
    return None


def _render_step3_from_workflow(state: ConversationState) -> Optional[Dict[str, Any]]:
    event_id = state.event_id
    if not event_id:
        return None
    try:
        db = wf_load_db()
    except Exception as exc:
        print(f"[WF][WARN] Step-3 render skipped (load failed): {exc}")
        return None

    events = db.get("events") or []
    event_entry = next((evt for evt in events if evt.get("event_id") == event_id), None)
    if not event_entry:
        return None

    current = event_entry.get("current_step")
    try:
        current_step = int(current)
    except (TypeError, ValueError):
        current_step = None
    if current_step != 3:
        return None

    message = IncomingMessage(
        msg_id=f"step3-refresh::{event_id}",
        from_name=state.event_info.name or event_entry.get("contact_name") or "Client",
        from_email=state.event_info.email or event_entry.get("contact_email"),
        subject=event_entry.get("subject") or "Room availability update",
        body="",
        ts=datetime.utcnow().isoformat() + "Z",
    )
    wf_state = WorkflowState(message=message, db_path=Path(WF_DB_PATH), db=db)
    wf_state.event_entry = event_entry
    wf_state.event_id = event_id
    wf_state.client_id = event_entry.get("client_id") or (state.event_info.email or "").lower()
    wf_state.thread_id = event_entry.get("thread_id") or state.session_id
    wf_state.intent = IntentLabel.EVENT_REQUEST
    wf_state.confidence = 1.0
    wf_state.user_info = dict(event_entry.get("user_info") or {})
    wf_state.context_snapshot = event_entry.get("context_snapshot") or {}
    wf_state.thread_state = event_entry.get("thread_state") or "Awaiting Client"
    wf_state.current_step = 3
    wf_state.caller_step = event_entry.get("caller_step")

    try:
        step3_process(wf_state)
    except Exception as exc:
        print(f"[WF][ERROR] Step-3 workflow failed: {exc}")
        return None

    if wf_state.extras.get("persist"):
        try:
            wf_save_db(db)
        except Exception as exc:
            print(f"[WF][WARN] Step-3 persist failed: {exc}")

    return _normalise_step3_draft(state.session_id, wf_state.draft_messages)


def render_step3_reply(conversation_state: ConversationState, drafts: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """Return the workflow-authored Step-3 reply if available and not yet delivered."""

    cached = _normalise_step3_draft(conversation_state.session_id, drafts)
    if cached:
        return cached
    return _render_step3_from_workflow(conversation_state)


def pop_step3_payload(session_id: Optional[str]) -> Optional[Dict[str, Any]]:
    cache_key = _step3_cache_key(session_id)
    return STEP3_PAYLOAD_CACHE.pop(cache_key, None)


# Load reference data
def load_room_info():
    """Load room information from JSON file"""
    try:
        with (BASE_PATH / "room_info.json").open('r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"rooms": []}


def load_catering_menu():
    """Load catering menu from JSON file"""
    try:
        with (BASE_PATH / "catering_menu.json").open('r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"catering_packages": [], "beverages": {}}

# Load data once at startup
ROOM_INFO = load_room_info()
CATERING_MENU = load_catering_menu()

def get_room_details(room_name: str) -> dict:
    """Get detailed information about a specific room"""
    for room in ROOM_INFO.get("rooms", []):
        if room["name"].lower() == room_name.lower():
            return room
    return {}

def format_room_description(room: dict) -> str:
    """Format room information for natural conversation"""
    if not room:
        return ""
    
    return f"""{room['name']} is perfect for {room['capacity']['min']}-{room['capacity']['max']} people (optimal for {room['capacity']['optimal']}). 
It's {room['size_sqm']}m² and features {', '.join(room['features'][:3])}. 
Great for {', '.join(room['best_for'][:2])}. 
Pricing: CHF {room['full_day_rate']} for a full day."""

def format_catering_options() -> str:
    """Format catering menu for conversation"""
    packages = CATERING_MENU.get("catering_packages", [])
    if not packages:
        return ""
    
    options = []
    for pkg in packages[:3]:  # Show top 3 options
        options.append(f"• {pkg['name']} (CHF {pkg['price_per_person']}/person): {pkg['description']}")
    
    return "\n".join(options)

def format_detailed_catering_info() -> str:
    """Format complete catering menu with all details"""
    packages = CATERING_MENU.get("catering_packages", [])
    
    output = []
    for pkg in packages:
        details = f"""
**{pkg['name']}** - CHF {pkg['price_per_person']} per person
{pkg['description']}
Includes:
{chr(10).join('  • ' + item for item in pkg['includes'])}
"""
        if 'dietary_options' in pkg:
            details += f"\nDietary options: {', '.join(pkg['dietary_options'])}"
        
        if 'main_course_options' in pkg:
            details += f"\nMain course choices:\n"
            details += chr(10).join('  • ' + option for option in pkg['main_course_options'])
        
        output.append(details)
    
    return "\n".join(output)

def get_non_veg_catering_options() -> str:
    """Get catering packages that include non-vegetarian options"""
    packages = CATERING_MENU.get("catering_packages", [])
    
    non_veg_options = []
    for pkg in packages:
        # Lunch and Premium packages have non-veg options
        if pkg['id'] in ['lunch_package', 'premium_lunch', 'apero', 'premium_apero']:
            details = f"""
**{pkg['name']}** - CHF {pkg['price_per_person']} per person
{pkg['description']}

What's included:
{chr(10).join('  • ' + item for item in pkg['includes'])}
"""
            if 'main_course_options' in pkg:
                details += f"\n**Main Course Options (Non-Vegetarian Available):**\n"
                details += chr(10).join('  • ' + option for option in pkg['main_course_options'])
            
            if 'dietary_options' in pkg:
                details += f"\n\n*Dietary accommodations: {', '.join(pkg['dietary_options'])}*"
            
            non_veg_options.append(details)
    
    return "\n\n".join(non_veg_options)

def create_offer_summary(event_info: EventInformation) -> str:
    """Create a detailed offer/quote for the client"""
    
    # Calculate room cost
    room_cost = 0
    room_name = event_info.preferred_room
    for room in ROOM_INFO.get("rooms", []):
        if room["name"] == room_name:
            room_cost = room["full_day_rate"]
            break
    
    # Calculate catering cost
    catering_cost = 0
    participants = 0
    try:
        participants = int(event_info.number_of_participants)
    except (ValueError, TypeError):
        participants = 0
    
    catering_pref = event_info.catering_preference.lower()
    for pkg in CATERING_MENU.get("catering_packages", []):
        if pkg["name"].lower() in catering_pref:
            catering_cost = pkg["price_per_person"] * participants
            break
    
    total_cost = room_cost + catering_cost
    
    return f"""**Event Booking Offer**

**Client:** {event_info.name}
**Company:** {event_info.company}
**Email:** {event_info.email}
**Phone:** {event_info.phone}
**Billing Address:** {event_info.billing_address}

**Event Details:**
- **Date:** {event_info.event_date}
- **Time:** {event_info.start_time} - {event_info.end_time}
- **Type:** {event_info.type_of_event}
- **Participants:** {event_info.number_of_participants}

**Venue:**
- **Room:** {event_info.preferred_room}
- **Cost:** CHF {room_cost}

**Catering:**
- **Package:** {event_info.catering_preference}
- **Cost:** CHF {catering_cost} ({participants} participants)

**Total Cost:** CHF {total_cost}

---

Please review this offer. Reply with "I accept" to confirm, or let me know if you need any changes."""

SYSTEM_PROMPT = f"""You are Shami from Ares Illi's team, an Event Manager at The Atelier event venue in Switzerland. 

CRITICAL CONVERSATION RULES:

1. **When all information is collected:**
   - If client asks for "offer", "quote", "proposal" → Show detailed cost breakdown
   - After showing offer, ask: "Would you like to proceed with this booking?"
   - If client says "I accept", "yes", "confirmed" → Tell them to click the Accept button in UI

2. **When client accepts in chat:**
   - Say: "Perfect! Please click the 'Accept & Save Booking' button below to save this to our system."
   - Mark conversation as complete

3. **When client asks for details about rooms/catering:**
   - Provide COMPLETE, DETAILED information
   - Include all features, pricing, what's included

4. **Never end until:**
   ✓ All info collected
   ✓ Client explicitly accepts or rejects

5. **Keep responses under 200 words** (except when showing menus)

6. **Always respond in ENGLISH**

7. **Sign as:** "Best regards, Shami (from Ares Illi's team)

8. **EMPATHY & TONE RULES (apply to every message, including the first):**
   - Open the first reply with ONE short acknowledgement tied to the client’s latest message (mood). In later turns, keep an appropriate tone but only add an explicit acknowledgement when warranted.
     → Prioritize the client's mood first, then adjust wording to suit the event’s atmosphere.
   - **Tone hierarchy:**  
       1. Mirror the client’s emotional state (calm, stressed, grieving, excited, etc.)  
       2. Modulate with the event’s “color”:  
          • solemn / steady → memorials or remembrance gatherings  
          • warm / celebratory → weddings, birthdays, success events  
          • neutral / professional → corporate or logistical requests  
       3. If moods conflict, lead with the client’s tone, then balance with event appropriateness.
   - Keep responses **concise and grounded** (≈ 120–180 words unless showing menus).  
     Avoid melodrama, repeated condolences, or inappropriate/excessive enthusiasm.
   - **Structure every message:**  
       1. One-sentence acknowledgement → shows empathy.  
       2. Clear, factual next steps → advance the booking flow or answer the question.  
       3. Close politely with “Best regards, Shami (from Ares Illi’s team)”.
"

AVAILABLE ROOMS:
{json.dumps(ROOM_INFO, indent=2)}

AVAILABLE CATERING:
{json.dumps(CATERING_MENU, indent=2)}

Current conversation context will be provided with each message."""


def classify_email(email_body: str) -> str:
    """Classify if email is a new event request or something else"""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": """Classify this email into ONE category:
            - "new_event": Client wants to book venue for a new event
            - "update": Client wants to modify existing booking
            - "follow_up": Client is following up on previous inquiry
            - "other": Anything else (complaint, question, spam, etc.)
            
            Return ONLY the category name, nothing else."""},
            {"role": "user", "content": email_body}
        ],
        temperature=0.3
    )
    return response.choices[0].message.content.strip().lower()

def extract_information_incremental(email_body: str, current_info: EventInformation) -> EventInformation:
    """Extract any new information from the latest email and update existing info"""
    
    # SPECIAL CASE: If the message is ONLY a phone number, extract it directly
    stripped = email_body.strip()
    if stripped.isdigit() and len(stripped) >= 7 and len(stripped) <= 15:
        print(f"✅ Detected standalone phone number: {stripped}")
        current_info.phone = stripped
        return current_info
    
    extraction_prompt = f"""Extract event booking information from this email.

    Current information we already have:
    {json.dumps(current_info.dict(), indent=2)}

    New email from client:
    {email_body}

    Extract ALL information. Return JSON:
    {{
        "event_date": "DD.MM.YYYY or Not specified",
        "name": "First Last or Not specified",
        "email": "exact email or Not specified",
        "phone": "phone number (ANY format, including just digits) or Not specified",
        "company": "company name (extract from email domain or signature) or Not specified",
        "billing_address": "full address or Not specified",
        "start_time": "HH:mm in 24-hour format or Not specified",
        "end_time": "HH:mm in 24-hour format or Not specified",
        "preferred_room": "Room A/B/C or Not specified",
        "number_of_participants": "number or Not specified",
        "type_of_event": "workshop/meeting/birthday/conference/etc or Not specified",
        "catering_preference": "DETAILED catering choice with exact package name or Not specified",
        "language": "en"
    }}

    CRITICAL EXTRACTION RULES:
    - If message is ONLY numbers (like "04258374"), that's a phone number
    - Phone numbers can be in ANY format: 041234567, +41 12 345 67 89, etc.
    - If no specific times mentioned, leave as "Not specified"
    - If email domain is @techcorp.com, extract company as "TechCorp"
    - For catering, include exact package name like "Premium Lunch Package CHF 42/person"
    - Extract event type from context (workshop, birthday party, meeting, etc.)
    - Return valid JSON only"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": extraction_prompt}],
        response_format={"type": "json_object"},
        temperature=0.1
    )
    
    extracted = json.loads(response.choices[0].message.content)
    
    print(f"📥 Extracted data: {extracted}")
    
    # Update fields intelligently
    for key, value in extracted.items():
        if value and value != "Not specified" and value != "none" and hasattr(current_info, key):
            current_value = getattr(current_info, key)
            
            # Special email handling
            if key == "email":
                if "example.com" in str(current_value) or current_value == "Not specified":
                    setattr(current_info, key, value)
                elif value != "Not specified" and "@" in value:
                    setattr(current_info, key, value)
            # For other fields, update if currently "Not specified"
            elif current_value == "Not specified" or current_value is None or current_value == "":
                print(f"  ✅ Updating {key}: '{current_value}' → '{value}'")
                setattr(current_info, key, value)
            else:
                print(f"  ⏭️  Skipping {key}: already has value '{current_value}'")
    
    return current_info

def generate_response(conversation_state: ConversationState, user_message: str) -> str:
    """Generate natural response from Event Manager"""
    
    # Extract any new info from user's message
    conversation_state.event_info = extract_information_incremental(
        user_message, 
        conversation_state.event_info
    )
    
    user_msg_lower = user_message.lower().strip()
    is_first_msg = (len(conversation_state.conversation_history) == 0)  # ← add this

    # Check if user is asking a question (even after all info collected)
    is_question = any(word in user_msg_lower for word in ['?', 'what', 'how', 'why', 'when', 'where', 'can you', 'could you', 'please tell', 'more details', 'explain'])
    
    # Check if user is requesting something
    is_request = any(phrase in user_msg_lower for phrase in ['send me', 'give me', 'show me', 'tell me more', 'provide', 'need to know'])
    
    # Check if user is accepting - BE VERY EXPLICIT
    is_accepting = (
        'yes please confirm' in user_msg_lower or
        'i accept' in user_msg_lower or
        'accept the offer' in user_msg_lower or
        'looks good' in user_msg_lower or
        'confirmed' in user_msg_lower or
        'yes please proceed' in user_msg_lower or
        'lets go ahead' in user_msg_lower or
        'book it' in user_msg_lower or
        'yes confirm' in user_msg_lower or
        'yes please' in user_msg_lower or
        'proceed' in user_msg_lower
    )
    
    print(f"\n=== GENERATE RESPONSE DEBUG ===")
    print(f"User message: '{user_message}'")
    print(f"is_accepting: {is_accepting}")
    print(f"is_question: {is_question}")
    print(f"================================\n")
    
    # Check what's still missing
    missing_fields = conversation_state.event_info.get_missing_fields()
    is_complete = conversation_state.event_info.is_complete()
    
    # If user is asking questions or making requests, ALWAYS respond even if complete
    if (is_question or is_request) and not is_accepting and not is_first_msg:
        # Handle specific questions
        asking_about_catering = any(word in user_msg_lower for word in 
            ['catering', 'food', 'lunch', 'menu', 'non-veg', 'vegetarian', 'eat', 'drink', 'beverage'])
        
        asking_about_rooms = any(word in user_msg_lower for word in 
            ['room', 'space', 'venue', 'facility'])
        
        asking_for_offer = any(phrase in user_msg_lower for phrase in 
            ['offer', 'quote', 'proposal', 'price breakdown', 'total cost', 'pricing', 'how much'])
        
        # Build response context based on question
        if asking_for_offer and is_complete:
            offer = create_offer_summary(conversation_state.event_info)
            conversation_state.conversation_history.append({"role": "user", "content": user_message})
            conversation_state.conversation_history.append({"role": "assistant", "content": offer})
            return offer

        elif asking_about_catering:
            catering_response = generate_catering_response(user_msg_lower)
            catering_response = _ensure_greeting(catering_response)
            conversation_state.conversation_history.append({"role": "user", "content": user_message})
            conversation_state.conversation_history.append({"role": "assistant", "content": catering_response})
            return catering_response


        elif asking_about_rooms:
            room_response = generate_room_response(user_msg_lower, conversation_state.event_info)
            room_response = _ensure_greeting(room_response)
            conversation_state.conversation_history.append({"role": "user", "content": user_message})
            conversation_state.conversation_history.append({"role": "assistant", "content": room_response})
            return room_response

    # If user is accepting AND all info is complete, mark as ready for buttons
    if is_accepting and is_complete:
        # CRITICAL: Set is_complete to True
        conversation_state.is_complete = True
        
        print(f"\n🎯 ACCEPTANCE DETECTED - Setting is_complete = TRUE\n")
        
        # Generate complete offer summary
        offer_summary = create_offer_summary(conversation_state.event_info)
        
        confirmation = f"""{offer_summary}

    **🎉 Your booking is confirmed!**

    **Please click the "Accept & Save Booking" button below to save this event to our system.**

    Thank you for choosing The Atelier!

    Best regards,
    Shami (from Ares Illi's team)"""
        
        conversation_state.conversation_history.append({"role": "user", "content": user_message})
        conversation_state.conversation_history.append({"role": "assistant", "content": confirmation})
        return confirmation
    
    # Build context for regular conversation
    asking_about_catering = any(word in user_msg_lower for word in 
        ['catering', 'food', 'lunch', 'menu', 'non-veg', 'vegetarian', 'eat', 'drink'])
    
    asking_about_rooms = any(word in user_msg_lower for word in 
        ['room', 'space', 'options', 'tell me more'])
    
    room_context = ""
    if asking_about_rooms or conversation_state.event_info.preferred_room == "Not specified":
        if conversation_state.event_info.number_of_participants != "Not specified":
            try:
                num_people = int(conversation_state.event_info.number_of_participants)
                suitable_rooms = []
                for room in ROOM_INFO.get("rooms", []):
                    if room["capacity"]["min"] <= num_people <= room["capacity"]["max"]:
                        suitable_rooms.append(format_room_description(room))
                if suitable_rooms:
                    room_context = f"\n\nSUITABLE ROOMS FOR {num_people} PEOPLE:\n" + "\n".join(suitable_rooms)
            except (ValueError, TypeError, KeyError):
                # Could not determine suitable rooms - continue without room context
                pass
    
    catering_context = ""
    if asking_about_catering:
        if "non-veg" in user_msg_lower or "non veg" in user_msg_lower or "meat" in user_msg_lower:
            catering_context = f"\n\nNON-VEGETARIAN CATERING OPTIONS (show these to client):\n{get_non_veg_catering_options()}"
        else:
            catering_context = f"\n\nCATERING OPTIONS (show relevant ones to client):\n{format_detailed_catering_info()}"
    
    # Check catering status
    catering_status = ""
    if conversation_state.event_info.catering_preference != "Not specified":
        catering_lower = conversation_state.event_info.catering_preference.lower()
        if ("needs clarification" in catering_lower or 
            "non-veg" in catering_lower or
            len(conversation_state.event_info.catering_preference) < 20):
            catering_status = "\n\n⚠️ CATERING NOT SPECIFIC ENOUGH - Must get exact package name and price confirmation"
    
    # Critical missing information
    critical_missing = []
    if conversation_state.event_info.company == "Not specified":
        critical_missing.append("Company name")
    if conversation_state.event_info.billing_address == "Not specified":
        critical_missing.append("Billing address")
    if conversation_state.event_info.phone == "Not specified":
        critical_missing.append("Phone number")
    if conversation_state.event_info.event_date == "Not specified":
        critical_missing.append("Event date")
    if not is_complete:
        catering_pref = conversation_state.event_info.catering_preference
        if ("needs clarification" in catering_pref.lower() or 
            catering_pref == "Not specified" or
            len(catering_pref) < 20):
            critical_missing.append("SPECIFIC catering package (must have exact name like 'Premium Lunch Package CHF 42/person')")
    
    missing_details = ""
    if critical_missing:
        missing_details = f"\n\n⚠️ STILL NEED TO COLLECT:\n" + "\n".join(f"- {item}" for item in critical_missing)
    
    context = f"""
    Latest client message (mirror its tone before detailing logistics):
     {user_message.strip()}
    Current event information collected:
    Event Date: {conversation_state.event_info.event_date}
    Name: {conversation_state.event_info.name}
    Email: {conversation_state.event_info.email}
    Phone: {conversation_state.event_info.phone}
    Company: {conversation_state.event_info.company}
    Billing Address: {conversation_state.event_info.billing_address}
    Start Time: {conversation_state.event_info.start_time}
    End Time: {conversation_state.event_info.end_time}
    Preferred Room: {conversation_state.event_info.preferred_room}
    Number of Participants: {conversation_state.event_info.number_of_participants}
    Type of Event: {conversation_state.event_info.type_of_event}
    Catering Preference: {conversation_state.event_info.catering_preference}
    {catering_status}
    {missing_details}
    {room_context}
    {catering_context}
    
    Is information complete? {is_complete}
    
    CRITICAL INSTRUCTIONS:
    - If client asks about catering/rooms, show FULL details from the data provided above
    - If is_complete = False, DO NOT summarize - continue collecting information
    - If catering shows "needs clarification", ask client to choose specific package
    - Be detailed and helpful when showing options
    - Only mention "accept & save booking button" when client explicitly confirms/accepts
    - If all info complete but client hasn't confirmed, ask: "Would you like to proceed with this booking?"
    """
    
    # Add user message to history
    conversation_state.conversation_history.append({
        "role": "user",
        "content": user_message
    })

    step3_reply = render_step3_reply(conversation_state)
    if step3_reply:
        body_text = step3_reply.get("body_markdown") or step3_reply.get("body") or ""
        body_text = body_text or ""
        conversation_state.conversation_history.append({
            "role": "assistant",
            "content": body_text,
        })
        return body_text
    
    # Generate response
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": context},
    ] + conversation_state.conversation_history
    # updated parameters ( tocheck)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.45,
        max_tokens=500,
        top_p=0.9,
        frequency_penalty=0.2,
        presence_penalty=0.1
    )

    assistant_message = response.choices[0].message.content
    # Add a short, contextual first-turn acknowledgement if missing

    # Always ensure an email-style greeting
    assistant_message = _ensure_greeting(assistant_message)

    # Add to history
    conversation_state.conversation_history.append({
        "role": "assistant",
        "content": assistant_message
    })
    
    # DO NOT mark as complete unless user explicitly accepts
    # (is_complete flag is only for showing buttons)
    
    return assistant_message

def _ensure_greeting(text: str) -> str:
    t = text.lstrip()
    lower = t.lower()
    if lower.startswith(("dear ", "hello", "hi ", "good morning", "good afternoon", "good evening")):
        return text  # already has a greeting
    return f"Hello,\n\n{t}"


def generate_catering_response(user_msg_lower: str) -> str:
    """Generate detailed response about catering based on user query"""
    if "non-veg" in user_msg_lower or "meat" in user_msg_lower:
        return f"""Here are our catering packages with non-vegetarian options:

{get_non_veg_catering_options()}

Which package would you prefer? Let me know if you need more details about any specific option.

Best regards,
Shami (from Ares Illi's team)"""
    else:
        return f"""Here are all our catering packages:

{format_detailed_catering_info()}

Which package interests you? I'm happy to provide more details about any of these options.

Best regards,
Shami (from Ares Illi's team)"""


def generate_room_response(user_msg_lower: str, event_info: EventInformation) -> str:
    """Generate detailed response about rooms based on user query"""
    if event_info.number_of_participants != "Not specified":
        try:
            num_people = int(event_info.number_of_participants)
            suitable_rooms = []
            for room in ROOM_INFO.get("rooms", []):
                if room["capacity"]["min"] <= num_people <= room["capacity"]["max"]:
                    # Format detailed room info
                    room_details = f"""**{room['name']}**
- Capacity: {room['capacity']['min']}-{room['capacity']['max']} people (optimal for {room['capacity']['optimal']})
- Size: {room['size_sqm']}m²
- Features: {', '.join(room['features'])}
- Setup options: {', '.join(room['setup_options'])}
- Equipment: {', '.join(room['equipment'])}
- Best for: {', '.join(room['best_for'])}
- Pricing: CHF {room['full_day_rate']} for a full day"""
                    suitable_rooms.append(room_details)

            if suitable_rooms:
                return f"""For your group of {num_people} people, here are the suitable rooms:

{chr(10).join(suitable_rooms)}

Which room would you prefer?

Best regards,
Shami (from Ares Illi's team)"""
        except (ValueError, TypeError, KeyError):
            # Could not parse participants or room data - fall through to show all rooms
            pass
    
    # If no participant count, show all rooms
    all_rooms = []
    for room in ROOM_INFO.get("rooms", []):
        room_details = f"""**{room['name']}**
- Capacity: {room['capacity']['min']}-{room['capacity']['max']} people
- Pricing: CHF {room['full_day_rate']} for a full day"""
        all_rooms.append(room_details)
    
    return f"""Here are our available rooms:

{chr(10).join(all_rooms)}

Let me know how many participants you're expecting, and I can recommend the best option!

Best regards,
Shami (from Ares Illi's team)"""

def create_summary(event_info: EventInformation) -> str:
    """Create a summary of collected information for final confirmation"""
    
    # Calculate costs
    room_cost = 0
    room_name = event_info.preferred_room
    for room in ROOM_INFO.get("rooms", []):
        if room["name"] == room_name:
            room_cost = room["full_day_rate"]
            break
    
    catering_cost = 0
    participants = 0
    try:
        participants = int(event_info.number_of_participants)
    except (ValueError, TypeError):
        participants = 0
    
    catering_pref = event_info.catering_preference.lower()
    for pkg in CATERING_MENU.get("catering_packages", []):
        if pkg["name"].lower() in catering_pref:
            catering_cost = pkg["price_per_person"] * participants
            break
    
    total_cost = room_cost + catering_cost
    
    return f"""Perfect! I have collected all the important information. Here's the complete summary:

    **Event Details:**
    - **Date:** {event_info.event_date}
    - **Time:** {event_info.start_time} - {event_info.end_time}
    - **Type:** {event_info.type_of_event}
    - **Participants:** {event_info.number_of_participants}

    **Client Information:**
    - **Name:** {event_info.name}
    - **Email:** {event_info.email}
    - **Phone:** {event_info.phone}
    - **Company:** {event_info.company if event_info.company != "Not specified" else "N/A"}
    - **Billing Address:** {event_info.billing_address}

    **Venue:**
    - **Room:** {event_info.preferred_room}
    - **Cost:** CHF {room_cost}

    **Catering:**
    - **Package:** {event_info.catering_preference}
    - **Cost:** CHF {catering_cost} ({participants} participants × CHF {catering_cost/participants if participants > 0 else 0})

    ---

    **Total Cost:** CHF {total_cost}

    ---

    Would you like to proceed with this booking?

    Best regards,
    Shami (from Ares Illi's team)"""
