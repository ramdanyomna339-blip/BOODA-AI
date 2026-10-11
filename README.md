# Booda

## Local media and phone browser access

New media exports are cataloged under an exact client/project scope. The desktop
`مخرجاتي` button and `/مخرجات` list that scope only and reject catalog paths outside
the expected output folder. Older uncataloged exports are not silently assigned
to a client or moved. Slideshow duration can be chosen from 0.5 to 5 seconds per image.

The desktop window now exports an SVG text poster from a fixed template and a
720x1280 silent MP4 slideshow from up to 20 local PNG/JPEG/WebP images. Video
export verifies the decoded frame count. These tools do not generate images,
perform unrestricted editing, add audio, publish content, or overwrite originals.

`start_mobile_workspace.ps1` serves a responsive local browser interface on
127.0.0.1:8765. Explicit `-Lan` binds the local network for a phone on the same
trusted private network. Enter the temporary session code printed on the laptop.
The code is not a model API key and is not saved. LAN mode is plain HTTP and must
not be exposed publicly or port-forwarded. Only scoped local commands are exposed;
project files cannot be browsed or downloaded through this server. This is browser
access, not a native iPhone app or an independently running phone assistant.

Custom local voice workers run with offline resource loading. Failed custom voice
synthesis tries installed Windows Egyptian Arabic speech; neither path downloads a
voice. Load and generation waits are each bounded to 120 seconds. Tests mock
playback, and waveform generation cannot establish subjective voice quality.

## Local workspace without a model or key

Run `start_local_workspace.ps1` (or `تشغيل بوده المحلي.cmd`) for the local desktop
window, menu 41 for the same window, or menu 40 for its text interface. These
provide decimal calculation, scoped reference search/inventory, dependency
inspection and reviewed teacher-pack import. They do not call a language model,
contact a service, or silently download dependencies. Changing the client/project
in the window clears previously displayed output.

Inside existing agent dialogue, `/مساعدة`, `/بحث query`, `/مراجعي`, `/جاهزية`, and
`احسب expression` also use these direct local commands. Lesson import in menu 40
uses `/تعليم path` or the desktop import button. It requires an exact match between
the pack scope and the selected workspace scope, explicit review, and an unchanged
pack hash after review. Teacher labels are declared, not authenticated; lessons
remain private references and do not train model weights.

`python -m tools.offline_workspace_acceptance` exercises the real local text
workspace on disposable clients. `python -m tools.check_local_window` opens a
hidden Tk window and checks actual callbacks and scope clearing. Neither proves
general model reasoning, visual usability, microphone quality or autonomous design.

## Free cloud checks and explicit context sharing

Menu 39 (or `python -m tools.check_free_gemini`) sends one fictional probe only
after the operator confirms the Google project is unbilled and approves the probe.
It asks for a hidden temporary key and saves only a redacted diagnostic report.
It does not retry, save provider response bodies, switch providers, or establish
general agent readiness. Billing eligibility is declared by the operator, not
verified by the application.

Gemini free sessions now register the existing guarded knowledge search,
campaign snapshot read and output review tools. Existing grants and plan approval
still apply. Local filesystem control remains separate. Remote conversation
history and retrieved reference excerpts each require separate session consent;
otherwise private content is withheld. Dialogue is limited to three short turns,
and source metadata excludes local paths. Structured personal memory remains
withheld. Google free-tier content may be used to improve its products.
Free sessions stop after 20 request attempts or a payload over 24KB; these are
application limits, not Google's actual quota or a monetary billing guarantee.

User policy in `config/ai_cost_policy.json` keeps paid AI disabled. No model or
framework download is required by these additions.

## Conversation retrieval and artifact review

Local conversation messages preserve literal Arabic inside the model's user text
(HTTP JSON escaping is separate). Local replies use a compact Arabic instruction,
bounded generation, and a repetition penalty. The server uses four threads at most
and smaller batch sizes (128/64) to reduce working memory. These settings improve
runtime behavior; they do not establish model reasoning quality.

