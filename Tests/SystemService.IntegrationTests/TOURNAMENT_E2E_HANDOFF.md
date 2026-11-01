# ADPP Competition tournament SQL Server E2E handoff

These tests are opt-in and write only uniquely named fixture rows in the existing
`DebatePracticePlatformDB`. Run them only from the intended Windows host after
confirming `THANH-SANGG\SQLEXPRESS` and Windows Integrated Authentication.

## Preconditions

- Set `ADPP_SQLSERVER_TEST_CONNECTION_STRING` from the local SystemService
  `appsettings.json` `DefaultConnection` when it points to the intended development
  database with Windows Integrated Authentication. A User Secrets override is not
  required for this test runner. Never paste connection strings into logs.
- The SQL Server test fixture verifies machine, instance, database, authentication,
  table count and required V0.7 columns before writing.
- The database needs active seeded Topic, `1 vs 1` DebateFormat, Lecturer role,
  active DebateCriteria, and either an active `2 vs 2` DebateFormat or no format
  with that name. A temporary `2 vs 2` format is created only when absent.
- Do not run migrations, EnsureCreated, rebuild or schema scripts.

## SQL Server tournament workflow tests

Set `ADPP_RUN_SQLSERVER_TESTS=1`, then run from the repository root:

```powershell
dotnet test Tests/SystemService.IntegrationTests/SystemService.IntegrationTests.csproj --filter 'FullyQualifiedName~Tournament_' --logger 'trx;LogFileName=tournament-e2e.trx' --verbosity normal *> tournament-e2e.log
```

The fixture tests cover a three-person individual bracket with BYE, two-team 2v2
bracket, Prepare/Start/SubmitArgument through Debate Completed and Match
Evaluating, fixture AI judgement, judge review/score/finalize, winner advancement,
champion, duplicate finalize rejection, concurrent Generate/Start, and invalid
owner or incomplete team rejection, judge authorization, plus two concurrent
judge Finalize requests.
One test also uses the real Competition
Create/Open, Registration Register/Approve and Close service methods before
Generate; it waits approximately 22 seconds for its fixture registration/start
window. They must leave no fixture rows after disposal.

## Optional live AI test

The published evaluator docs URL supplied by the project owner is
`https://adpp-ai-evaluator.greenstone-4d67d46a.indonesiacentral.azurecontainerapps.io/docs`.
Set `ADPP_RUN_LIVE_AI_TESTS=1` and set `ADPP_AI_EVALUATOR_URL` to the **base URL**
without `/docs`:

```powershell
$env:ADPP_RUN_SQLSERVER_TESTS = '1'
$env:ADPP_RUN_LIVE_AI_TESTS = '1'
$env:ADPP_AI_EVALUATOR_URL = 'https://adpp-ai-evaluator.greenstone-4d67d46a.indonesiacentral.azurecontainerapps.io'
$settings = Get-Content 'Services/SystemService/appsettings.json' -Raw | ConvertFrom-Json
$env:ADPP_SQLSERVER_TEST_CONNECTION_STRING = $settings.ConnectionStrings.DefaultConnection
dotnet test Tests/SystemService.IntegrationTests/SystemService.IntegrationTests.csproj --filter 'FullyQualifiedName~Tournament_' --logger 'trx;LogFileName=tournament-live-ai-e2e.trx' --verbosity normal *> tournament-live-ai-e2e.log
```

Do not print `ADPP_SQLSERVER_TEST_CONNECTION_STRING`. The test fixture verifies
the SQL target and Windows Integrated Authentication before writing. The test
client posts to `<base URL>/evaluate/session`. Confirm the published service
is reachable from the Windows runner before opting in. The live AI tests require
persisted AIJudgements from that service and never insert fixture judgements.
`Tournament_LiveAiEvaluation_ThreeTeams_ByeScoresAndChampion` uses the actual
Competition and Team services to create and open a TEAM tournament, create three
2v2 teams, send and accept member invitations, and close registration. It then
checks the automatic BYE, completes two real AI evaluated debates, and verifies
the official judge scores and champion. The registration window adds about 32
seconds to this test. All fixture records are removed by `SqlFixture.DisposeAsync`.

## Report back

Provide test totals, each test name and PASS/FAIL, full failure stack traces,
the TRX/log paths, SQL Server instance identity, and read-only post-run checks for
`adpp-sql-it-%@example.invalid` users, `ADPP SQL test %` competitions, related
rounds/matches/participants/sessions/JudgeScores/AIJudgements, and temporary
`2 vs 2` formats. If fixture cleanup fails, report exact IDs; do not delete
unrelated development rows.

For the three-team live AI case, copy the `ADPP_LIVE_AI_TOURNAMENT_REPORT=` JSON
from the test output before cleanup and summarize: team count and names, captain
and member IDs, which **actual** team got the BYE, each match's PRO/CON teams,
AI suggested winner and overall PRO/CON scores, official per-criterion judge
scores and final totals, match winner, advancement, and final champion. The
fixture's human judge assigns deterministic test scores and confirms PRO; report
those scores as **test judge scores**, never as AI scores. Seeding is random; use
`ByeTeamId` in the JSON to identify the actual BYE team. Verify all fixture
records are absent after disposal.

The existing `SqlFixture.DisposeAsync` owns cleanup. It discovers all match,
round and team IDs through fixture-owned competition IDs, clears self-referencing
`NextMatchId` and `DebateSessionId`, then removes dependents in FK order and
verifies that owned rows are gone. Do not use DROP, TRUNCATE or global DELETE.
