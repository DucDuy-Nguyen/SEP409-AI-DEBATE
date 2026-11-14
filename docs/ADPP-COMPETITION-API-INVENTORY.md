# ADPP – FULL BACKEND API INVENTORY & COMPETITION WORKFLOW MAPPING

**Document:** Complete System API Catalog & Workflow Mapping  
**Solution Root:** `d:\FA26_CapstoneProject\SEP409-AI-DEBATE`  
**Artifact Path:** `C:\Users\ACER\.gemini\antigravity\brain\309f68c6-ab5f-46a3-b613-d1a810922a1a\docs\ADPP-COMPETITION-API-INVENTORY.md`  
**Workspace Path:** `d:\FA26_CapstoneProject\SEP409-AI-DEBATE\docs\ADPP-COMPETITION-API-INVENTORY.md`  
**Audit Mode:** READ-ONLY Architectural Audit  

---

## 1. Executive Summary

This report delivers a complete, read-only architectural audit of the entire backend of the **AI Debate Practice Platform (ADPP)**. The backend is an ASP.NET Core 8 Web API built on a layered architecture (Controller → Service → Repository / Unit of Work → EF Core SystemDbContext → SQL Server).

### Key Audit Findings
1. **Total Backend Endpoints Scanned:** Exactly **98 public HTTP endpoints** across 17 controllers in 4 distinct modules:
   - **Competition Module:** 37 endpoints across 6 controllers.
   - **Debate Module:** 31 endpoints across 3 controllers.
   - **Identity & Administration Module:** 19 endpoints across 3 controllers.
   - **Payment & Rewards Module:** 11 endpoints across 5 controllers.
2. **Alignment with Newly Agreed Business Flow (Organizer as Sole Judge):**
   - The agreed flow states that the **Competition Organizer is the ONLY Judge** and no per-match `AssignJudge` is required.
   - **Architectural Gap:** Current code in `FinalizeMatchAsync` strictly enforces `if (match.AssignedJudgeUserId != actorId) return 403 Forbidden`. Because `AssignedJudgeUserId` defaults to `null` on new match records, if the Organizer does not call `PUT matches/{matchId}/judge`, they are locked out of finalizing matches. 
   - **Fix Required:** Default `AssignedJudgeUserId = competition.CreatedBy` upon match creation or authorize `competition.CreatedBy == actorId` in `FinalizeMatchAsync`, and mark `AssignJudge` as `NOT REQUIRED`.
3. **P0 Validation Bug in TEAM 2v2 Start (BE-01):**
   - In `CompetitionService.cs` line 508, `active.Count * 2 != entrantCount` compares total team members ($2N$) against total bracket slots ($N$). For any valid team bracket, this always returns false, throwing a 409 Conflict.
4. **AI Override Reason Enforcement Bug (BE-03):**
   - In `CompetitionTournamentService.cs` line 258, `FinalizeMatchAsync` only demands `DecisionReason` when total judge criteria scores tie or invert. It fails to compare the judge's selected winner with `AIJudgement.SuggestedWinnerSide`. If a judge scores their chosen side higher, they can override AI's recommended winner with an empty reason.
5. **No SignalR / DebateHub:**
   - Real-time debate is handled exclusively via authenticated REST API endpoints in `DebateController.cs` with database transaction locks and strict turn validation for 1v1 and 2v2.
6. **Round Progression Architecture:**
   - Current code generates the full binary elimination tree (`Rounds` 1..N and all `Matches`) up-front during `GenerateBracketAsync`. Round 1 BYEs are auto-advanced immediately. Subsequent round matches are transitioned to `"Ready"` and activated to `"Ongoing"` automatically as winners are confirmed in `FinalizeMatchAsync`. No manual click is required for subsequent rounds.

---

## 2. Backend Architecture & Module Overview

```
                                  ┌───────────────────────────────┐
                                  │      Client Applications      │
                                  │   (React SPA / Mobile App)    │
                                  └───────────────┬───────────────┘
                                                  │ HTTP / REST
                                                  ▼
                                  ┌───────────────────────────────┐
                                  │     YARP Gateway (Port 5000)   │
                                  │    Reverse Proxy & Routing    │
                                  └───────────────┬───────────────┘
                                                  │
            ┌─────────────────────────────────────┼─────────────────────────────────────┐
            │ /api/competitions, /api/debate,     │ /api/evaluate/*                     │ /api/opponent/*
            │ /api/auth, /api/users, /api/admin   │                                     │
            ▼                                     ▼                                     ▼
┌──────────────────────────────┐       ┌──────────────────────────────┐       ┌──────────────────────────────┐
│  SystemService (Port 5001)   │       │  ai-evaluator-service        │       │  ai-opponent-service         │
│  ASP.NET Core 8 Web API      │──────▶│  Azure Container Apps        │       │  FastAPI (Port 8002)         │
│  - Identity & Auth (JWT)     │       │  (NLP / Turn Evaluation)     │       │  (AI Debate Opponent)        │
│  - Competition Management    │       └──────────────────────────────┘       └──────────────────────────────┘
│  - Tournament & Bracket      │
│  - Debate Engine & History   │
│  - Payment & Wallets         │
└──────────────┬───────────────┘
               │ EF Core (SystemDbContext)
               ▼
┌──────────────────────────────┐
│    SQL Server 2022 Database  │
│  - Competitions / Matches    │
│  - DebateSessions / Turns    │
│  - Users / Roles / Wallets   │
└──────────────────────────────┘
```

### Dependency Injection Pipeline (`SystemService/Program.cs`)
- **Controllers:** `builder.Services.AddControllers()`.
- **Database:** `SystemDbContext` (SQL Server connection string `DefaultConnection`).
- **Distributed Cache:** Redis if configured; otherwise `AddDistributedMemoryCache()`.
- **Singletons:** `DebateEvaluationCoordinator` (orchestrates background AI evaluations, prevents duplicate concurrent AI evaluations for the same session).
- **HTTP Clients:**
  - `IAiEvaluatorClient` → `AiEvaluatorClient` (Azure Container App URL, 120s timeout).
  - `IAiOpponentClient` → `AiOpponentClient` (Port 8002, 120s timeout).
- **Hosted Services:** `StartupWarmupService` (warms up EF Core queries and verifies AI Evaluator `/health/ready`).
- **Authentication:** JWT Bearer tokens with `ClockSkew = TimeSpan.Zero`.
- **Error Middleware:** `ExceptionMiddleware` intercepts unhandled exceptions, logs them, and returns standardized `ApiResponse<T>` error structures.

---

## 3. Complete Backend API Inventory (All 98 Endpoints)

Below is the comprehensive catalog of all 98 HTTP endpoints currently compiled into the backend.

### 3.1. Competition Module (37 Endpoints)

#### A. Competitions Controller (`CompetitionsController.cs`)
Base Route: `api/competitions` | Controller Auth: Mixed

| # | Method | Full Route | Action | Purpose / Business Flow | Request DTO | Response DTO | Auth | Service & Database Operation | Stage | Existing Test |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | POST | `/api/competitions` | `Create` | Create a new competition draft | `CreateCompetitionRequest` | `ApiResponse<CompetitionResponse>` | `[Authorize]` (Admin/Lecturer) | `ICompetitionService.CreateAsync` → Inserts `Competitions` & `CompetitionJudges` | Stage 1 | Integration test covered |
| 2 | GET | `/api/competitions` | `GetList` | List public competitions with filtering & pagination | `[FromQuery] CompetitionQueryRequest` | `ApiResponse<PagedList<CompetitionListItemResponse>>` | Anonymous | `ICompetitionService.GetListAsync` → Queries `Competitions` | Discovery | Integration test covered |
| 3 | GET | `/api/competitions/{id}` | `GetById` | Retrieve detailed competition information | None (Route `id`) | `ApiResponse<CompetitionDetailResponse>` | Anonymous | `ICompetitionService.GetByIdAsync` → Queries `Competitions`, `Rounds`, `Teams` | Discovery / All | Integration test covered |
| 4 | PATCH | `/api/competitions/{id}` | `Patch` | Update competition configuration while in Draft | `PatchCompetitionRequest` | `ApiResponse<CompetitionResponse>` | `[Authorize]` (Creator only) | `ICompetitionService.PatchAsync` → Updates `Competitions` | Stage 1 | Integration test covered |
| 5 | POST | `/api/competitions/{id}/open-registration` | `OpenRegistration` | Transition competition status from Draft to OpenRegistration | None | `ApiResponse<object>` | `[Authorize]` (Creator only) | `ICompetitionService.OpenRegistrationAsync` → Updates `Competitions.Status` | Stage 2 | Integration test covered |
| 6 | POST | `/api/competitions/{id}/close-registration` | `CloseRegistration` | Manually close registration window | None | `ApiResponse<object>` | `[Authorize]` (Creator only) | `ICompetitionService.CloseRegistrationAsync` → Updates `Competitions.Status` | Stage 3 | Integration test covered |
| 7 | POST | `/api/competitions/{id}/start` | `Start` | Start competition (sets status to Ongoing and first-round matches to Ready) | None | `ApiResponse<object>` | `[Authorize]` (Creator only) | `ICompetitionService.StartCompetitionAsync` → Validates bracket, sets `Competitions.Status='Ongoing'` | Stage 4 | Integration test covered (Failed on 2v2 due to BE-01) |
| 8 | POST | `/api/competitions/{id}/complete` | `Complete` | Manually mark competition as completed | None | `ApiResponse<object>` | `[Authorize]` (Creator only) | `ICompetitionService.CompleteCompetitionAsync` → Rejects unless official champion exists | Stage 10 | Integration test covered |
| 9 | POST | `/api/competitions/{id}/cancel` | `Cancel` | Cancel competition from Draft, OpenRegistration, or RegistrationClosed | None | `ApiResponse<object>` | `[Authorize]` (Creator only) | `ICompetitionService.CancelCompetitionAsync` → Updates `Competitions.Status='Cancelled'` | Cancellation | Integration test covered |
| 10 | POST | `/api/competitions/matches/{matchId}/prepare-debate` | `PrepareMatchDebate` | Create linked DebateSession with 3 rounds and fixed PRO/CON sides | `PrepareMatchDebateRequest` | `ApiResponse<DebateSessionResponse>` | `[Authorize]` (Creator / Judge) | `ICompetitionDebateBridgeService.PrepareMatchDebateAsync` → Creates `DebateSession`, updates `CompetitionMatches.DebateSessionId` | Stage 5 | Integration test covered |

#### B. Competition Tournament Controller (`CompetitionTournamentController.cs`)
Base Route: `api/competitions/{competitionId:int}` | Controller Auth: Mixed

