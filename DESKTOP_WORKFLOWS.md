# Reviewed desktop workflows

Launch the Arabic interface with `start_desktop.ps1`, then choose 34, connection type 2.

Inside the desktop menu:
- 35 prepares a supported natural-language request and displays its steps without executing them.
- 36 reviews one next step. Each step requires a fresh, single-use approval and result confirmation.
- 37 saves an explicitly approved correction; 38 recalls approved corrections as context, never commands.

Supported examples: `اكتب في المفكرة: اختبار بودا`, `ابحث عن تعلم العربية`, `افتح الفيديو ولخصه https://youtu.be/iG9CE55wbtY`, and `اقرأ الشاشة`.

These are bounded templates, not a general autonomous planner. Opening Notepad may restore documents: confirm a blank document before approving typing. Automatic text verification must report success; human confirmation cannot override a failed automatic check.

Video excerpts are verbatim samples from available captions, not a comprehensive semantic summary or audio transcription. Saved corrections use lexical similarity and reviewed memory, not model-weight training. Screen answers expose OCR evidence separately from vision answers; neither grants action permission.

## Verification on 2026-10-11

- Latest full suite after separating Unicode press/release: 637 passed (31.17 seconds).
- Integrated workflows: real approval executor, persistence and public Arabic YouTube captions; window actions and human result confirmations simulated.
- Actual Booda UI opened a new blank Notepad window with explicit user approval.
- Initial approved Arabic typing displayed the first word followed by dots. Added 20 ms pacing between UTF-16 units. The next native attempt stopped after `اختبار ب`: Notepad automatically changed its caption, invalidating the strict title check. During typing only, the guard now retains the approved foreground window handle, process and bounds while allowing caption changes. The initial approval still checks the complete target.
- The latest separately approved native attempt completed sending without interruption, but live editor accessibility returned `اختبار ودا:كل خطوة بموافقتي.` instead of `اختبار بودا: كل خطوة بموافقتي.`. Arabic input is therefore still not exact and must not be reported as passing. No file was saved; no automatic retry was performed. Tests cover title changes, foreign-window/process/bounds rejection, UTF-16 packets, key release and partial-send failure, but do not establish native character fidelity.
- Follow-up fix: send Unicode key-down and key-up separately, holding for 50 ms and leaving a 50 ms release gap. An accepted press is released even if the hold is interrupted; failed sends/releases stop without retry. In a fresh, explicitly approved single attempt through the actual Booda UI, the editor accessibility value was exactly `اختبار بودا: كل خطوة بموافقتي.`. All letters, spaces and punctuation matched. No document was saved. This supersedes the failed attempt above for this exact Notepad test; reliability across other applications still needs separate practical tests.
- Saved Arabic OCR fixture was read as `اختبار بودا` and `Booda 123`, confidence 92. This does not establish accuracy across applications.
- Local vision replay answered calculator result 4 in about 16 seconds; no general accuracy claim or stronger-model installation.
- Local Git baseline created. No GitHub remote or upload. Runtime data, screenshots, permissions, secrets and model files are excluded.
