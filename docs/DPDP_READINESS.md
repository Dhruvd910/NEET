# DPDP readiness: briefing for legal review

**Status:** prepared by engineering for counsel. This is **not legal advice** and not a compliance opinion.
It describes what the platform does with personal data, what has been built, and the open questions that need
a qualified lawyer's answer. Most users are NEET aspirants aged 16–19, so many are children under the
Digital Personal Data Protection Act, 2023 ("the Act"). The Act defines a child as under 18.

Ask counsel to confirm which provisions of the Act and of the Digital Personal Data Protection Rules, 2025 are
in force on the planned launch date. The Rules were notified with obligations phased in over time.

## 1. Data inventory

| Data | Source | Purpose | Where stored | Retention (current) |
|---|---|---|---|---|
| Email, password hash (scrypt) | Student | Account | `users` | Until deletion |
| Under-18 flag (self-declared), guardian email | Student | Children's-data rules | `users` | Until deletion |
| Guardian name, relationship, IP at consent | Guardian | Record of consent | `consent_records` | Until account deletion |
| Profile: class, state, domicile, preferences, budget | Student | Guidance | `student_profiles` | Until deletion |
| Category, sub-category, PwD status (optional) | Student | Only to compare with the matching cutoffs | `student_profiles` | Until deletion |
| NEET rank / estimated rank range | Student | Predictor | `exam_profiles` | Until deletion |
| Mock-test scores, weak topics | Student | Analytics | `mock_tests` | Until deletion |
| Saved colleges, comparisons, draft preference lists | Student | Planning | several tables | Until deletion |
| Assistant chats | Student | Answering questions | `chat_sessions/messages` | Until deletion |
| Practice-test answers, timings, "left the test window" count | Student | Scoring and analysis | `exam_attempts`, `exam_attempt_items` | Until deletion |
| Syllabus progress and study plan | Student | Planning | `chapter_progress`, `study_plans`, `study_tasks` | Until deletion |
| College reviews | Student | Moderated reviews | `student_reviews` (author set null on deletion) | Indefinite |
| Request logs: method, path, status, timing, request id | System | Operations | Log storage | Set by log retention |
| Backups | System | Recovery | Off-host storage | 14 days rolling |

The platform does not use advertising, analytics trackers, third-party cookies or behavioural profiling.
Category and PwD data are optional and labelled private in the UI.

## 2. Processors and transfers

| Processor | Data sent | When |
|---|---|---|
| Hosting provider (VM, backups) | Everything | Always |
| Email provider (SMTP) | Guardian email, student email in the message | Guardian consent |
| OpenRouter, routing to the model provider (default Anthropic Claude Haiku), if `OPENROUTER_API_KEY` is set | The question and tool results, which can include the student's own profile and ranks. Requests set `data_collection: deny` | Assistant use (text and voice) |
| Anthropic (Claude API), if `LLM_PROVIDER=anthropic` | Same as above | Assistant use |
| The student's browser speech service (Google in Chrome, Apple in Safari) | The student's voice. This goes directly from the browser; our servers receive only the text | Voice input |
| Voyage AI, if `VOYAGE_API_KEY` is set | Text of official documents and the student's search query | Semantic search |
| OpenStreetMap / Overpass | College coordinates only (no personal data) | Admin refresh |

These involve cross-border transfer. Counsel should confirm the position under section 16 and the processor
contracts (section 8(2)).

## 3. What is built

**Notice and consent (sections 5, 6)**
- Sign-up requires accepting the privacy notice. Each acceptance is stored in `consent_records` with the
  notice version (`PRIVACY_NOTICE_VERSION`).
- The current notice text is a short summary in the sign-up form and on the guardian page. **A full privacy
  notice is still to be drafted** (see open questions).

**Children (section 9)**
- Students who say they are under 18 must name a parent or guardian's email.
- The account is created but **locked**: no profile, ranks, mock tests, chats or saved items can be stored
  until the guardian acts. This is enforced server-side for every personal-data endpoint.
- The guardian receives a single-use link, valid 72 hours. It shows what is collected and why, asks for their
  name, relationship and a declaration that they are the parent or legal guardian, and records approval or refusal.
- Unanswered or refused accounts are deleted after 7 days by `python -m app.maintenance purge-unconsented`
  (scheduled daily).
- There is no tracking, behavioural monitoring or targeted advertising of any user.
- Existing minor accounts from before this feature were switched to "pending" by the migration, because a
  checkbox is not verifiable consent.

**Rights (sections 11–13)**
- Access and portability: `GET /api/auth/me/export` (button on the profile page). It includes consent records.
- Erasure: `DELETE /api/auth/me` deletes the account and all linked data (database cascades). It is on
  the profile page and, for accounts still waiting for guardian consent, in the consent banner.
  Reviews keep their text, with the author removed.
- Correction: every profile field is editable.

**Security safeguards (section 8(5))**
- HTTPS only; httpOnly SameSite=Lax session cookie; signed double-submit CSRF tokens.
- scrypt password hashing; rate limits on sign-in, sign-up and consent endpoints (shared through Redis).
- Role-based admin access, with every admin change written to an audit log.
- No personal data in URLs or logs. The guardian token in the consent link is stored only as a hash.
- The production configuration refuses to start with development secrets, insecure cookies or SQLite.

## 4. Open questions for counsel

1. **Verifiable consent method.** Is an emailed link plus a self-declaration "verifiable" consent under the
   Rules? The Rules refer to reliable identity and age details, or a virtual token from an authorised entity
   (e.g. DigiLocker). If email is insufficient, which method should be integrated?
2. **Age assurance.** Age is self-declared. What diligence is expected to detect an under-18 student who
   says they are an adult?
3. **Guardian withdrawal.** A guardian can refuse but has no self-service way to withdraw consent later.
   Is "contact the grievance officer" acceptable, or is a guardian dashboard needed?
4. **Privacy notice.** Full text: purposes, the data list above, rights, the grievance officer, how to
   complain to the Data Protection Board. In which languages (section 5(3))? Shown again when it changes?
5. **Grievance officer / contact person.** Name and contact to publish, and response time.
6. **Retention.**
   - How long to keep inactive adult accounts?
   - How long to keep consent records after an account is deleted (they currently cascade-delete)?
   - Is the 14-day backup retention acceptable?
7. **Sensitive inputs.** Category (caste) and disability data are optional and used only for cutoff
   matching. Any additional safeguards or explicit consent wording required?
8. **LLM processing.** Is sending a student's question and their own profile to the Claude API, outside
   India, acceptable with notice? Should the assistant be off for minors by default?
9. **Breach response.** Who notifies the Board and affected users, and in what timeframe? A runbook is still
   to be written.
10. **Significant Data Fiduciary.** Is a notification as an SDF likely at the expected scale?
11. **Third-party data.** Terms-of-use reuse of official counselling data (tracked per source in /admin → Sources).

## 5. After sign-off

Set `DPDP_REVIEW_REFERENCE` to the review memo or ticket id. The admin readiness check then shows the item as
done. Add the agreed notice text, update `PRIVACY_NOTICE_VERSION`, and implement any changes counsel requires.