| # | Method | Full Route | Action | Purpose / Business Flow | Request DTO | Response DTO | Auth | Service & Database Operation | Stage | Existing Test |
|---|---|---|---|---|---|---|---|---|---|---|
| 11 | GET | `/api/competitions/{competitionId}/bracket` | `GetBracket` | Get the entire bracket structure, rounds, matches, and champion | None | `ApiResponse<BracketResponse>` | Anonymous | `ICompetitionTournamentService.GetBracketAsync` → Queries `CompetitionRounds`, `Matches`, `Participants` | Stage 4, 9, 10 | Integration test covered |
| 12 | POST | `/api/competitions/{competitionId}/bracket` | `GenerateBracket` | Generate single-elimination tournament bracket and handle BYEs | None | `ApiResponse<BracketResponse>` | `[Authorize]` (Creator only) | `ICompetitionTournamentService.GenerateBracketAsync` → Inserts `Rounds`, `Matches`, `Participants` (Serializable tx) | Stage 4 | Integration test covered |
| 13 | PUT | `/api/competitions/{competitionId}/matches/{matchId}/judge` | `AssignJudge` | Assign judge to match and auto-add to competition judges | `AssignJudgeRequest` | `ApiResponse<object>` | `[Authorize]` (Creator only) | `ICompetitionTournamentService.AssignJudgeAsync` → Updates `CompetitionMatches.AssignedJudgeUserId` | Legacy / NOT REQUIRED | Integration test covered |
| 14 | GET | `/api/competitions/{competitionId}/matches/{matchId}/review` | `GetReview` | Get official match review data, AI scores, and criteria | None | `ApiResponse<MatchReviewResponse>` | `[Authorize]` (Creator / Assigned Judge) | `ICompetitionTournamentService.GetReviewAsync` → Queries `AIJudgements`, `DebateCriteria`, `MatchParticipants` | Stage 8 | Integration test covered |
| 15 | POST | `/api/competitions/{competitionId}/matches/{matchId}/finalize` | `Finalize` | Submit official criteria scores, confirm winner, advance to next match | `FinalizeMatchRequest` | `ApiResponse<object>` | `[Authorize]` (Assigned Judge only) | `ICompetitionTournamentService.FinalizeMatchAsync` → Inserts `JudgeScores`, advances winner to `NextMatchId` | Stage 8, 9, 10 | Integration test covered |

#### C. Competition Registrations Controller (`CompetitionRegistrationsController.cs`)
Base Route: `api/competitions/{id}/registrations` | Controller Auth: Mixed

| # | Method | Full Route | Action | Purpose / Business Flow | Request DTO | Response DTO | Auth | Service & Database Operation | Stage | Existing Test |
|---|---|---|---|---|---|---|---|---|---|---|
| 16 | POST | `/api/competitions/{id}/registrations` | `Register` | User registers individually for an INDIVIDUAL competition | None | `ApiResponse<CompetitionRegistrationResponse>` | `[Authorize]` | `ICompetitionRegistrationService.RegisterAsync` → Inserts `CompetitionRegistrations` (Status='Pending') | Stage 2 | Integration test covered |
| 17 | GET | `/api/competitions/{id}/registrations` | `GetList` | List registrations filtered by status | `[FromQuery] string? status` | `ApiResponse<List<CompetitionRegistrationResponse>>` | Anonymous | `ICompetitionRegistrationService.GetListAsync` → Queries `CompetitionRegistrations` | Stage 2 | Integration test covered |
| 18 | GET | `/api/competitions/{id}/registrations/{registrationId}` | `GetById` | Get single registration detail | None | `ApiResponse<CompetitionRegistrationResponse>` | Anonymous | `ICompetitionRegistrationService.GetByIdAsync` → Queries `CompetitionRegistrations` | Stage 2 | Unit test covered |
| 19 | PUT | `/api/competitions/{id}/registrations/{registrationId}/approve` | `Approve` | Organizer approves an individual registration | None | `ApiResponse<CompetitionRegistrationResponse>` | `[Authorize]` (Creator only) | `ICompetitionRegistrationService.ApproveAsync` → Sets status to 'Approved' | Stage 2 | Integration test covered |
| 20 | PUT | `/api/competitions/{id}/registrations/{registrationId}/reject` | `Reject` | Organizer rejects an individual registration with reason | `RejectRegistrationRequest` | `ApiResponse<CompetitionRegistrationResponse>` | `[Authorize]` (Creator only) | `ICompetitionRegistrationService.RejectAsync` → Sets status to 'Rejected' | Stage 2 | Integration test covered |
| 21 | DELETE | `/api/competitions/{id}/registrations/me` | `CancelMyRegistration` | User cancels their own registration | `CancelRegistrationRequest` | `ApiResponse<object>` | `[Authorize]` | `ICompetitionRegistrationService.CancelMyRegistrationAsync` → Sets status to 'Cancelled' | Stage 2 | Integration test covered |
| 22 | PUT | `/api/competitions/{id}/registrations/{registrationId}/status` | `RemoveParticipant` | Organizer removes an approved participant before start | `UpdateRegistrationStatusRequest` | `ApiResponse<CompetitionRegistrationResponse>` | `[Authorize]` (Creator only) | `ICompetitionRegistrationService.RemoveParticipantAsync` → Sets status to 'Cancelled' | Stage 2 | Integration test covered |

#### D. Competition Teams Controller (`CompetitionTeamsController.cs`)
Base Route: `api/competitions/{id}/teams` | Controller Auth: Mixed

| # | Method | Full Route | Action | Purpose / Business Flow | Request DTO | Response DTO | Auth | Service & Database Operation | Stage | Existing Test |
|---|---|---|---|---|---|---|---|---|---|---|
| 23 | POST | `/api/competitions/{id}/teams` | `CreateTeam` | Captain creates team for TEAM 2v2 competition | `CreateCompetitionTeamRequest` | `ApiResponse<CompetitionTeamResponse>` | `[Authorize]` | `ICompetitionTeamService.CreateTeamAsync` → Inserts `CompetitionTeams` (Status='Pending') | Stage 2 | Integration test covered |
| 24 | GET | `/api/competitions/{id}/teams` | `GetList` | List all teams in competition | None | `ApiResponse<List<CompetitionTeamResponse>>` | Anonymous | `ICompetitionTeamService.GetListAsync` → Queries `CompetitionTeams` | Stage 2 | Integration test covered |
| 25 | GET | `/api/competitions/{id}/teams/{teamId}` | `GetById` | Get team details and member list | None | `ApiResponse<CompetitionTeamDetailResponse>` | Anonymous | `ICompetitionTeamService.GetByIdAsync` → Queries `CompetitionTeams` with members | Stage 2 | Integration test covered |
| 26 | DELETE | `/api/competitions/{id}/teams/{teamId}/members/me` | `LeaveTeam` | Non-captain member leaves team | None | `ApiResponse<object>` | `[Authorize]` | `ICompetitionTeamService.LeaveTeamAsync` → Removes from `CompetitionTeamMembers` | Stage 2 | Integration test covered |
| 27 | DELETE | `/api/competitions/{id}/teams/{teamId}/members/{userId}` | `RemoveMember` | Captain removes a member from team | None | `ApiResponse<object>` | `[Authorize]` (Captain only) | `ICompetitionTeamService.RemoveMemberAsync` → Removes from `CompetitionTeamMembers` | Stage 2 | Integration test covered |
| 28 | POST | `/api/competitions/{id}/teams/{teamId}/withdraw` | `WithdrawTeam` | Captain withdraws the entire team | None | `ApiResponse<object>` | `[Authorize]` (Captain only) | `ICompetitionTeamService.WithdrawTeamAsync` → Sets `CompetitionTeams.Status='Withdrawn'` | Stage 2 | Integration test covered |

#### E. Competition Team Requests Controller (`CompetitionTeamRequestsController.cs`)
Base Route: `api/competitions/{id}` | Controller Auth: `[Authorize]`

| # | Method | Full Route | Action | Purpose / Business Flow | Request DTO | Response DTO | Auth | Service & Database Operation | Stage | Existing Test |
|---|---|---|---|---|---|---|---|---|---|---|
| 29 | POST | `/api/competitions/{id}/teams/{teamId}/invitations` | `SendInvitation` | Captain invites a user to complete the 2v2 team | `SendTeamInvitationRequest` | `ApiResponse<CompetitionTeamRequestResponse>` | `[Authorize]` (Captain only) | `ICompetitionTeamRequestService.SendInvitationAsync` → Inserts `CompetitionTeamRequests` (Type='Invitation') | Stage 2 | Integration test covered |
| 30 | GET | `/api/competitions/{id}/teams/invitations/me` | `GetMyInvitations` | User views pending invitations sent to them | None | `ApiResponse<List<CompetitionTeamRequestResponse>>` | `[Authorize]` | `ICompetitionTeamRequestService.GetMyInvitationsAsync` → Queries `CompetitionTeamRequests` | Stage 2 | Integration test covered |
| 31 | POST | `/api/competitions/{id}/teams/invitations/{requestId}/accept` | `AcceptInvitation` | User accepts invitation to join 2v2 team | None | `ApiResponse<object>` | `[Authorize]` (Invited user) | `ICompetitionTeamRequestService.AcceptInvitationAsync` → Adds member, transitions team to 'Active' | Stage 2 | Integration test covered |
| 32 | POST | `/api/competitions/{id}/teams/invitations/{requestId}/reject` | `RejectInvitation` | User rejects invitation to join team | `RejectTeamRequestDto` | `ApiResponse<object>` | `[Authorize]` (Invited user) | `ICompetitionTeamRequestService.RejectInvitationAsync` → Updates request to 'Rejected' | Stage 2 | Integration test covered |
| 33 | POST | `/api/competitions/{id}/teams/{teamId}/join-requests` | `CreateJoinRequest` | User requests to join an existing team | None | `ApiResponse<CompetitionTeamRequestResponse>` | `[Authorize]` | `ICompetitionTeamRequestService.CreateJoinRequestAsync` → Inserts `CompetitionTeamRequests` (Type='JoinRequest') | Stage 2 | Integration test covered |
| 34 | GET | `/api/competitions/{id}/teams/{teamId}/join-requests` | `GetTeamJoinRequests` | Captain views pending join requests | None | `ApiResponse<List<CompetitionTeamRequestResponse>>` | `[Authorize]` (Captain only) | `ICompetitionTeamRequestService.GetTeamJoinRequestsAsync` → Queries `CompetitionTeamRequests` | Stage 2 | Integration test covered |
| 35 | POST | `/api/competitions/{id}/teams/{teamId}/join-requests/{requestId}/approve` | `ApproveJoinRequest` | Captain approves join request | None | `ApiResponse<object>` | `[Authorize]` (Captain only) | `ICompetitionTeamRequestService.ApproveJoinRequestAsync` → Adds member, transitions team to 'Active' | Stage 2 | Integration test covered |
| 36 | POST | `/api/competitions/{id}/teams/{teamId}/join-requests/{requestId}/reject` | `RejectJoinRequest` | Captain rejects join request | `RejectTeamRequestDto` | `ApiResponse<object>` | `[Authorize]` (Captain only) | `ICompetitionTeamRequestService.RejectJoinRequestAsync` → Updates request to 'Rejected' | Stage 2 | Integration test covered |