`python -m tools.evaluate_local_brain` runs four real-model checks on disposable
fixtures and saves raw answers and timings in `outputs/brain_evaluations/`.
Local general plans use tool-specific JSON schemas. An explicitly named single
tool is bounded to one step; independent literal-input read/review tools cannot
invent dependencies. Schemas constrain structure, not the truth of arguments.
`review_output` compares supplied dimensions and literal text; it neither opens
images nor edits them. An Arabic input adapter copies explicitly labeled review dimensions/text directly
into the tool schema; ambiguous/unlabeled inputs are not inferred by that adapter.
The planner rejects generated arguments that differ from these copied fields.
This prevents the model from replacing a user's text with dimensions or examples.
Percentage evidence uses decimal arithmetic. A narrow
percentage-conflict guard reports the verified calculation and asks about the
unresolved agreement. These are system checks, not model training or evidence
of unaided model reasoning. Raw model responses are retained in evaluation reports.
Heuristic passes require human review: an answer can include the expected string
while also inventing facts. The October 10 real-model runs exposed timeouts,
hallucinations, and output-review failures; current installed models are not
validated as generally ready. No smaller model was silently adopted as default.

General local planners (including Ollama) now have guarded `search_local_knowledge`
and `read_campaign_snapshot` tools. Their `knowledge_read` and `campaign_read`
permissions start disabled; the normal reviewed plan and explicit grants are
required. Tool parameter schemas are shown to the planner. Snapshot reads use saved
local data, not live advertising accounts. Tool results enter conversational state
as private references and are recursively withheld from remote payloads, including
replanning context. Restricted local plan-artifact mode and Mock remain separate.

Starting a new goal clears recovery state. An existing plan cannot be silently
replaced by calling plan again. Replanning rejects the reuse of a capability with
an unresolved uncertain action (even under a new title); a different capability can
be proposed for review. Missing persisted tasks pause work rather than crashing.

Conversation turns retrieve structured memory, experience lessons, course material,
documents, and approved research using the current message, while preserving the
active goal and its project/client scope. Structured recall ranks matching records
before applying the return limit, so older relevant facts are not hidden by newer
unrelated entries. The main agent checks saved draft contents and plan artifacts;
verification exceptions stop dependent work as uncertain. These checks establish
file integrity, not semantic quality or completion of external objectives.

`python -m tools.teach_reference PATH_TO_REFERENCE.md` imports a reference and its
numbered teaching examples into existing local retrieval. The full source remains
historical/unverified, each excerpt carries its status, and candidate memories stay
in a separate review ledger rather than becoming confirmed personal facts. All
imported reference/lesson documents are private and excluded from remote planner
payloads. This is retrieval-based guidance, not model weight training. The importer
is repeatable by content hash. No permissions are granted by imported material.

## Advanced research, reviewed code evolution, and laptop connection

Research option **32 → 18** adds local-model semantic evidence classification,
validated against exact source quotations. Task execution automatically records
research exposure, terminal outcome and duration; numeric effects use actual prior
task results where an explicit measurement specification is available. Unknown
effects stay unknown, and observations are not causal proof.

Option **33** prepares or locally generates code drafts, binds source/test review
to a snapshot digest, executes regression tests in a staging directory, and permits
task-approved application and rollback. Staging is not an OS security sandbox;
unreviewed code/tests cannot be run by this workflow. Original code is retained,
live/staged edits invalidate adoption, and guard modules cannot self-modify directly.

Option **34 → 1** starts a scoped laptop file connection with read/write permissions,
task-bound approvals for writes, exclusive file creation, bounded UTF-8 reads and
path/secret/reparse-point guards. Local general planners can explicitly opt into scoped read tools with
`BOODA_LAPTOP_ROOT`; Mock, restricted local-plan mode and remote planners do not
automatically receive these tools. See [system usage guide](SYSTEM_GUIDE.md).

Option **34 → 2** adds separately approved desktop input, browser search/URLs,
supported app and media launch, local audio/video transcription, and temporary
screen observation with a visible pause/stop window. Each action needs a one-time
approval; viewing consent authorizes only the bounded viewing session. Vision
uses a separate loopback model and never executes its output. Run
`python -m tools.desktop_menu` with workspace-local dependencies, or install
`requirements-desktop.txt` in your environment. Model setup and operational
limits are documented in [SYSTEM_GUIDE.md](SYSTEM_GUIDE.md).
The observation window answers questions directly from local vision; a separate
checkbox requests a single-step proposal using the local text model. Desktop option
14 provides reviewed direct-vision answers; option 16 requests a text-model proposal.
Option 15 reviews a recent
proposal and requires a separate action approval. The model cannot approve or
execute its own proposals, and it does not invent mouse coordinates.

