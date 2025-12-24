# OpenEvent AI Architecture Diagrams

> **Note:** These diagrams are generated using Mermaid.js. They reflect the current architecture as of December 2025.
> Consult `docs/DEPENDENCY_GRAPH.md` for detailed file mapping.

## 1. System Context & High-Level Architecture

This diagram shows how the system interacts with the user and external components.

```mermaid
graph TB
    Client((Client)) -->|Chat| Frontend[Frontend Next.js]
    Manager((Manager)) -->|Approve/View| Frontend

    Frontend <-->|REST API| Backend[Backend FastAPI]
    
    subgraph Backend Services
        Backend --> Orchestrator[Workflow Engine]
        Orchestrator -->|Read/Write| DB[(JSON Database)]
        Orchestrator -->|Draft/Classify| LLM_Adapter[LLM Adapter]
        Orchestrator -->|Check| Calendar[Calendar Adapter]
        
        LLM_Adapter <-->|API| OpenAI(OpenAI / LLM Provider)
    end
```

## 2. Workflow State Machine (Steps 1-7)

The core of the application is a linear state machine with "detour" capabilities.

```mermaid
stateDiagram-v2
    [*] --> Step1_Intake
    
    state "Step 1: Intake" as Step1_Intake {
        [*] --> Classify
        Classify --> Extract
        Extract --> CreateEvent
    }

    Step1_Intake --> Step2_Date : Intent=EventRequest
    Step1_Intake --> Step3_Room : Shortcut (Date+Pax present)
    
    state "Step 2: Date Confirmation" as Step2_Date {
        [*] --> ProposeDates
        ProposeDates --> WaitDateConfirmation
        WaitDateConfirmation --> ValidateDate
    }
    
    Step2_Date --> Step3_Room : Date Confirmed
    Step2_Date --> Step2_Date : Invalid/Vague Date

    state "Step 3: Room Availability" as Step3_Room {
        [*] --> CheckInventory
        CheckInventory --> PresentOptions
        PresentOptions --> WaitRoomSelection
    }

    Step3_Room --> Step4_Offer : Room Selected
    Step3_Room --> Step2_Date : Change Date (Detour)
    
    state "Step 4: Offer" as Step4_Offer {
        [*] --> CalculatePrice
        CalculatePrice --> DraftOffer
        DraftOffer --> WaitHIL : HIL Approval
        WaitHIL --> SendOffer
    }

    Step4_Offer --> Step5_Negotiation : Offer Sent
    Step4_Offer --> Step2_Date : Change Date (Detour)
    Step4_Offer --> Step3_Room : Change Room (Detour)

    state "Step 5: Negotiation" as Step5_Negotiation {
        [*] --> WaitClientReply
        WaitClientReply --> AnalyzeIntent
        AnalyzeIntent --> HandleCounter
        AnalyzeIntent --> HandleAccept
    }

    Step5_Negotiation --> Step7_Confirmation : Accepted
    Step5_Negotiation --> Step4_Offer : Change Products (Detour)
    Step5_Negotiation --> Step3_Room : Change Room (Detour)
    Step5_Negotiation --> Step2_Date : Change Date (Detour)

    state "Step 7: Confirmation" as Step7_Confirmation {
        [*] --> CheckDeposits
        CheckDeposits --> SiteVisitFlow
        SiteVisitFlow --> FinalizeBooking
    }

    Step7_Confirmation --> [*] : Booking Confirmed
```

## 3. Workflow Routing Logic

How the system decides which code module processes an incoming message.

```mermaid
flowchart TD
    Msg[Incoming Message] --> LoadState[Load Event State]
    LoadState --> SpecialFlow{Special Flow?}
    
    SpecialFlow -->|Yes: Billing/Deposit| Bypass[Bypass Detection]
    Bypass --> StepHandler
    
    SpecialFlow -->|No| DetectDup{Duplicate?}
    DetectDup -->|Yes| Halt[Halt: Duplicate]
    
    DetectDup -->|No| Classify[Intent Classification]
    Classify --> Extract[Entity Extraction]
    
    Extract --> Change{Change Detected?}
    Change -->|Yes: Date| Detour2[Set Step = 2]
    Change -->|Yes: Room| Detour3[Set Step = 3]
    Change -->|No| CurrentStep[Use Current Step]
    
    Detour2 --> StepHandler[Execute Step Handler]
    Detour3 --> StepHandler
    CurrentStep --> StepHandler
    
    StepHandler --> Result{Result Action}
    Result -->|Draft| HIL[Enqueue HIL Task]
    Result -->|Direct| DB[Update DB & Reply]
```

## 4. Detection Logic (Inside a Stage)

Inside each stage (e.g., Intake, Date Confirmation), a multi-layered approach is used to understand the user's intent.

```mermaid
flowchart LR
    Input[User Text] --> Layer1[Layer 1: Regex/Keywords]
    Layer1 -->|Match?| FastTrack[Fast Track Result]
    
    Layer1 -->|No Match| Layer2[Layer 2: LLM Classifier]
    Layer2 -->|Intent| Layer3[Layer 3: Entity Extraction]
    
    Layer3 -->|Regex Date| Dates
    Layer3 -->|NER| Names/Orgs
    Layer3 -->|LLM| ComplexReqs
    
    Dates --> Merge[Merge Context]
    Names/Orgs --> Merge
    ComplexReqs --> Merge
    
    Merge --> Validation{Safety Sandwich}
    Validation -->|Pass| Output[Validated Structured Data]
    Validation -->|Fail| Retry[Retry / Fallback]
```

## 5. Detailed Stage Definitions

| Step | Name | Description | Key Actions |
| :--- | :--- | :--- | :--- |
| **1** | **Intake** | Initial contact and requirement gathering. | Extract Event Type, Pax, Date preference. Create Event record. |
| **2** | **Date Confirmation** | Nail down the exact date/time. | Handle "Next Friday", specific dates. Check Calendar. |
| **3** | **Room Availability** | Select specific rooms. | Present options based on Pax/Layout. Handle "Room A vs Room B". |
| **4** | **Offer Review** | Present formal offer/quote. | Generate pricing. Handle "Send me the quote". |
| **5** | **Negotiation** | Refine terms. | Handle price objections, menu changes. |
| **6** | **Transition** | Pre-booking checks (Merged into 5/7). | Verify all details before final confirmation. |
| **7** | **Confirmation** | Final booking. | Send confirmation email. Close lead. |