#### F. Competition Judges Controller (`CompetitionJudgesController.cs`)
Base Route: `api/competitions/{id}/judges` | Controller Auth: Anonymous

| # | Method | Full Route | Action | Purpose / Business Flow | Request DTO | Response DTO | Auth | Service & Database Operation | Stage | Existing Test |
|---|---|---|---|---|---|---|---|---|---|---|
| 37 | GET | `/api/competitions/{id}/judges` | `GetList` | List judges assigned to the competition | None | `ApiResponse<List<CompetitionJudgeResponse>>` | Anonymous | `ICompetitionJudgeService.GetListAsync` → Queries `CompetitionJudges` | Discovery / Stage 5 | Integration test covered |

---

### 3.2. Debate Module (31 Endpoints)

#### A. Debate Controller (`DebateController.cs`)
Base Route: `api/debate` | Controller Auth: `[Authorize]`

| # | Method | Full Route | Action | Purpose / Business Flow | Request DTO | Response DTO | Auth | Service & Database Operation | Stage | Existing Test |
|---|---|---|---|---|---|---|---|---|---|---|
| 38 | POST | `/api/debate/ai-practice` | `CreateAiPracticeSession` | Create 1v1 practice session vs AI Opponent | `CreateAiPracticeSessionRequest` | `ApiResponse<DebateSessionResponse>` | `[Authorize]` | `IDebateService.CreateAiPracticeSessionAsync` → Creates `DebateSession` with AI participant | Standalone | Unit & Integration covered |
| 39 | POST | `/api/debate/p2p` | `CreateP2pSession` | Create standalone 1v1 peer-to-peer room | `CreateP2pSessionRequest` | `ApiResponse<DebateSessionResponse>` | `[Authorize]` | `IDebateService.CreateP2pSessionAsync` → Creates `DebateSession` in Waiting state | Standalone | Unit & Integration covered |
| 40 | POST | `/api/debate/{sessionId}/join` | `JoinP2pSession` | Opponent joins standalone 1v1 debate | None | `ApiResponse<DebateSessionResponse>` | `[Authorize]` | `IDebateService.JoinP2pSessionAsync` → Adds second participant, sets status to Ready | Standalone | Unit & Integration covered |
| 41 | POST | `/api/debate/2v2` | `Create2v2Session` | Create standalone 2v2 debate room | `Create2v2SessionRequest` | `ApiResponse<DebateSessionResponse>` | `[Authorize]` | `IDebateService.Create2v2SessionAsync` → Creates 2v2 `DebateSession` | Standalone | Unit & Integration covered |
| 42 | POST | `/api/debate/{sessionId}/join-2v2` | `Join2v2Session` | User joins standalone 2v2 debate room | `Join2v2SessionRequest` | `ApiResponse<DebateSessionResponse>` | `[Authorize]` | `IDebateService.Join2v2SessionAsync` → Adds up to 4 participants | Standalone | Unit & Integration covered |
| 43 | GET | `/api/debate/{sessionId}` | `GetSessionDetails` | Get debate room details, current round, turn, participants | None | `ApiResponse<DebateSessionResponse>` | `[Authorize]` | `IDebateService.GetSessionDetailsAsync` → Queries `DebateSession` details | Stage 6 | Integration test covered |
| 44 | POST | `/api/debate/{sessionId}/arguments` | `SubmitArgument` | Submit debate speech/turn argument (1v1 or 2v2) | `SubmitArgumentRequest` | `ApiResponse<DebateSessionResponse>` | `[Authorize]` (Turn holder) | `IDebateService.SubmitArgumentAsync` → Inserts `DebateArgument`, triggers auto AI background eval if final turn | Stage 6 | Integration test covered |
| 45 | POST | `/api/debate/{sessionId}/ai-arguments` | `SubmitAiArgument` | Trigger AI Opponent response turn in AI debate | `SubmitAiArgumentRequest` | `ApiResponse<SubmitAiArgumentResponse>` | `[Authorize]` | `IDebateService.SubmitAiArgumentAsync` → Calls AI opponent, inserts `DebateArgument` | Standalone | Integration test covered |
| 46 | GET | `/api/debate/{sessionId}/transcript` | `GetTranscript` | Retrieve complete speech transcript with word counts | None | `ApiResponse<DebateTranscriptResponse>` | `[Authorize]` | `IDebateService.GetTranscriptAsync` → Queries rounds and arguments | Stage 6, 8 | Integration test covered |
| 47 | GET | `/api/debate/my-history` | `GetUserHistory` | View user's past debates and performance | None | `ApiResponse<List<DebateHistoryResponse>>` | `[Authorize]` | `IDebateService.GetUserHistoryAsync` → Queries completed sessions for current user | History | Unit test covered |
| 48 | POST | `/api/debate/{sessionId}/switch-side` | `SwitchSide` | Switch PRO/CON side in standalone waiting room | None | `ApiResponse<DebateSessionResponse>` | `[Authorize]` | `IDebateService.SwitchSideAsync` → Swaps side if slot free | Standalone | Unit test covered |
| 49 | POST | `/api/debate/{sessionId}/swap-request` | `SendSwapSideRequest` | Request side swap with opponent in waiting room | `SwapSideRequestDto` | `ApiResponse<bool>` | `[Authorize]` | `IDebateService.SendSwapSideRequestAsync` → Inserts swap request | Standalone | Unit test covered |
| 50 | POST | `/api/debate/{sessionId}/swap-response` | `RespondSwapSideRequest` | Accept or decline side swap request | `SwapSideResponseDto` | `ApiResponse<bool>` | `[Authorize]` | `IDebateService.RespondSwapSideRequestAsync` → Updates swap and swaps sides | Standalone | Unit test covered |
| 51 | GET | `/api/debate/{sessionId}/swap-requests` | `GetPendingSwapRequests` | View pending side swap requests | None | `ApiResponse<List<SwapSideRequestResponseDto>>` | `[Authorize]` | `IDebateService.GetPendingSwapRequestsAsync` → Queries pending swap requests | Standalone | Unit test covered |
| 52 | POST | `/api/debate/{sessionId}/start` | `StartDebateSession` | Host manually starts debate room from Ready state | None | `ApiResponse<DebateSessionResponse>` | `[Authorize]` (Host only) | `IDebateService.StartDebateSessionAsync` → Sets `DebateSessions.Status='InProgress'` | Stage 6 | Integration test covered |
| 53 | POST | `/api/debate/{sessionId}/leave` | `LeaveSession` | Participant forfeits or leaves active debate | None | `ApiResponse<DebateSessionResponse>` | `[Authorize]` (Participant) | `IDebateService.LeaveSessionAsync` → Cancels session, sets opponent as winner | Stage 6, 15 | Unit test covered |
| 54 | POST | `/api/debate/{sessionId}/evaluate` | `EvaluateSession` | Manually invoke / await full session AI evaluation | None | `ApiResponse<DebateEvaluationResponse>` | `[Authorize]` | `IDebateService.EvaluateSessionAsync` → Calls AI Evaluator, persists `AIJudgement` | Stage 7 | Integration test covered |
| 55 | GET | `/api/debate/{sessionId}/evaluation` | `GetSessionEvaluation` | Fetch stored AI judgement, criteria scores, feedback | None | `ApiResponse<DebateEvaluationResponse>` | `[Authorize]` | `IDebateService.GetSessionEvaluationAsync` → Reads `AIJudgement` (or triggers if missing) | Stage 7, 8 | Integration test covered |
| 56 | POST | `/api/debate/{sessionId}/arguments/{argumentId}/evaluate` | `EvaluateArgument` | Real-time speech evaluation of a single argument | None | `ApiResponse<ArgumentEvaluationDetailDto>` | `[Authorize]` | `IDebateService.EvaluateArgumentAsync` → Calls AI Evaluator for single turn | Analytics | Unit test covered |

#### B. Topics Controller (`TopicsController.cs`)
Base Route: `api/topics` | Controller Auth: Mixed

| # | Method | Full Route | Action | Purpose / Business Flow | Request DTO | Response DTO | Auth | Service & Database Operation | Stage | Existing Test |
|---|---|---|---|---|---|---|---|---|---|---|
| 57 | GET | `/api/topics` | `GetTopics` | List active topics by category & difficulty | `[FromQuery] string? category, difficulty` | `ApiResponse<List<TopicResponse>>` | Anonymous | `ITopicService.GetTopicsAsync` → Queries `Topics` table | Stage 1, 5 | Unit test covered |
| 58 | GET | `/api/topics/{id}` | `GetTopicById` | Get topic details by ID | None | `ApiResponse<TopicResponse>` | Anonymous | `ITopicService.GetTopicByIdAsync` → Queries `Topics` table | Stage 5 | Unit test covered |
| 59 | POST | `/api/topics` | `CreateTopic` | Admin/Lecturer creates standardized debate topic | `CreateTopicRequest` | `ApiResponse<TopicResponse>` | `[Authorize]` (Admin/Lecturer) | `ITopicService.CreateTopicAsync` → Inserts into `Topics` table | Setup / Stage 1 | Unit test covered |
| 60 | PATCH | `/api/topics/{id}` | `UpdateTopic` | Update topic title, description, or active status | `UpdateTopicRequest` | `ApiResponse<TopicResponse>` | `[Authorize]` (Admin/Lecturer) | `ITopicService.UpdateTopicAsync` → Updates `Topics` table | Setup | Unit test covered |
| 61 | DELETE | `/api/topics/{id}` | `DeleteTopic` | Deactivate/soft delete topic | None | `ApiResponse<bool>` | `[Authorize]` (Admin/Lecturer) | `ITopicService.DeleteTopicAsync` → Sets `IsActive=false` | Setup | Unit test covered |

#### C. Debate Challenges Controller (`DebateChallengeController.cs`)
Base Route: `api/debate/challenges` | Controller Auth: `[Authorize]`