`python -m tools.system_smoke --local-model` provides a reproducible real-model,
code regression/apply/rollback and local file round-trip check on disposable
fixtures under `outputs/system_checks/`.

## Research and reviewed learning

Menu **32** opens a model-independent research workspace. It identifies research
needs from a question and failed/uncertain tasks, searches imported documents
offline, or searches the public Arabic/English Wikipedia API or general web.
Web discovery uses DuckDuckGo HTML with Bing RSS as a best-effort fallback;
provider blocks, changed markup, failed sources and empty results are reported.
Users may also supply a public HTTPS source URL directly. Online discovery sends
the entered topic, then requests public source pages; no profile, memory, API key,
or local document contents are sent. General web retrieval pins a validated public
DNS address, rejects internal/private addresses and credentials, and disables
redirects. Each connection has a 15-second timeout and both compressed and
decompressed responses are capped at 1 MB. Only text/HTML/XML is accepted.

Research sessions, source excerpts, retrieval dates, available revision dates,
and review decisions persist in `knowledge/research.json`. UTF-8 reports are
exported under `outputs/research/`. Users can propose a finding with source IDs
and an intended application, then explicitly approve or reject it. The interactive
search also extracts relevant verbatim sentences as pending proposals. Evidence
quotes must occur in their cited source. Comparisons detect exact matches and
user-classified supporting/contradicting evidence; publisher groups are an estimate,
not proof of independent corroboration. Semantic truth/contradiction detection
requires human review. Contradictory evidence blocks approval until resolved;
adding/removing evidence or correcting a claim requires a new review. Revision-age
labels flag sources older than 180 days without claiming that age proves truth.
Only approved, relevant findings enter planning and conversational context, with
source references and a recall limit. Approval is a human review decision, not a
claim of independent verification. Source text is reference data, never execution
authority. Remote planners exclude research knowledge by default; explicit opt-in
is `BOODA_SHARE_RESEARCH_WITH_REMOTE=1`, independent of structured-memory sharing.

Users can record an approved finding's application to a task with an observation
and an optional improvement outcome; numeric before/after metrics compute a delta
with an explicit higher/lower-is-better direction. Unknown outcomes stay unknown;
all observations remain user-reported, not causal proof. A summary reports known,
unknown and measured outcomes. An approved finding with an application can create
a traceable, idempotent proposal in the existing evolution workflow, starting at
`proposed`; sandbox/adoption still follow their existing permissions and approval
flow. No code is rewritten, tools installed, or model weights trained.
Applications retain the finding revision and statement snapshot; observations
from an older claim cannot support a new revision's improvement proposal.

Research updates reload state under a SQLite interprocess lock to avoid stale
manager instances overwriting each other. Review/correction history is retained;
research metadata events are recorded when an event log is supplied. Deleting a
session removes its recall data and report, but previously created evolution
proposals remain under the evolution workflow's separate lifecycle. The workspace
can also run independently with `python -m core.research_cli` (evolution proposal
creation is available through the main menu). See [Arabic usage guide](RESEARCH_GUIDE.md).

