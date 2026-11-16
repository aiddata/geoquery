# Mini-feedback prompts: design

**Status:** draft for review · 2026-11-12
**Mockup:** https://claude.ai/artifact/U3S7KtUaREAUmtWwZNHxKi

## Goal

Ask visitors one short question at the moment it applies, for example "Did you find the boundaries you were looking for?" right after they pick boundaries. A question should take one tap to answer, be easy to ignore or dismiss, and let people opt out for good. The answers show us where the site falls short.

## Decisions already made

1. Build it into GeoQuery (Django plus Svelte), not with a third-party survey tool.
2. Questions live in a YAML file in the repo. A sync step loads that file into a table.
3. Cadence starts at about every third visit, with at least a week between questions. Both numbers are settings.
4. Every visitor is eligible unless they opt out.
5. Results are read in the Django admin, with CSV export. No in-app results page for now.

## Question catalog

The questions are defined in `backend/feedback/questions.yaml`:

```yaml
- key: boundaries_found          # stable id; change the key when the meaning changes
  moment: boundaries_selected
  kind: yes_no                   # yes_no | scale | text
  prompt: Did you find the boundaries you were looking for?
  labels: {yes: "Yes", no: "Not quite"}
  followup: What were you looking for?
  followup_on: [no]              # answers that open the follow-up box; omit for none, "any" for all
- key: zoom_sufficient
  moment: boundaries_selected
  kind: yes_no
  prompt: Was zooming and panning enough to find your area?
  followup: What got in the way?
  followup_on: [no]
- key: dataset_metadata
  moment: dataset_options
  kind: scale                    # 1–5
  prompt: How well does this page describe the dataset?
  labels: {low: "Not enough", high: "Everything I need"}
  followup: What's missing?
  followup_on: [1, 2, 3, 4]
- key: dataset_wishlist
  moment: request_submitted
  kind: text
  prompt: Is there a dataset you wish GeoQuery had?
  placeholder: e.g. flood extent, school locations
```

A question can also set `active: false` to pause it.

**Sync.** The `sync_feedback_questions` management command upserts rows by `key`.
- It runs from a `post_migrate` handler in the `feedback` app. The deploy job already runs `migrate`, so no Helm change is needed.
- A key that has been removed from the file is marked `active=False`, not deleted, so its past responses keep their question.
- The command validates the file and stops with an error on any of these:
  - an unknown `kind` or `moment`
  - duplicate keys
  - `labels` or `followup_on` values that don't match the kind
- Each response stores a snapshot of the prompt text. Small wording fixes can therefore reuse the key; a change in meaning should get a new key.

## Moments

| Moment | Page | When it fires |
|---|---|---|
| `boundaries_selected` | `/` | The selection is non-empty and hasn't changed for 4 seconds |
| `dataset_options` | `/customize` | A dataset has been open for 10 seconds |
| `request_submitted` | `/review` | The request was submitted successfully |
| `request_results` | `/requests/<id>` | The request is complete (no questions in v1; the moment is reserved) |

A page calls `askFeedback(moment, context)` and nothing else. The prompt module decides whether a question actually appears.

## Who gets asked, and how often

The rules run in the browser. State is kept in `localStorage` under the key `geoquery-feedback`:

```ts
{ clientId: string,        // random UUID, sent with responses; not linked to identity
  visits: number,          // incremented once per browser session (sessionStorage flag)
  lastAskedAt: string|null,
  seen: Record<string, 'answered' | 'dismissed'>,
  optedOut: boolean }
```

A question is shown only when all of these hold:
- the feature is enabled;
- the visitor hasn't opted out;
- `visits ≥ every_n_visits`, and `visits` is a multiple of it;
- `lastAskedAt` was at least `min_days_between` days ago;
- nothing has been asked yet this visit;
- the moment has an active question whose key isn't in `seen`.

When several questions match, one is picked at random, weighted by `weight` (default 1).

The settings are environment variables, read like the throttle rates are:

| Setting | Env var | Default |
|---|---|---|
| Enabled | `FEEDBACK_ENABLED` | `true` |
| Ask every N visits | `FEEDBACK_EVERY_N_VISITS` | `3` |
| Minimum days between questions | `FEEDBACK_MIN_DAYS_BETWEEN` | `7` |
| Questions per visit | `FEEDBACK_MAX_PER_VISIT` | `1` |

"Answer another" is the visitor's own choice, so it skips the per-visit limit. It still never repeats a question in `seen`.