| # | Method | Full Route | Action | Purpose / Business Flow | Request DTO | Response DTO | Auth | Service & Database Operation | Stage | Existing Test |
|---|---|---|---|---|---|---|---|---|---|---|
| 62 | POST | `/api/debate/challenges` | `CreateChallenge` | Send direct 1v1 debate challenge to another user | `CreateChallengeRequest` | `ApiResponse<DebateChallengeResponse>` | `[Authorize]` | `IDebateChallengeService.CreateChallengeAsync` → Inserts `DebateChallenges` | Challenge | Unit test covered |
| 63 | GET | `/api/debate/challenges/received` | `GetReceivedChallenges` | View incoming debate challenges | None | `ApiResponse<List<DebateChallengeResponse>>` | `[Authorize]` | `IDebateChallengeService.GetReceivedChallengesAsync` → Queries `DebateChallenges` | Challenge | Unit test covered |
| 64 | GET | `/api/debate/challenges/sent` | `GetSentChallenges` | View outgoing debate challenges | None | `ApiResponse<List<DebateChallengeResponse>>` | `[Authorize]` | `IDebateChallengeService.GetSentChallengesAsync` → Queries `DebateChallenges` | Challenge | Unit test covered |
| 65 | GET | `/api/debate/challenges/{challengeId}` | `GetChallengeById` | Get challenge details | None | `ApiResponse<DebateChallengeResponse>` | `[Authorize]` | `IDebateChallengeService.GetChallengeByIdAsync` → Queries `DebateChallenges` | Challenge | Unit test covered |
| 66 | POST | `/api/debate/challenges/{challengeId}/accept` | `AcceptChallenge` | Accept challenge & spawn debate session | None | `ApiResponse<DebateSessionResponse>` | `[Authorize]` | `IDebateChallengeService.AcceptChallengeAsync` → Spawns `DebateSession` | Challenge | Unit test covered |
| 67 | POST | `/api/debate/challenges/{challengeId}/reject` | `RejectChallenge` | Decline challenge | None | `ApiResponse<bool>` | `[Authorize]` | `IDebateChallengeService.RejectChallengeAsync` → Updates status to Rejected | Challenge | Unit test covered |
| 68 | POST | `/api/debate/challenges/{challengeId}/cancel` | `CancelChallenge` | Sender cancels pending challenge | None | `ApiResponse<bool>` | `[Authorize]` | `IDebateChallengeService.CancelChallengeAsync` → Updates status to Cancelled | Challenge | Unit test covered |

---

### 3.3. Identity & Administration Module (19 Endpoints)

#### A. Auth Controller (`AuthController.cs`)
Base Route: `api/auth` | Controller Auth: Mixed

| # | Method | Full Route | Action | Purpose / Business Flow | Request DTO | Response DTO | Auth | Service & Database Operation | Stage | Existing Test |
|---|---|---|---|---|---|---|---|---|---|---|
| 69 | POST | `/api/auth/register` | `Register` | User registration step 1 (sends OTP) | `RegisterRequest` | `ApiResponse<object>` | Anonymous | `IAuthService.RegisterAsync` → Generates OTP & emails user | Pre-Stage | Integration covered |
| 70 | POST | `/api/auth/verify-register-otp` | `VerifyRegisterOtp` | User registration step 2 (creates account) | `VerifyRegisterOtpRequest` | `ApiResponse<AuthResponse>` | Anonymous | `IAuthService.VerifyRegisterOtpAsync` → Inserts `Users`, assigns 'Student' role | Pre-Stage | Integration covered |
| 71 | POST | `/api/auth/login` | `Login` | Email & password login | `LoginRequest` | `ApiResponse<AuthResponse>` | Anonymous | `IAuthService.LoginAsync` → Validates BCrypt hash, issues JWT & Refresh Token | Pre-Stage | Integration covered |
| 72 | POST | `/api/auth/google-login` | `GoogleLogin` | Google OAuth SSO login | `GoogleLoginRequest` | `ApiResponse<AuthResponse>` | Anonymous | `IAuthService.GoogleLoginAsync` → Validates Google token, creates/logs in user | Pre-Stage | Integration covered |
| 73 | POST | `/api/auth/send-otp` | `SendOtp` | Send generic verification OTP | `SendOtpRequest` | `ApiResponse<object>` | Anonymous | `IOtpService.GenerateAndSendOtpAsync` → Caches OTP in Redis/Memory | Pre-Stage | Unit test covered |
| 74 | POST | `/api/auth/verify-otp` | `VerifyOtp` | Verify OTP code | `VerifyOtpRequest` | `ApiResponse<object>` | Anonymous | `IOtpService.VerifyOtpAsync` → Checks OTP validity | Pre-Stage | Unit test covered |
| 75 | POST | `/api/auth/forgot-password` | `ForgotPassword` | Request password reset OTP | `SendOtpRequest` | `ApiResponse<object>` | Anonymous | `IAuthService.ForgotPasswordAsync` → Sends password reset OTP email | Pre-Stage | Unit test covered |
| 76 | POST | `/api/auth/reset-password` | `ResetPassword` | Reset password using verified OTP | `ResetPasswordRequest` | `ApiResponse<object>` | Anonymous | `IAuthService.ResetPasswordAsync` → Updates user password hash | Pre-Stage | Unit test covered |
| 77 | PUT | `/api/auth/change-password` | `ChangePassword` | Authenticated user changes password | `ChangePasswordRequest` | `ApiResponse<object>` | `[Authorize]` | `IAuthService.ChangePasswordAsync` → Updates password in DB | Pre-Stage | Unit test covered |
| 78 | POST | `/api/auth/refresh-token` | `RefreshToken` | Exchange refresh token for new JWT | `RefreshTokenRequest` | `ApiResponse<AuthResponse>` | Anonymous | `ITokenService.RefreshTokenAsync` → Rotates `RefreshTokens` table | Pre-Stage | Integration covered |
| 79 | POST | `/api/auth/revoke-token` | `RevokeToken` | Invalidate active refresh token (logout) | `RefreshTokenRequest` | `ApiResponse<object>` | Anonymous | `ITokenService.RevokeTokenAsync` → Marks token revoked | Pre-Stage | Integration covered |

#### B. Users Controller (`UsersController.cs`)
Base Route: `api/users` | Controller Auth: `[Authorize]`

| # | Method | Full Route | Action | Purpose / Business Flow | Request DTO | Response DTO | Auth | Service & Database Operation | Stage | Existing Test |
|---|---|---|---|---|---|---|---|---|---|---|
| 80 | GET | `/api/users/me` | `GetMyProfile` | Get profile of logged-in user | None | `ApiResponse<UserProfileResponse>` | `[Authorize]` | `IUserService.GetProfileAsync` → Queries `Users` table | All Stages | Unit test covered |
| 81 | PUT | `/api/users/me` | `UpdateMyProfile` | Update user display name, avatar, bio | `UpdateProfileRequest` | `ApiResponse<UserProfileResponse>` | `[Authorize]` | `IUserService.UpdateProfileAsync` → Updates `Users` record | All Stages | Unit test covered |

#### C. Admin Controller (`AdminController.cs`)
Base Route: `api/admin` | Controller Auth: `[Authorize(Roles="Admin")]`

| # | Method | Full Route | Action | Purpose / Business Flow | Request DTO | Response DTO | Auth | Service & Database Operation | Stage | Existing Test |
|---|---|---|---|---|---|---|---|---|---|---|
| 82 | GET | `/api/admin/dashboard/stats` | `GetDashboardStats` | Platform telemetry: total users, active debates, revenue | None | `ApiResponse<AdminDashboardStatsDto>` | `[Authorize(Roles="Admin")]` | `IAdminService.GetDashboardStatsAsync` → Aggregates statistics | Admin | Integration covered |
| 83 | GET | `/api/admin/users` | `GetUsers` | Filter, search, and paginate user directory | `[FromQuery] UserFilterRequest` | `ApiResponse<PagedList<AdminUserListItemDto>>` | `[Authorize(Roles="Admin")]` | `IAdminService.GetUsersAsync` → Queries `Users` with roles | Admin | Integration covered |
| 84 | GET | `/api/admin/users/{id}` | `GetUserById` | Detailed audit view of user account | None | `ApiResponse<AdminUserDetailDto>` | `[Authorize(Roles="Admin")]` | `IAdminService.GetUserByIdAsync` → Queries `Users`, `Roles`, `Wallets` | Admin | Integration covered |
| 85 | PATCH | `/api/admin/users/{id}/status` | `UpdateUserStatus` | Ban, suspend, or activate user account | `UpdateUserStatusRequest` | `ApiResponse<object>` | `[Authorize(Roles="Admin")]` | `IAdminService.UpdateUserStatusAsync` → Updates `Users.IsActive` | Admin | Integration covered |
| 86 | GET | `/api/admin/roles` | `GetRoles` | List all system security roles | None | `ApiResponse<List<RoleResponse>>` | `[Authorize(Roles="Admin")]` | `IAdminService.GetRolesAsync` → Queries `Roles` table | Admin | Integration covered |
| 87 | PUT | `/api/admin/users/{id}/roles` | `AssignUserRoles` | Promote user to Lecturer or Admin | `AssignUserRolesRequest` | `ApiResponse<object>` | `[Authorize(Roles="Admin")]` | `IAdminService.AssignUserRolesAsync` → Updates `UserRoles` table | Stage 1 (Setup) | Integration covered |

---

### 3.4. Payment & Rewards Module (11 Endpoints)

#### A. Credit Packages Controllers (`CreditPackagesController.cs` & `AdminCreditPackagesController.cs`)
Base Route: `api/credit-packages` & `api/admin/credit-packages` | Controller Auth: Mixed

| # | Method | Full Route | Action | Purpose / Business Flow | Request DTO | Response DTO | Auth | Service & Database Operation | Stage | Existing Test |
|---|---|---|---|---|---|---|---|---|---|---|
| 88 | GET | `/api/credit-packages` | `GetActivePackages` | Public list of purchasable credit packages | None | `ApiResponse<List<CreditPackageResponse>>` | Anonymous | `ICreditPackageService.GetActivePackagesAsync` → Queries `CreditPackages` | Monetization | Unit test covered |
| 89 | GET | `/api/admin/credit-packages` | `GetAllPackages` | Admin catalog management of credit packages | None | `ApiResponse<List<CreditPackageResponse>>` | `[Authorize(Roles="Admin")]` | `ICreditPackageService.GetAllPackagesAsync` → Queries all packages | Monetization | Unit test covered |
| 90 | POST | `/api/admin/credit-packages` | `CreatePackage` | Admin creates credit package | `CreateCreditPackageRequest` | `ApiResponse<CreditPackageResponse>` | `[Authorize(Roles="Admin")]` | `ICreditPackageService.CreatePackageAsync` → Inserts `CreditPackages` | Monetization | Unit test covered |
| 91 | PATCH | `/api/admin/credit-packages/{packageId}` | `PatchPackage` | Admin updates price, credits, or availability | `PatchCreditPackageRequest` | `ApiResponse<CreditPackageResponse>` | `[Authorize(Roles="Admin")]` | `ICreditPackageService.PatchPackageAsync` → Updates `CreditPackages` | Monetization | Unit test covered |