Provider interface references: [MediaWiki Search](https://www.mediawiki.org/wiki/API:Search)
and [TextExtracts](https://www.mediawiki.org/wiki/Extension:TextExtracts#API).

## AI agent

The menu's **19. Run AI agent on a goal** option uses a local Qwen model through
llama.cpp to make a 3–7 step plan, shows the plan for review, and then runs
approved steps through Booda's existing executor. Local plans use only the
`create_plan_artifact` capability, which writes the reviewed plan under
`outputs/plans/` and registers it with `BoodaArtifactManager`. It requires the
`save_file` permission and uses the normal approval flow when that permission's
risk level requires approval. It performs no publishing or external actions.
Arabic educational plans request level/prerequisites, ordered learning stages,
practical exercises, and progress tracking. Invalid local responses get one
correction request to the same model; if that also fails validation, Booda
reports the error without falling back to Mock.
Mock and remote-provider behavior remain separate.

For direct advertising-copy goals, the local provider uses Booda's bounded
offline ad-writing skill instead of loading a model. It produces a clearly
labeled first draft with placeholders for missing prices, product details, and
ordering information. The user reviews it before execution, and saving still
requires the existing `save_file` permission and executor checks. This is a
template-based skill, not AI-generated copy; strategy and learning goals still
use the configured planner.

For marketing campaign-planning goals, a second offline skill creates a
four-stage checklist covering objective and audience, the offer and message,
pre-publication review, and a measurable test. It does not claim market research
or invent performance figures. The plan is reviewed and saved through the same
`save_file` permission and executor flow.

Optional local model files live under `.local-ai-runtime/`; the runtime and
model are ignored by Git. Gemini Flash is now Booda's default AI provider. When
option 19 is selected, Booda asks for the Gemini API key in a hidden prompt if
it is not already present in `BOODA_GEMINI_API_KEY` or `GEMINI_API_KEY`; it
does not save the key. Before sending a request, it asks the user to confirm
that the Google AI Studio project has no linked billing account. A project
without billing remains on Google's free tier and will stop at its quota; Booda
does not switch to a paid model or another provider. Keep the project unlinked
from Cloud Billing to avoid charges. Google's current pricing page lists a free
tier for Gemini 3.8 Flash, with limited rate limits, and says free-tier prompts
may be used to improve Google products. [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing)
· [OpenAI-compatible endpoint](https://ai.google.dev/gemini-api/docs/openai)
· [Billing tiers](https://ai.google.dev/gemini-api/docs/billing/).

To explicitly force local mode, select it in PowerShell:

```powershell
$env:BOODA_AI_PROVIDER = "local"
python -m core.main
```

To use a model already installed in Ollama instead, select the Ollama provider.
It connects only to the local Ollama service, defaults to the local
`qwen3.5:4b` model, and never reads an API key. The model must already be downloaded in
Ollama; models ending in `:cloud` use Ollama's cloud service and are not selected
by this default. This mode can write a content draft using the existing
`save_task_content` capability after plan review and the normal `save_file`
permission/approval checks. It does not publish or send anything:

```powershell
$env:BOODA_AI_PROVIDER = "ollama"
python -m core.main
```

For a different installed local model, set `BOODA_OLLAMA_MODEL` to its exact
Ollama name. The optional local service address is `BOODA_OLLAMA_BASE_URL` and
defaults to `http://127.0.0.1:11434/v1`.

To send a standalone Arabic smoke-test request to the real local model, display
its response, and stop the server started by the test:

```powershell
python -m core.local_model
```

## Approval storage and execution

The application passes `security/approvals.json` as the legacy approval-state
path. `BoodaApprovalManager` stores current state transactionally in the adjacent
`security/approvals.json.sqlite3` database. On first startup with a legacy JSON
file, it creates `approvals.json.bak`, imports the records in a SQLite
transaction, then atomically replaces the old JSON content with `{}` so an
older application version cannot reuse an approval that SQLite has consumed.
The backup and SQLite database retain the original approvals; a conflicting or
invalid migration stops startup and leaves the source file untouched. Stop all
older Booda processes before this first startup; an already-running old process
may still hold approvals loaded from its in-memory JSON snapshot.

Approval claims use a conditional SQLite transaction shared across processes.
The persisted lifecycle is `pending/available → reserved → executing →
completed`, with `failed` for a known pre-action failure and `uncertain` when
the process or external action outcome cannot be confirmed. Reserved approvals
are never automatically released. If `BoodaApprovalManager` is constructed
without a file path, it uses an in-memory database for isolated/test usage and
does not provide persistence across restarts.
An action exception is surfaced as an `uncertain` task and audit outcome; the
Agent does not automatically repeat it or proceed with dependent work.

This command binds only to `127.0.0.1:8080`. The server lifecycle is managed
for the duration of the AI session or smoke test; a server already running
before the command is reused and is not stopped by Booda. Missing assets,
startup failures, and model-load diagnostics are reported without falling
back to Mock.

## Offline local knowledge

Choose main-menu option **29** to import PDF, TXT, or Markdown documents, search
their extracted text, list imported sources, or delete a source and its chunks.
The importer is local-only, accepts UTF-8 text, preserves PDF page numbers,
avoids duplicate content, and rejects scanned PDFs when no text can be
extracted (OCR is not included). Documents are limited to 20 MiB.

Imported text and source metadata are stored in
`knowledge/local_documents.json`. Relevant excerpts are supplied to the
planner and conversational model with source/page details; they are context,
not model training. PDF support is provided by `pypdf` in `requirements.txt`.

Choose main-menu option **30** for the offline marketing course. Each lesson
appears before a three-question quiz; at least two correct answers pass the
lesson. A practical project response is saved with its lesson. Attempts,
scores, submissions, lesson states, and course progress are stored in
`knowledge/learning_paths.json`. This uses fixed local content, not an LLM,
and quiz answers are not included in material recalled for the Agent.

The optional local model files include
`.local-ai-runtime/models/Qwen3-4B-Q2_K.gguf`. To choose another
model explicitly, set `BOODA_LOCAL_MODEL_PATH` to an absolute path or to a path
relative to the Booda project root. A missing configured path is reported with
the available GGUF filenames; Booda does not silently select another model.

For a deterministic demo without a model or network connection, explicitly
select the Mock provider in PowerShell before starting Booda:

```powershell
$env:BOODA_AI_PROVIDER = "mock"
python -m core.main
```

Mock plans and saved drafts are labeled `Demo / Mock`; they are fixed examples,
not AI-generated content. The plan still requires review and the normal
permission and approval checks. Mock mode only uses `save_task_content` and
does not read API-key settings, contact external services, or start the local
model server. Remove the setting with
`Remove-Item Env:BOODA_AI_PROVIDER` to return to the existing provider behavior.

Other remote model endpoints remain blocked unless `BOODA_ALLOW_PAID_API=1` is
set explicitly. If that opt-in is used, configure `BOODA_LLM_BASE_URL`,
`BOODA_LLM_MODEL`, and an API key in the environment. This can incur provider
charges. Gemini mode uses only Google's Gemini endpoint and a separate API
key; its free-project confirmation does not enable this paid-endpoint opt-in.

The user reviews every plan before execution. Booda pauses when a permission or
approval is needed; grants and approvals go through the existing managers and
are recorded in the audit log. Goal events can be recalled from
`memory/agent_memory.jsonl`.

## Projects and task scheduling

Create projects from menu option 20, then attach tasks to them from option 11.
Project data is saved in `memory/projects.json`; linked task ids and due dates
are saved in the existing `memory/tasks.json` file. Task due dates accept an
ISO 8601 date (`2026-10-22`, treated as the end of that local day) or timestamp
(`2026-10-22T17:00:00+03:00`). Option 21 lists projects and their task counts;
option 22 shows overdue tasks and tasks due within the next seven days.

The scheduler reports due work when option 22 is selected. It does not send
background notifications yet.

## Core foundation APIs

`BoodaAgent` is the core orchestrator. It accepts a `BoodaGoal`, creates a
validated dependency-aware plan, persists its tasks, and runs capabilities
through the existing permission and approval checks.

The supporting managers are intentionally separate so their storage and
interfaces can be changed without replacing the orchestrator:

- `BoodaGoalManager` stores goal context and lifecycle status in
  `memory/goals.json`.
- `BoodaProjectManager` and `BoodaTaskManager` store project/task state;
  tasks can retain goal and project ids plus due dates.
- `BoodaLearningManager` stores learning paths, unit progress, and assessment
  history in `knowledge/learning_paths.json`.
- Booda seeds five curated, local marketing topics and retrieves relevant material
  into the planner context for matching goals. This is prompt-time guidance, not
  model training or a claim of personal experience; no network is used.
- `BoodaToolRegistry` holds executable callables. `BoodaCapabilityRegistry`
  stores the separate capability manifest and required permission in
  `security/capabilities.json`; plans must match that permission.
- `BoodaMemory`, `BoodaEventLog`, and `BoodaAuditLog` provide goal memory,
  domain event history, and security audit history.
- `BoodaAgentSessionStore` saves the active plan and decision history in
  `memory/agent_sessions.json`. Restarted work resumes from its saved plan;
  an action interrupted after it started requires an explicit retry decision.
- `JsonlBoodaMemory` keeps append-only goal events. Explicitly confirmed facts,
  preferences, project/client records, decisions, lessons, and expiring notes
  are stored separately in `memory/structured_memory.sqlite3` by
  `BoodaStructuredMemoryStore`. The SQLite store never imports legacy JSONL
  fact records. It distinguishes approved entries from pending proposals,
  scopes project and client data, and supports explicit approval, correction,
  withdrawal, and deletion. Credential-like data is rejected and memory
  contents are supplied as untrusted reference data, never as instructions or
  authority. The planner receives only relevant approved entries plus
  separately labeled proposals; memory grants no permissions. Remote planners do
  not receive structured memory unless `BOODA_SHARE_STRUCTURED_MEMORY_WITH_REMOTE=1`
  is explicitly set. Local planning can use it without network access.
- Failed work can be replanned up to three times. Revised steps receive new
  ids, completed work cannot be repeated by the revised plan, and each new plan
  must be explicitly approved before execution.
- `BoodaArtifactManager` indexes output files in `outputs/artifacts.json`.
- `BoodaJobManager` persists safe named jobs in `memory/jobs.json`;
  `BoodaJobRunner` runs them only when the application explicitly invokes it
  with registered handlers. No worker runs automatically in the background.
- `BoodaVersionStore` records append-only snapshots in
  `memory/versions.jsonl`. Goals, projects, and tasks use it when the main
  application constructs their managers.

## User profile and preferences

Booda stores a local default profile and scoped preferences in UTF-8 JSON at
`memory/user_profile.json`. The application currently serves one local default
user and has no multi-user authentication. `BoodaUserProfileManager` exposes
profile updates and preference create/update/deactivate operations for
`user`, `project`, and `task` scopes; every change is recorded by the existing
audit and event logs when those managers are supplied.

The initial profile uses `ar-EG` and Egyptian colloquial Arabic, with
`avoid_unrequested_age_restriction_labels=true`. `BoodaContextBuilder` adds
the profile and applicable preferences to the existing goal memory passed to
the planners. System safety, permissions, and output schemas remain
authoritative; the current explicit request takes precedence over preferences.
Among preferences, explicit values take precedence over imported, inferred,
and system defaults; a more specific scope wins within the same source, and a
temporary value wins over a persistent value at equal source and scope.
Secret-like preference keys are not included in planner context.

Choose main-menu option **27** to manage preferences. The submenu lists all or
active preferences, filters project-scoped preferences, adds/edits/deactivates/
reactivates/deletes entries, promotes imported or inferred entries to explicit,
and adds temporary task-scoped instructions. Temporary session-scoped entries
are not supported by the current preference scopes. CLI value input accepts
Arabic text or JSON scalar/object values; secret-like keys and recognized
credential-shaped values are rejected, and sensitive-looking stored values are
redacted from listings. Preference mutations use the existing profile manager
and are recorded in the existing audit and event logs.

Choose main-menu option **31** to manage structured memory. Adding confirmed
memory requires a separate confirmation; suggestions stay pending until
explicitly approved. Users can review records, reject or withdraw them, correct
approved records, and permanently delete records. Temporary entries require an
ISO 8601 expiry timestamp. The structured store records metadata in the audit
log without recording memory values.
- `BoodaEvolutionManager` stores task experiences, outcome-only evaluations,
  traceable lessons, capability gaps, improvement proposals, local knowledge,
  and change history in `memory/evolution.json`. Task results are recorded
  locally; unknown quality, speed, cost, and privacy metrics remain unset.
- Failed task outcomes create a review-only improvement proposal from the
  recorded evidence. Missing registered capabilities create a gap record;
  neither action changes the tool or capability registry.
- Proposals must pass `proposed → sandbox → approval → adopted`. The sandbox
  records a local validation report and does not execute code. Adoption and
  rollback require the high-risk `evolution_change` permission and a
  task-bound approval. Adoption changes proposal records only; it never
  changes code, installs tools, or registers capabilities. Rollback restores
  the last sandboxed proposal snapshot.

Menu options 23–25 create, list, and update goals. New state uses separate
files, leaving existing task, permission, approval, memory, and audit data in
place.

Menu option 26 shows a local dashboard with goal, project, and task status
counts plus overdue and upcoming tasks. It uses saved project data and does not
need an AI model or network access.

Choose main-menu option **35** for the advertising intelligence workspace. It
can analyze campaign periods entered manually or imported from Booda's template
and common Meta Ads Manager and Google Ads campaign-report CSVs, review saved
history, and export all snapshots and derived metrics to CSV. Google Ads
supports CSV downloads from campaign tables and reports
([Google Ads Help](https://support.google.com/google-ads/answer/2404036)). The
Booda template lists the accepted columns; dates use `YYYY-MM-DD`, currency is a
three-letter code, and conversions, revenue, and targets are optional. For
exports without a date column, Booda asks for the report period. Booda
calculates CTR, CPC, CPM, conversion rate, CPA, and ROAS where inputs permit;
judges performance only against targets you provide; compares repeated periods
for the same campaign; and keeps observed signals distinct from hypotheses and
suggested experiments. Optional creative copy gets a transparent keyword
checklist for CTA, offer, benefit, trust, and urgency; absolute claims are
flagged for human review. This is not an AI quality score. A Meta `Results`
column is labeled as an unverified conversion measure because its meaning
depends on campaign setup. Booda does not infer general platform benchmarks or
claim a suspected cause is proven. This reads exported files and does not sign
in to ad accounts. Data, imports, exports and reports stay on this
computer in `knowledge/ad_intelligence.json` and `outputs/ad_intelligence/`;
manual entry and CSV import require no network request or AI key. Reports are
catalogued as local artifacts.

Options **35 → 6** and **35 → 7** can fetch Meta Ads and Google Ads campaign
reports directly in read-only mode. Meta requests only campaign insights; Google
uses `SELECT` report queries. Booda never stores the tokens: Meta's access token
and Google's OAuth refresh token, client secret, and developer token are read
through hidden terminal prompts and sent only to the respective official API
endpoints. Meta requires an access token with `ads_read`; see the
[Marketing API Insights guide](https://developers.facebook.com/docs/marketing-api/insights).
Google requires OAuth credentials, a developer token, and the `adwords` OAuth
scope ([Google Ads API auth](https://developers.google.com/google-ads/api/rest/auth)).

Choose main-menu option **36** for the read-only integrations center. It can
read public YouTube channel metadata through `channels.list` (1 quota unit per
request) and up to 20 recent public TikTok videos for an authorized account.
YouTube public channel lookup needs a Google Cloud API key; TikTok needs an
approved developer app, account consent, and the `video.list` scope. The
credentials are requested hidden at runtime and are not stored. Facebook and
Instagram ad reports and Google Ads reports are available under option **35**.

The integrations center documents the setup status for X, ChatGPT, Gemini, and
Manus. X's API and AI-provider APIs may consume paid credits; a ChatGPT
subscription does not automatically include API use. Gemini has limited free
tiers for some models. Booda does not call or enable any of those services
without a configured provider. No publishing or account changes are available
through these integrations.
Google states that the API itself has no usage charges at its access levels,
though developer-token access is subject to its setup and review requirements
([access levels](https://developers.google.com/google-ads/api/docs/productionize/access-levels)).
Live account reads require the account owner's authorization and credentials;
tests use mocked API responses and do not contain or need real account secrets.

Choose main-menu option **37** for a local voice session. Start Booda with
`./start_desktop.ps1` so it uses the bundled Python 3.12 speech libraries.
Booda records up to twelve seconds from the default Windows microphone, runs the
existing multilingual Whisper tiny model on this computer, displays the
transcript, and waits for you to type `نعم` before planning. The audio stays in
memory and is not saved or sent to a service. The normal plan review, permission,
and approval checks still apply. Booda can also read its plan and replies aloud
using the local Piper Arabic voice when its model is installed, with Windows
Speech Synthesis as a fallback. The Piper model is downloaded separately and
speech is synthesized in memory; replies are not sent to a cloud service.
