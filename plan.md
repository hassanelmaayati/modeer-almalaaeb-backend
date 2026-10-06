# Modeer Almalaaeb — simple plan

An English-first desktop/mobile website for activities in Bahrain. The backend is implemented; this page records the rules it follows and what is still planned.

The shared idea and wireframes remain the sources. The build uses eight tables and includes friends, groups, direct messages, cups and notifications.

## Models

1. **User:** accounts, profiles, home district and an optional Google link. There are no roles or admin accounts.
2. **Sport:** activities and format presets. Each sport's cup format (knockout, race or none) is derived on the server.
3. **Room:** schedule, venue point/privacy, capacity, JSON slot layout and cancellation record.
4. **Membership:** room/group members, friend connections and cup rosters.
5. **Message:** room chat, group chat, direct message or system notice.
6. **Group:** social group or persistent cup team.
7. **Cup:** registration, team snapshots, knockout bracket or race results.
8. **Notification:** per-user notices and read state.

Membership has no `kind` column; the row type follows from which target is set. A friend row stores one user pair and one Boolean block flag per side. Room slots and cup entries/fixtures are JSON data, validated inside locked transactions.

## Rules to keep

- Seeded sports: football, basketball, padel, swimming, walking together, running, cycling, handball, billiards and kayak. Outings use pools with optional distance, pace and route notes. Walking has no cups.
- Public browsing; accounts for participation. Verify Google server-side and authenticate the existing account before linking.
- Accepted room members, including the host, count toward capacity. Pending requests reserve nothing; approval comes before slot selection.
- Store UTC; display Bahrain time.
- At 15 minutes before start, remove discovery listings and reject all admission. Freeze schedule/venue/capacity changes and ordinary cancellation. Emergency cancellation needs a reason and participant notice.
- Start/end automatically. Assign unslotted accepted players in admission order, then team/slot order; pools use ordinal.
- Completion is not attendance. The host records attendance and rates present players (1–5); no self-rating.
- Protect exact meeting/booking details across previews and messages. Group membership or invitations never bypass room admission rules.
- Friend/group/cup invitations require consent. Direct sending requires an accepted, unblocked friendship; old DM history remains readable after unfriend/block. Each user sees only their own block.
- Cup writes carry the revision the client last read; stale writes and invalid state changes return 409.

## Implementation phases

1. **Foundation** — done: models, Alembic migrations, accounts, Google sign-in/linking, profiles and the sports catalogue.
2. **Rooms** — done: discovery, creation, approval, slots/pools, privacy, host controls, the lifecycle worker (inside the app process) and in-memory WebSocket hubs with socket tickets.
3. **Community and after-game** — done: friends, blocks, direct/room/group messages, groups/teams, consent-based invitations, attendance, host ratings and notifications.
4. **Cups** — done: team entries, rosters, locked 4/8/16-team knockout brackets and race results.
5. **Verification** — done: an offline test suite on isolated PostgreSQL/PostGIS runs in CI before every deploy.

**Deployment inputs:** HTTPS, PostgreSQL with PostGIS, `JWT_SECRET`, `CORS_ORIGINS` and optional Google credentials. Realtime hubs and the worker live in memory, so the backend runs as one instance with one worker.

**Not built yet:** readiness, host hand-over when the host disconnects, calendar export, derived reputation, external sports news, waiting lists, email/WhatsApp notices, Arabic, browser push, saved searches, automatic balancing and league/group-stage cups.

## Assets and sources

[ERD](assets/diagrams/erd.svg) · [Routes](assets/diagrams/endpoints.svg) · [Components](assets/diagrams/component-hierarchy.svg) · [Main screens](README.md#wireframes)

https://docs.google.com/document/d/146Ux37oZdEJnZHlKk3vzWZATzfPnYqUf0dR-ri5tRlU/edit?usp=sharing

https://excalidraw.com/#json=mm8VWN_xrBNjyhHDay83Q,RyXy2F4vY2rYgb8-3t7_Xw