#### B. Payments Controller (`PaymentsController.cs`)
Base Route: `api/payments` | Controller Auth: Mixed

| # | Method | Full Route | Action | Purpose / Business Flow | Request DTO | Response DTO | Auth | Service & Database Operation | Stage | Existing Test |
|---|---|---|---|---|---|---|---|---|---|---|
| 92 | POST | `/api/payments/top-up` | `CreateTopUpPayment` | Initiate PayOS checkout URL for credit purchase | `TopUpRequest` | `ApiResponse<TopUpResponse>` | `[Authorize]` | `IPaymentService.CreateTopUpPaymentAsync` → Inserts `Payments` | Monetization | Unit test covered |
| 93 | GET | `/api/payments/{paymentId}` | `GetPaymentStatus` | Poll status of pending payment transaction | None | `ApiResponse<PaymentResponse>` | `[Authorize]` | `IPaymentService.GetPaymentStatusAsync` → Queries `Payments` | Monetization | Unit test covered |
| 94 | POST | `/api/payments/payos/webhook` | `PayOSWebhook` | PayOS webhook receiver for transaction settlement | `Webhook` (PayOS SDK) | `ApiResponse<object>` | Anonymous (Signature check) | `IPaymentService.ProcessPayOSWebhookAsync` → Credits user `Wallets` | Monetization | Unit test covered |

#### C. Rewards & Wallets Controllers (`RewardsController.cs` & `WalletsController.cs`)
Base Route: `api/rewards` & `api/wallets` | Controller Auth: `[Authorize]`

| # | Method | Full Route | Action | Purpose / Business Flow | Request DTO | Response DTO | Auth | Service & Database Operation | Stage | Existing Test |
|---|---|---|---|---|---|---|---|---|---|---|
| 95 | GET | `/api/rewards/status` | `GetRewardStatus` | Check daily login streak and available reward | None | `ApiResponse<DailyRewardStatusResponse>` | `[Authorize]` | `IRewardService.GetDailyRewardStatusAsync` → Queries `Rewards` | Gamification | Unit test covered |
| 96 | POST | `/api/rewards/daily-login` | `ClaimDailyLogin` | Claim daily login credit bonus | None | `ApiResponse<ClaimRewardResponse>` | `[Authorize]` | `IRewardService.ClaimDailyLoginAsync` → Credits user `Wallets` | Gamification | Unit test covered |
| 97 | GET | `/api/wallets/me` | `GetMyWallet` | View user's current credit balance | None | `ApiResponse<WalletResponse>` | `[Authorize]` | `IWalletService.GetWalletByUserIdAsync` → Queries `Wallets` | User Balance | Unit test covered |
| 98 | GET | `/api/wallets/me/transactions` | `GetMyTransactions` | View user's credit transaction ledger | None | `ApiResponse<List<WalletTransactionResponse>>` | `[Authorize]` | `IWalletService.GetTransactionsByUserIdAsync` → Queries `WalletTransactions` | User Balance | Unit test covered |

---

## 4. Competition Workflow API Mapping (Sequential Flow)

The table below maps the backend APIs in the **exact sequential order** required by the newly agreed 10-Stage Competition workflow. Automatic system operations are explicitly designated.

| Seq | Workflow Stage | Execution Type | HTTP Method | Exact Endpoint | Purpose in Competition Flow | Existing Status |
|---|---|---|---|---|---|---|
| **01** | Stage 1 – Create | User-Facing | `POST` | `/api/competitions` | Organizer creates Competition (INDIVIDUAL or TEAM, capacity, dates). Auto-assigns Organizer as judge. | `IMPLEMENTED` |
| **02** | Stage 1 – Configure | User-Facing | `PATCH` | `/api/competitions/{id}` | Organizer fine-tunes title, description, start dates while in Draft. | `IMPLEMENTED` |
| **03** | Stage 2 – Open Reg | User-Facing | `POST` | `/api/competitions/{id}/open-registration` | Organizer opens registration window (`Draft` → `OpenRegistration`). | `IMPLEMENTED` |
| **04a** | Stage 2 – Register (1v1) | User-Facing | `POST` | `/api/competitions/{id}/registrations` | Competitor registers individually for 1v1. Status set to `Pending`. | `IMPLEMENTED` |
| **04b** | Stage 2 – Approve (1v1) | User-Facing | `PUT` | `/api/competitions/{id}/registrations/{regId}/approve` | Organizer reviews and approves individual registration. | `IMPLEMENTED` |
| **05a** | Stage 2 – Create Team (2v2) | User-Facing | `POST` | `/api/competitions/{id}/teams` | Captain registers team for TEAM 2v2. Status set to `Pending`. | `IMPLEMENTED` |
| **05b** | Stage 2 – Invite Member (2v2) | User-Facing | `POST` | `/api/competitions/{id}/teams/{teamId}/invitations` | Captain invites 2nd user to join team. | `IMPLEMENTED` |
| **05c** | Stage 2 – Accept Invite (2v2) | User-Facing | `POST` | `/api/competitions/{id}/teams/invitations/{reqId}/accept` | 2nd user accepts invitation. Team status becomes `Active`. | `IMPLEMENTED` |
| **06** | Stage 3 – Close Reg | User-Facing | `POST` | `/api/competitions/{id}/close-registration` | Organizer manually closes registration window early or deadline hits. | `IMPLEMENTED` (Has early-close issue) |
| **07** | Stage 4 – Generate Round 1 | User-Facing | `POST` | `/api/competitions/{competitionId}/bracket` | Organizer generates single-elimination bracket. Creates Round 1 matches and seeds. | `IMPLEMENTED` (Pre-creates full tree) |
| **08** | Stage 4 – Auto BYE Advance | **Automatic** | Internal | `CompetitionTournamentService.GenerateBracketAsync` | System automatically flags 1-entrant matches as `"Bye"` and inserts winner into Round 2. | `IMPLEMENTED` |
| **09** | Stage 4 – Start Tournament | User-Facing | `POST` | `/api/competitions/{id}/start` | Organizer starts competition. Status → `"Ongoing"`. Ready matches activated. | `BUG` (Fails for TEAM 2v2 - BE-01) |
| **10** | Stage 4 – View Bracket | User-Facing | `GET` | `/api/competitions/{competitionId}/bracket` | Competitors, Organizer, and Spectators view the live bracket. | `PARTIAL` (Missing `DebateSessionId` - BE-05) |
| **11** | Stage 5 – Get Match Detail | User-Facing | `GET` | `/api/competitions/{competitionId}/matches/{matchId}` | View match topic, status, debate room link, and competitor names. | `MISSING` (BE-04) |
| **12** | Stage 5 – Prepare Debate | User-Facing | `POST` | `/api/competitions/matches/{matchId}/prepare-debate` | Organizer selects topic, creates `DebateSession`, maps PRO/CON participants. | `IMPLEMENTED` |
| **13** | Stage 6 – Enter Debate Room | User-Facing | `GET` | `/api/debate/{sessionId}` | Participants and Organizer inspect debate session status and turn order. | `IMPLEMENTED` |
| **14** | Stage 6 – Start Debate Session | User-Facing | `POST` | `/api/debate/{sessionId}/start` | Participants or host trigger countdown start (`Waiting` → `InProgress`). | `IMPLEMENTED` |
| **15** | Stage 6 – Submit Arguments | User-Facing | `POST` | `/api/debate/{sessionId}/arguments` | Real participants submit turn speeches. Validates turn order and speaker rotation. | `IMPLEMENTED` |
| **16** | Stage 6 – Auto Match Sync | **Automatic** | Internal | `DebateRepository.UpdateLinkedMatchStatusOnSessionCompleteAsync` | On final turn, `DebateSession` reaches `Completed`, linked `CompetitionMatch` → `"Evaluating"`. | `IMPLEMENTED` |
| **17** | Stage 7 – Auto AI Evaluation | **Automatic** | Internal | `DebateService.StartBackgroundEvaluation` | System triggers asynchronous AI grading. Scores criteria and suggests winner. | `IMPLEMENTED` (Lacks failure fallback) |
| **18** | Stage 8 – Review Match | User-Facing | `GET` | `/api/competitions/{competitionId}/matches/{matchId}/review` | Organizer reviews AI suggested winner, criteria breakdown, and transcript. | `PARTIAL` (AssignedJudge restriction lock) |
| **19** | Stage 8 – Finalize Result | User-Facing | `POST` | `/api/competitions/{competitionId}/matches/{matchId}/finalize` | Organizer confirms/overrides winner with mandatory reason and official scores. | `BUG` (Missing AI override check - BE-03) |
| **20** | Stage 9 – Auto Winner Advance | **Automatic** | Internal | `CompetitionTournamentService.FinalizeMatchAsync` | System propagates match winner to `NextMatchId`. When 2 entrants arrive, sets `"Ready"`. | `IMPLEMENTED` |
| **21** | Stage 9 – Auto Round Progress | **Automatic** | Internal | `CompetitionTournamentService.FinalizeMatchAsync` | When all matches in current round finish, marks current round `"Completed"`, next round `"Ongoing"`. | `IMPLEMENTED` |
| **22** | Stage 10 – Complete Competition | **Automatic** | Internal | `CompetitionTournamentService.FinalizeMatchAsync` | Upon final match finalization, marks `Competitions.Status='Completed'` and persists Champion. | `IMPLEMENTED` |

---

## 5. API Coverage and Gap Analysis