**Opting out** sets `optedOut` in the browser. For signed-in users it also sets `User.feedback_opt_out`, so the choice follows them across devices; the questions endpoint returns that flag and the client respects it. A "Feedback questions" switch in the Help panel turns them back on.

If storage is unavailable (private mode, blocked storage), no questions are shown.

## The prompt card

`FeedbackPrompt.svelte` is mounted once in `+layout.svelte`:

**Placement**
- It's a fixed card, 320px wide, at the bottom-left of the content area. On `/` it sits just right of the sidebar.
- The existing support banner keeps the bottom-right corner.
- Below 640px wide it spans the full width with a 16px gutter. At that width it doesn't appear while the support banner is showing.

**Behaviour**
- No modal, no focus stealing, no sound.
- Escape dismisses the card when focus is inside it.
- With `prefers-reduced-motion`, it appears without sliding in.

**States** (see the mockup)
- Asked: the prompt, the answer controls, and "Don't ask me again".
- Answered: the answer is saved on tap. If the answer is in `followup_on`, an optional text box and a Send button appear.
- Thanks: closes by itself after 6 seconds and offers "Answer another".
- Opted out: "We won't ask again", with Undo.

**Accessibility**
- The card is a labelled `section`.
- The 1–5 scale is a `radiogroup`.
- Text inputs have real labels.
- Icon buttons have an `aria-label`.

## Backend

There is a new `feedback` app.

**Models**

`FeedbackQuestion` fields:
- `key`, which is unique;
- `moment`, `kind`, `prompt`;
- `options`, a JSON field holding the labels and placeholder;
- `followup`, `followup_on`;
- `weight`, `active`, `updated_at`.

`FeedbackResponse` holds one row per question shown. Its fields:
- `id`: a UUID.
- `question`: a foreign key with `PROTECT`.
- `prompt`: the snapshot of the prompt text.
- `status`: `shown`, `answered`, `dismissed` or `opted_out`.
- `answer`: `"yes"` or `"no"`, `"1"` to `"5"`, or text of at most 500 characters.
- `detail`: the follow-up text, at most 2,000 characters.
- `path`.
- `client_id`.
- `user`: nullable; set when the visitor is signed in.
- `request`: nullable; set for the `request_submitted` and `request_results` moments.
- `created_at`, `updated_at`.

`accounts.User` gains `feedback_opt_out`, a boolean defaulting to false.

**Endpoints** (under `/api/feedback/`)

`GET questions/`
- Returns the settings and the active questions grouped by moment.
- Anonymous visitors get a short cache; signed-in visitors also get their opt-out flag.

`POST responses/`
- Body: `{question, client_id, path, request?}`.
- Creates a row with status `shown` and returns its `id`.
- It is sent when the card appears, so the share of people who ignore or dismiss a question can be measured.

`PATCH responses/<id>/`
- Body: `{status, answer?, detail?}`.
- `client_id` must match the row, otherwise the server returns 404.
- The answer is checked against the question's kind.
- If the status is `opted_out` and the visitor is signed in, the user's flag is also set.

`PUT opt-out/`: for signed-in users, to toggle the flag from the Help panel.

All of these use a new throttle scope `feedback`, `THROTTLE_RATE_FEEDBACK`, defaulting to `120/hour`.

**Admin**
- The question list shows counts of shown, answered and dismissed responses. It also shows "yes" % for yes/no questions and the mean for scale questions, computed with annotations.
- The response list:
  - filters by question, moment, status and date;
  - searches `answer` and `detail`;
  - has an "Export selected as CSV" action.

## Privacy

- The data has no identifying fields beyond what the visitor already gave us. `client_id` is random. `user` and `request` are set only when the visitor is signed in or the response is tied to a request.
- Free text can contain anything, so only staff can see it, in the admin.
- The cookie and privacy wording doesn't change, because `localStorage` is used only for this feature's own state.

## Testing

**Backend**
- Sync: creates, updates, deactivates, and rejects invalid YAML.
- Answer validation for each kind.
- `client_id` ownership on PATCH.
- Opt-out sets the user flag.
- Throttle scope wiring.
- Admin aggregates and CSV export.

**Frontend** (`bun test`)
- The eligibility function as a pure function of state, settings and time:
  - visit counting;
  - the days-between gap;
  - `seen` exclusion;
  - opt-out;
  - the per-visit limit, and "Answer another" bypassing it;
  - storage being unavailable.

## Out of scope for v1

- An in-app results page.
- Translations.
- Targeting by user segment.
- A/B variants.
- Questions for `request_results`; the moment exists, but no questions use it yet.