| Workflow Requirement | Existing API / Service | Status | Evidence (File + Line Number) | Required Architectural Action |
|---|---|---|---|---|
| **Create Competition (1v1 & 2v2)** | `POST /api/competitions` (`CompetitionService.CreateAsync`) | `IMPLEMENTED` | `CompetitionService.cs`<br>Lines 45–134 | None. Fully supports INDIVIDUAL and TEAM types, date windows, capacity. |
| **Individual Registration & Approval** | `POST /api/competitions/{id}/registrations`<br>`PUT /.../approve` | `IMPLEMENTED` | `CompetitionRegistrationService.cs`<br>Lines 40–120 | None. Correctly handles registration queue and creator approval. |
| **Team 2v2 Creation & Join Flow** | `POST /api/competitions/{id}/teams`<br>`POST /.../invitations` | `IMPLEMENTED` | `CompetitionTeamService.cs`<br>Lines 25–65;<br>`CompetitionTeamRequestService.cs` | None. Enforces captain + 1 invited member lifecycle. |
| **Early Registration Close Behavior** | `POST /api/competitions/{id}/close-registration` | `PARTIAL` / `BUG` | `CompetitionTournamentService.cs`<br>Lines 36–37;<br>`CompetitionService.cs` Line 423 | `GenerateBracketAsync` and `StartCompetitionAsync` block progress if `UtcNow < RegistrationEnd` even if status is `RegistrationClosed`. Need to permit bracket generation once closed early. |
| **Generate Round 1 & Bracket Tree** | `POST /api/competitions/{competitionId}/bracket` | `IMPLEMENTED` | `CompetitionTournamentService.cs`<br>Lines 30–135 | Pre-creates full single-elimination tree. Seeding and binary bracket layout are mathematically consistent. |
| **Automatic BYE Handling** | Internal logic in `GenerateBracketAsync` | `IMPLEMENTED` | `CompetitionTournamentService.cs`<br>Lines 116–131 | Detects single-entrant matches in Round 1, sets `"Bye"`, and auto-advances entrant to Round 2. |
| **Start Competition TEAM 2v2** | `POST /api/competitions/{id}/start` (`CompetitionService.StartCompetitionAsync`) | `BUG` | `CompetitionService.cs`<br>Line 508 | **P0 Bug:** `active.Count * 2 != entrantCount` compares members to teams. Must be fixed to `active.Count != entrantCount`. |
| **Public Match Detail Endpoint** | None | `MISSING` | `CompetitionTournamentController.cs`<br>Lines 10–61 | Add `GET /api/competitions/{competitionId}/matches/{matchId}` returning topic, status, debate session id, participants, and schedule. |
| **Bracket Data for Navigation** | `GET /api/competitions/{competitionId}/bracket` | `PARTIAL` | `TournamentDtos.cs`<br>Line 8 (`MatchResponse`) | `MatchResponse` omits `DebateSessionId`, preventing frontend from navigating users to debate rooms. Must enrich DTO. |
| **Organizer Sole Judge Assignment** | `PUT /.../matches/{matchId}/judge` | `NOT REQUIRED` / `PARTIAL` | `CompetitionTournamentService.cs`<br>Line 233 | Business rule states Organizer is sole judge without per-match assignment. Current code rejects finalization if `AssignedJudgeUserId != actorId`. Must auto-default `AssignedJudgeUserId = competition.CreatedBy`. |
| **Prepare Match Debate & Link** | `POST /api/competitions/matches/{matchId}/prepare-debate` | `IMPLEMENTED` | `CompetitionDebateBridgeService.cs`<br>Lines 45–257 | Idempotently creates `DebateSession`, sets up 3 standard rounds, maps PRO/CON participants for both 1v1 and 2v2. |
| **Conduct Real Human Debate** | `POST /api/debate/{sessionId}/arguments` | `IMPLEMENTED` | `DebateService.cs`<br>Lines 360–450 | Enforces turn order in 1v1 and speaker rotation in 2v2. No SignalR required; runs over JWT-authenticated REST. |
| **Debate to Match Status Sync** | `UpdateLinkedMatchStatusOnSessionCompleteAsync` | `IMPLEMENTED` | `DebateRepository.cs`<br>Lines 1–15 | When debate session completes, linked `CompetitionMatch.Status` automatically transitions from `"Ongoing"` to `"Evaluating"`. |
| **AI Evaluation Execution** | `DebateEvaluationCoordinator.StartInBackground` | `IMPLEMENTED` | `DebateService.cs`<br>Lines 405–408, 502–506 | Evaluates transcript asynchronously, saves `AIJudgement` record. Does not finalize match or pick official winner. |
| **AI Failure & Fallback Handling** | None | `MISSING` | `CompetitionTournamentService.cs`<br>Lines 240–241 | If AI service fails/timeouts, match is stuck in `"Evaluating"` forever. Need an emergency manual finalize override or retry endpoint. |
| **Organizer Review Authorization** | `GET /.../matches/{matchId}/review` | `IMPLEMENTED` | `CompetitionTournamentService.cs`<br>Lines 206–223 | Restricts review data (AI score breakdown, criteria) to Organizer (`competition.CreatedBy == actorId`) and assigned judge. |
| **Enforce AI Override Reason** | `POST /.../matches/{matchId}/finalize` | `BUG` | `CompetitionTournamentService.cs`<br>Lines 255–259 | Only checks judge criteria total score tie/override; fails to check if winner differs from `AIJudgement.SuggestedWinnerSide`. |
| **Structured Decision Storage** | Internal logic in `FinalizeMatchAsync` | `PARTIAL` | `CompetitionTournamentService.cs`<br>Lines 266–267 | Decision reason is concatenated into string `JudgeScore.Feedback`. Should be saved as a clean column on `CompetitionMatch`. |
| **Automatic Next-Round Progression** | Internal logic in `FinalizeMatchAsync` | `IMPLEMENTED` | `CompetitionTournamentService.cs`<br>Lines 280–320 | Advances winner to `NextMatchId`. Activates next match to `"Ready"` when both opponents arrive. Activates next round to `"Ongoing"`. |
| **Championship & Completion** | Internal logic in `FinalizeMatchAsync` | `IMPLEMENTED` | `CompetitionTournamentService.cs`<br>Lines 295–307 | Detects final match completion, marks `Competitions.Status='Completed'`, persists winner as official Champion. |

---

## 6. Detailed Critical Business Rule Audit

### 6.1. INDIVIDUAL vs TEAM Participant Validation
- **Source Verification:** `CompetitionService.cs` lines 494–524 (`HasValidStartBracketAsync`), `CompetitionTournamentService.cs` lines 43–65 (`GenerateBracketAsync`).
- **Code Behavior:**
  - For INDIVIDUAL: Validates approved registrations (`r.Status == "Approved"`), checks all users are active (`r.User.IsActive`), verifies count matches bracket entrants, and verifies set equality between registered user IDs and match participant user IDs.
  - For TEAM: Queries active teams (`t.Status == "Active"`). Validates each team has captain active, exactly 1 member active, captain != member, and no user is shared across multiple teams (`users.Add` anti-collision).
- **Comparison:** Fully complies with business rules, except for the unit calculation bug described in BE-01.

### 6.2. TEAM Must Have Exactly Two Distinct Active Members
- **Source Verification:** `CompetitionTournamentService.cs` line 59, `CompetitionService.cs` line 515, `CompetitionDebateBridgeService.cs` lines 189–213.
- **Code Behavior:**
  - In `GenerateBracketAsync`: Rejects bracket generation if any active team does not have `team.Captain.IsActive`, `team.TeamMembers.Count == 1`, and `team.TeamMembers.Single().User.IsActive`.
  - In `PrepareMatchDebateAsync`: Re-checks `proUserIds.Count != 2` and `conUserIds.Count != 2`. If a team member left after bracket generation, debate session preparation aborts with a descriptive error.
- **Comparison:** Strictly enforced at all 3 layers (registration, bracket generation, debate preparation).

### 6.3. Registration Closure & Early-Close Behavior
- **Source Verification:** `CompetitionService.cs` lines 372–375, 416–420, 423; `CompetitionTournamentService.cs` lines 36–37.
- **Code Behavior:**
  - Organizer calling `POST /api/competitions/{id}/close-registration` updates `competition.Status = "RegistrationClosed"`.
  - However, `GenerateBracketAsync` explicitly checks `if (competition.Status != "RegistrationClosed" || DateTime.UtcNow < competition.RegistrationEnd) return Conflict("Registration must be closed and its deadline passed.");`.
  - And `StartCompetitionAsync` checks `if (now < competition.RegistrationEnd || now < competition.StartDate) return Conflict("Competition can start only after registration closes and its start time arrives.");`.
- **Comparison:** Current implementation strictly forces waiting for the pre-scheduled deadline. To support the agreed workflow where the Organizer can close early and proceed, either `RegistrationEnd` must be updated to `UtcNow` upon manual close, or the condition `DateTime.UtcNow < competition.RegistrationEnd` must be skipped if `Status == "RegistrationClosed"`.

### 6.4. Bracket Generation & BYE Handling
- **Source Verification:** `CompetitionTournamentService.cs` lines 67–135 (`GenerateBracketAsync`).
- **Code Behavior:**
  - Uses binary power-of-two expansion: `size = 2; while (size < entrants.Count) size *= 2;`.
  - Uses deterministic seed distribution: `SeedSlots(size)` (e.g., size 4 → [1, 4, 2, 3]; size 8 → [1, 8, 4, 5, 2, 7, 3, 6]).
  - Entrants are shuffled once using `RandomNumberGenerator.GetInt32`, and assigned seed numbers 1..$N$.
  - Slots with seed number $> N$ remain empty.
  - In Round 1, any match having exactly 1 participant is flagged as `Status = "Bye"`, and that participant is immediately copied into Round 2 (`matches[1]`) with the correct PRO/CON side.
- **Comparison:** Robust, standard tournament bracket algorithm. Handles BYEs automatically without user intervention.

### 6.5. Round Completion Detection
- **Source Verification:** `CompetitionTournamentService.cs` lines 309–312 (`FinalizeMatchAsync`).
- **Code Behavior:**
  - After saving official scores and winner, the service executes:
    ```csharp
    var matchRound = await _db.CompetitionRounds.SingleAsync(r => r.CompetitionRoundId == match.CompetitionRoundId, ct);
    if (!await _db.CompetitionMatches.AnyAsync(m => m.CompetitionRoundId == match.CompetitionRoundId
        && m.Status != "Completed" && m.Status != "Bye", ct))
        matchRound.Status = "Completed";
    ```
- **Comparison:** Accurately identifies round completion. A round is marked `"Completed"` if and only if every match in that round has reached `"Completed"` or was an initial `"Bye"`.

### 6.6. Automatic Next-Round Generation & Progression
- **Source Verification:** `CompetitionTournamentService.cs` lines 280–294, 313–320 (`FinalizeMatchAsync`).
- **Code Behavior:**
  - Because all rounds and matches are pre-created during bracket generation, next-round matches are not dynamically inserted; they are dynamically *populated and unlocked*.
  - When a match is finalized, `winner` is added to `nextMatch.Participants`:
    ```csharp
    next.Participants.Add(new MatchParticipant { 
        Side = match.BracketPosition % 2 == 1 ? "PRO" : "CON",
        UserId = winner.UserId, TeamId = winner.TeamId, SeedNumber = winner.SeedNumber 
    });
    if (next.Participants.Count == 2 && next.Status == "Scheduled") next.Status = "Ready";
    ```
  - If `nextRound.Status == "Pending"` and any match in it has reached `"Ready"`, `nextRound.Status` updates to `"Ongoing"`.
- **Comparison:** Fully satisfies the agreed business requirement that the Organizer does not need to click "Generate" for subsequent rounds. The progression is 100% automatic.

### 6.7. Duplicate Round & Match Prevention
- **Source Verification:** `CompetitionMatchConfiguration.cs` lines 14–20; `CompetitionTournamentService.cs` lines 32, 38–40.
- **Code Behavior:**
  - Bracket generation executes in an `IsolationLevel.Serializable` transaction and checks `_db.CompetitionRounds.AnyAsync(...) || _db.CompetitionMatches.AnyAsync(...)`.
  - Database schema enforces unique constraints:
    - `UQ_CompetitionMatches`: Unique on `(CompetitionRoundId, MatchNumber)`.
    - `UQ_CompetitionMatches_Round_Position`: Unique on `(CompetitionRoundId, BracketPosition)`.
- **Comparison:** Impossible to generate duplicate brackets, rounds, or match slots.

### 6.8. Concurrent Finalization of Multiple Matches in the Same Round
- **Source Verification:** `CompetitionTournamentService.cs` lines 227–228, 260–261; `JudgeScoreConfiguration.cs` lines 14–16.
- **Code Behavior:**
  - `FinalizeMatchAsync` opens an `IsolationLevel.Serializable` transaction and acquires an exclusive SQL Server lock via `LockCompetitionAsync` (`UPDLOCK, HOLDLOCK`).
  - Concurrency token `byte[] RowVersion` is verified on `CompetitionMatch`.
  - Unique index `UQ_JudgeScores` on `(CompetitionMatchId, JudgeUserId, MatchParticipantId, CriteriaId)` physically blocks duplicate score insertions.
  - If two different matches in the same round are finalized concurrently, both transactions commit cleanly without race conditions on round status or next-match slots.
- **Comparison:** Fully concurrency-safe.

### 6.9. Organizer-Only Judge Authorization
- **Source Verification:** `CompetitionTournamentService.cs` line 233 (`FinalizeMatchAsync`).
- **Code Behavior:**
  - Current line 233: `if (match.AssignedJudgeUserId != actorId) return ApiResponse<object>.FailureResponse("Only the assigned judge may confirm the result.", CompetitionErrorCodes.Forbidden);`.
  - Under the newly agreed flow, the Organizer is the sole judge, and per-match judge assignment is not performed.
  - As a result, `match.AssignedJudgeUserId` remains null, and the Organizer is rejected with 403 Forbidden when attempting to finalize!
- **Comparison:** Violates the new agreed workflow. Must be adjusted to check `if (competition.CreatedBy != actorId)` or automatically set `match.AssignedJudgeUserId = competition.CreatedBy`.

### 6.10. AI Suggested Winner vs Official Winner
- **Source Verification:** `DebateService.cs` lines 405–408; `CompetitionTournamentService.cs` lines 218–222, 273–274.
- **Code Behavior:**
  - AI evaluation computes `AIJudgement.SuggestedWinnerSide` and overall scores. It never writes to `CompetitionMatch.WinnerUserId` or `WinnerTeamId`.
  - Official winner is determined strictly when the Organizer posts `FinalizeMatchRequest.WinnerMatchParticipantId`.
- **Comparison:** Fully compliant with the core rule: AI only advises; human Organizer decides.

### 6.11. Mandatory Override Reason
- **Source Verification:** `CompetitionTournamentService.cs` lines 258–259.
- **Code Behavior:**
  - Current line 258: `if (totals[winner.MatchParticipantId] <= totals[other.MatchParticipantId] && string.IsNullOrWhiteSpace(request!.DecisionReason)) return FailureResponse("A tie or override requires a decision reason.");`.
  - Missing check against `ai.SuggestedWinnerSide`. If judge totals award winner more points than loser, but AI suggested the other side, no reason is demanded.
- **Comparison:** Violates agreed business rule. Must check both score override AND AI recommendation override.

### 6.12. AI Evaluation Failure & Retry/Fallback Behavior
- **Source Verification:** `CompetitionTournamentService.cs` lines 240–241; `DebateService.cs` lines 502–506.
- **Code Behavior:**
  - `FinalizeMatchAsync` line 240: `if (!await _db.AIJudgements.AnyAsync(j => j.DebateSessionId == match.DebateSessionId, ct)) return Conflict("AI evaluation is not yet available.");`.
  - If the external AI service times out or throws an unhandled exception, `AIJudgements` is never created.
  - There is no retry endpoint or manual override bypass. The match is permanently stuck in `"Evaluating"`.
- **Comparison:** Critical edge-case defect. An emergency override reason policy or retry trigger must be introduced.

### 6.13. DebateSession Completion & Match Status Synchronization
- **Source Verification:** `DebateRepository.cs` lines 1–15; `DebateService.cs` lines 398, 436.
- **Code Behavior:**
  - When the final speech turn is submitted, `DebateService` marks `DebateSession.Status = SessionStatus.Completed`.
  - It immediately calls `_debateRepository.UpdateLinkedMatchStatusOnSessionCompleteAsync(sessionId, completedAt, cancellationToken)`.
  - The repository updates `CompetitionMatches.Status = "Evaluating"` and `UpdatedAt = completedAt`.
- **Comparison:** 100% compliant and working in source.

### 6.14. Final Champion Persistence
- **Source Verification:** `CompetitionTournamentService.cs` lines 273–274, 295–307; `GetBracketAsync` lines 164–165.
- **Code Behavior:**
  - In the final round match (`NextMatchId == null`), `match.WinnerUserId` / `match.WinnerTeamId` is recorded upon finalization, and `competition.Status = "Completed"`.
  - `GetBracketAsync` retrieves the final match and projects `ChampionUserId` / `ChampionTeamId` into `BracketResponse`.
- **Comparison:** Champion is reliably persisted on the final match and competition aggregate.

### 6.15. Competition Status Transitions
- **Source Verification:** `CompetitionService.cs` lines 405–448 (`UpdateStatusInternalAsync`).
- **Allowed Transitions:**
  - `Draft` → `OpenRegistration` (only if within scheduled registration window).
  - `OpenRegistration` → `RegistrationClosed`.
  - `RegistrationClosed` → `Ongoing` (requires valid bracket and start date reached).
  - `Ongoing` → `Completed` (only via official final match completion).
  - Any non-ongoing state → `Cancelled`.
- **Comparison:** State machine is clean, strictly guarded, and prevents invalid regressions.

---

## 7. Prioritized Implementation Backlog

The following backlog is prioritized by **workflow dependency** (blockers to running a tournament from Stage 1 to 10):

```
┌────────────────────────────────────────────────────────────────────────┐
│ Blockers to Competition Start & Finalization (Phase 1)                 │
│ 1. FIX: BE-01 Team 2v2 Start Unit Mismatch Bug                         │
│ 2. FIX: Organizer Sole Judge Authorization in FinalizeMatchAsync       │
│ 3. FIX: BE-03 Enforce Mandatory Reason on AI Suggested Winner Override │
│ 4. FIX: Early Registration Close Bracket Generation Lock               │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│ Frontend Navigation & Match Operations (Phase 2)                       │
│ 5. ADD: BE-04 Public Match Detail Endpoint (GET /matches/{id})         │
│ 6. EXTEND: BE-05 MatchResponse with DebateSessionId & Display Metadata │
│ 7. EXTEND: BE-08 Detailed Start Validation Error Reasons               │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│ Reliability, Auditability & Fallback (Phase 3)                         │
│ 8. EXTEND: BE-06 Structured Decision Columns on CompetitionMatch       │
│ 9. ADD: AI Evaluation Failure / Emergency Fallback Finalization        │
│ 10. REMOVE/DEPRECATE: Mark AssignJudge as NOT REQUIRED                 │
└────────────────────────────────────────────────────────────────────────┘
```

### Detailed Item Descriptions

#### Item 1: FIX – Correct TEAM 2v2 Validation in `HasValidStartBracketAsync` [P0]
- **Category:** `FIX` | **Stage:** Stage 4 (Start Competition)
- **Why Needed:** Eliminates the unit calculation bug where active teams ($N$) were multiplied by 2 and compared to bracket entrants ($N$), causing all valid 2v2 tournaments to fail start with 409 Conflict.
- **Affected Files:** `Services/SystemService.BLL/Services/Competition/Implementations/CompetitionService.cs` (Line 508).
- **Migration Required:** No.
- **Verification Test:** `SqlServerCompetitionDebateTests.Tournament_TwoTeams_FourDistinctUsers_OfficialTeamChampion`.

#### Item 2: FIX – Organizer Sole Judge Authorization in `FinalizeMatchAsync` [P0]
- **Category:** `FIX` | **Stage:** Stage 8 (Organizer Review & Finalization)
- **Why Needed:** Aligns with agreed workflow where Organizer does not assign judges per match.
- **Affected Files:**
  - `Services/SystemService.BLL/Services/Competition/Implementations/CompetitionTournamentService.cs` (Line 233).
  - Change line 233 from `if (match.AssignedJudgeUserId != actorId)` to `if (competition.CreatedBy != actorId && match.AssignedJudgeUserId != actorId)`.
  - In `GenerateBracketAsync` / `PrepareMatchDebateAsync`, default `match.AssignedJudgeUserId = competition.CreatedBy`.
- **Migration Required:** No.
- **Verification Test:** Finalize match as competition creator without invoking `AssignJudgeAsync`.

#### Item 3: FIX – Enforce Mandatory DecisionReason on AI Override [P0]
- **Category:** `FIX` | **Stage:** Stage 8 (Organizer Review & Finalization)
- **Why Needed:** Enforces the mandatory business rule that overriding AI's recommendation requires explicit reasoning.
- **Affected Files:** `Services/SystemService.BLL/Services/Competition/Implementations/CompetitionTournamentService.cs` (Lines 255–259).
- **Logic:** Query `_db.AIJudgements` for the match session. If `!string.Equals(winner.Side, ai.SuggestedWinnerSide, StringComparison.OrdinalIgnoreCase)` and `string.IsNullOrWhiteSpace(request.DecisionReason)`, reject with 409 Conflict.
- **Migration Required:** No.
- **Verification Test:** Integration test verifying AI recommends "CON", judge picks "PRO" without reason (rejects 409), and with reason (succeeds).

#### Item 4: FIX – Permit Bracket Generation on Early Registration Close [P0]
- **Category:** `FIX` | **Stage:** Stage 3 & 4 (Close Registration & Generate Bracket)
- **Why Needed:** If the Organizer closes registration early, they must be allowed to generate the bracket immediately without waiting for the original deadline.
- **Affected Files:**
  - `CompetitionTournamentService.cs` (Lines 36–37): Update condition to `if (competition.Status != "RegistrationClosed") return Conflict(...)`.
  - `CompetitionService.cs` (Line 423): When transitioning to `"Ongoing"`, if status is `"RegistrationClosed"`, check `now < competition.StartDate` instead of `now < competition.RegistrationEnd`.
- **Migration Required:** No.
- **Verification Test:** Close registration before deadline, immediately call `GenerateBracket`, verify bracket generation succeeds.

#### Item 5: ADD – Implement Public Match Detail Endpoint [P1]
- **Category:** `ADD` | **Stage:** Stage 5 & 6 (Prepare & Conduct Match)
- **Why Needed:** General competitors and viewers need to view match status, topic, round, and debate room links without hitting the restricted `GetReviewAsync` endpoint.
- **Affected Files:**
  - Controller: `Services/SystemService/Controllers/Competition/CompetitionTournamentController.cs`
  - Route: `GET /api/competitions/{competitionId}/matches/{matchId}`
  - Interface & Service: `ICompetitionTournamentService.GetMatchDetailAsync`
- **Migration Required:** No.
- **Verification Test:** Competitor calls endpoint, receives match metadata, competitor display names, and `DebateSessionId`.

#### Item 6: EXTEND – Enrich `MatchResponse` with `DebateSessionId` & Metadata [P1]
- **Category:** `EXTEND` | **Stage:** Stage 4 & 5 (View Bracket & Navigate to Debate)
- **Why Needed:** Frontend bracket tree cannot route users into the debate room because `MatchResponse` lacks `DebateSessionId`.
- **Affected Files:**
  - `Services/SystemService.BLL/DTOs/Competition/Tournament/TournamentDtos.cs` (`MatchResponse`).
  - `Services/SystemService.BLL/Services/Competition/Implementations/CompetitionTournamentService.cs` (`GetBracketAsync`).
- **Fields Added:** `DebateSessionId`, `TopicId`, `TopicTitle`, `AssignedJudgeUserId`, `ProDisplayName`, `ConDisplayName`, `WinnerDisplayName`.
- **Migration Required:** No.

#### Item 7: EXTEND – Descriptive Start Validation Error Reporting [P1]
- **Category:** `EXTEND` | **Stage:** Stage 4 (Start Competition)
- **Why Needed:** Replaces generic 409 message with actionable error codes (e.g. `BracketNotGenerated`, `InsufficientTeams`, `InactiveMember`).
- **Affected Files:** `Services/SystemService.BLL/Services/Competition/Implementations/CompetitionService.cs` (`HasValidStartBracketAsync`).
- **Migration Required:** No.

#### Item 8: EXTEND – Add Structured Decision Columns to `CompetitionMatch` [P2]
- **Category:** `EXTEND` | **Stage:** Stage 8 (Auditability)
- **Why Needed:** Stores official decision reason, AI override flag, and timestamp in structured columns rather than string-concatenating into `JudgeScores.Feedback`.
- **Affected Files:**
  - `Services/SystemService.DAL/Entities/Competition/CompetitionMatch.cs`
  - EF Core Configuration & Migration: Add `DecisionReason` (nvarchar 1000), `AiSuggestedWinnerSide` (nvarchar 10), `IsAiOverridden` (bit).
- **Migration Required:** YES (Single lightweight nullable column addition).

#### Item 9: ADD – AI Failure & Emergency Fallback Handling [P2]
- **Category:** `ADD` | **Stage:** Stage 7 & 8 (Error Recovery)
- **Why Needed:** Prevents tournament deadlock if external Azure Container App AI Evaluator goes down.
- **Affected Files:** `CompetitionTournamentService.FinalizeMatchAsync`. Allow Organizer to finalize with `EmergencyOverrideReason` if AI evaluation status is failed/timed out.
- **Migration Required:** No.

#### Item 10: REMOVE/DEPRECATE – Mark `AssignJudge` as `NOT REQUIRED` [P3]
- **Category:** `REMOVE/DEPRECATE` | **Stage:** Stage 5
- **Why Needed:** Streamlines system to match agreed flow. Maintain endpoint for backward compatibility but remove from frontend competition wizard.

---

## 8. Existing Test Coverage & Missing Test Scenarios

### Existing Test Suite
Located in `Tests/SystemService.IntegrationTests/SqlServerCompetitionDebateTests.cs`:
1. `Tournament_Individual_CreateRegisterApproveCloseThroughChampion`: End-to-end 1v1 individual tournament.
2. `Tournament_TwoTeams_FourDistinctUsers_OfficialTeamChampion`: End-to-end 2v2 team tournament.
3. `Tournament_ThreeIndividuals_ByeDebatesAndChampion`: Verifies BYE seeding and progression for odd entrant counts.
4. `Tournament_ConcurrentJudgeFinalize_OneOfficialResultAndOneChampion`: Verifies concurrency safety during finalization.
5. `Prepare_FiveConcurrentRequests_CreateOneLinkedSessionWithoutOrphans`: Verifies debate bridge idempotency.
6. `FinalArgument_CompletesDebateAndMovesLinkedMatchToEvaluating`: Verifies automatic match status transition on final turn.

### Missing Test Scenarios to Implement
1. **AI Override Without Reason:** Attempt finalization selecting winner opposite to AI recommendation with null/empty `DecisionReason` → Expect 409 Conflict.
2. **AI Override With Reason:** Attempt finalization selecting winner opposite to AI recommendation with valid `DecisionReason` → Expect 200 OK and recorded override.
3. **Early Close Immediate Bracket Generation:** Close registration before deadline, immediately call bracket generation → Expect 200 OK without waiting for deadline.
4. **Organizer Sole Judge Finalization:** Create competition, do not call `AssignJudge`, conduct debate, call `FinalizeMatchAsync` as Organizer → Expect 200 OK.
5. **TEAM 2v2 Start Bug Fix:** Automated regression test verifying `StartCompetitionAsync` succeeds for 4 teams (8 users) with bracket size 4.

---

## 9. Unresolved Business Questions & UNKNOWN Items

1. **AI Service Outage Policy:**
   - *Question:* If the external AI evaluation service fails completely, is the Organizer permitted to finalize the match with an explicit "Manual Emergency Override" reason, or must the tournament halt until the AI service recovers?
2. **Early Close Start Time Window:**
   - *Question:* When registration is closed early, should the competition start time (`StartDate`) also be allowed to start immediately, or must it still wait until the clock reaches `StartDate`?
3. **Spectator Debate Visibility:**
   - *Question:* Should non-participants be allowed to fetch live debate transcripts while a match is `"InProgress"`, or only after the session reaches `"Completed"`?

---

## 10. Supporting File & Line References

- `Services/SystemService/Program.cs`: Lines 40–165 (DI registrations, DbContext, HTTP clients, JWT).
- `Gateway/appsettings.json`: Lines 8–75 (YARP route clusters).
- `Services/SystemService/Controllers/Competition/CompetitionsController.cs`: Lines 28–189.
- `Services/SystemService/Controllers/Competition/CompetitionTournamentController.cs`: Lines 10–61.
- `Services/SystemService/Controllers/Competition/CompetitionRegistrationsController.cs`: Lines 23–130.
- `Services/SystemService/Controllers/Competition/CompetitionTeamsController.cs`: Lines 23–110.
- `Services/SystemService/Controllers/Competition/CompetitionTeamRequestsController.cs`: Lines 23–162.
- `Services/SystemService/Controllers/Competition/CompetitionJudgesController.cs`: Lines 19–25.
- `Services/SystemService/Controllers/Debate/DebateController.cs`: Lines 26–334.
- `Services/SystemService.BLL/Services/Competition/Implementations/CompetitionService.cs`: Lines 45–134 (`CreateAsync`), 370–448 (`UpdateStatusInternalAsync`), 450–527 (`HasValidStartBracketAsync`).
- `Services/SystemService.BLL/Services/Competition/Implementations/CompetitionTournamentService.cs`: Lines 30–135 (`GenerateBracketAsync`), 148–166 (`GetBracketAsync`), 168–196 (`AssignJudgeAsync`), 206–223 (`GetReviewAsync`), 225–325 (`FinalizeMatchAsync`).
- `Services/SystemService.BLL/Services/Competition/Implementations/CompetitionDebateBridgeService.cs`: Lines 45–257 (`PrepareMatchDebateAsync`).
- `Services/SystemService.BLL/Services/Debate/Implementations/DebateService.cs`: Lines 360–450 (`SubmitArgumentAsync`), 405–408 & 502–506 (`StartBackgroundEvaluation`).
- `Services/SystemService.DAL/Repositories/Debate/Implementations/DebateRepository.cs`: Lines 1–15 (`UpdateLinkedMatchStatusOnSessionCompleteAsync`).
- `Services/SystemService.DAL/Configurations/Competition/CompetitionMatchConfiguration.cs`: Lines 14–25 (Indexes and RowVersion).
- `Services/SystemService.DAL/Configurations/Competition/JudgeScoreConfiguration.cs`: Lines 14–20 (`UQ_JudgeScores`).

---

## 11. Final Summary Metrics

| Metric | Verified Count | Notes |
|---|---|---|
| **Total Backend Endpoints Scanned** | **98** | Scanned across all 17 controllers |
| **Total Competition-Related Endpoints** | **37** | 6 controllers (Competitions, Tournament, Registrations, Teams, TeamRequests, Judges) |
| **Total Debate-Related Endpoints** | **31** | 3 controllers (Debate, Topics, DebateChallenge) |
| **Total Identity & Payment Endpoints** | **30** | 8 controllers (Auth, Users, Admin, CreditPackages, Payments, Rewards, Wallets) |
| **Fully Implemented Requirements** | **12** | Bracket generation, BYE handling, team validation, debate engine, round progress, champion persistence |
| **Partial Requirements** | **3** | `MatchResponse` missing fields (BE-05), Early close lock (BE-02), Unstructured decision storage (BE-06) |
| **Missing Requirements** | **2** | Public match detail endpoint (BE-04), AI failure fallback handler |
| **Confirmed Bugs** | **3** | TEAM 2v2 start calculation (BE-01), AI override reason check (BE-03), Sole judge authorization lock |
| **Not-Required Operations** | **1** | Per-match judge assignment (`PUT /matches/{id}/judge`) under the new sole-organizer flow |
| **Highest-Priority Blockers** | **2** | BE-01 (prevents TEAM 2v2 start) and Sole Judge Auth Lock (blocks Organizer finalization) |

---
*Report compiled autonomously following strict read-only backend code inspection.*

