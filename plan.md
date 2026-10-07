# Modeer Almalaaeb — simple plan

An English-first desktop/mobile website for activities in Bahrain. The backend is implemented; this page records the rules it follows and what is still planned.

The shared idea and wireframes remain the sources. The build uses nine tables and includes friends, groups, direct messages, cups, ratings and notifications.

## Models

1. **User:** accounts, profiles, home district and an optional Google link. There are no roles or admin accounts. Names are unique ignoring case.
2. **Sport:** activities and format presets. Each sport's cup format (knockout, race or none) is derived on the server.
3. **Room:** schedule, venue point/privacy, admission policy, capacity, JSON slot layout, cancellation record and host hand-over state.
4. **Membership:** room/group members, friend connections and cup rosters.
5. **Message:** room chat, group chat, direct message or system notice; senders can edit or soft-delete their own.
6. **Group:** social group or persistent cup team.
7. **Cup:** registration, team snapshots, knockout bracket or race results.
8. **Notification:** per-user notices and read state; expired by a daily job.
9. **Player rating:** a final 1-5 star rating between two players of one completed room.

Membership has no `kind` column; the row type follows from which target is set. A friend row stores one user pair and one block flag per side (free-text strings). Room slots and cup entries/fixtures are JSON data, validated inside locked transactions.

## Rules to keep

- Seeded sports: football, basketball, padel, swimming, walking together, running, cycling, handball, billiards and kayak. Outings use pools with optional distance, pace and route notes. Walking has no cups.
- Public browsing; accounts for participation. Verify Google server-side and authenticate the existing account before linking.
- Accepted room members, including the host, count toward capacity. Pending requests reserve nothing. With approval admission the host accepts each request; with open admission a request is accepted at once when a place is free; invitations always need the invitee's consent.
- A room starts between 1 hour and **14 days** from now. Times are stored and returned in UTC; the frontend shows Bahrain time.
- At 15 minutes before start, remove discovery listings and reject all admission. Freeze schedule/venue/capacity changes. Cancelling always needs a reason and notifies participants.
- Rooms start and finish automatically (the lifecycle worker, once a minute). Players claim a named slot from the room's layout (numbered places when there is none); no automatic slot assignment.
- Private rooms are invisible to outsiders (404 like a missing room). Group-only rooms are visible to the group's owner and accepted members, who can list and join them.
- Completion is not attendance. The host records attendance and rates present accepted players once (1-5, final, after completion); players rate each other once per room after completion; no self-rating, no no-shows. Nobody can see who rated whom, and the host rating is visible only to the host.
- If a started room's host stays offline for the grace period (five hours by default), the longest-admitted connected player takes over; the host can also transfer a room by hand. The old host stays as a player.
- Protect exact meeting/booking details across previews, messages and distance search (distances use a coarse area point). Group membership or invitations never bypass room admission rules.
- Friend/group/cup invitations require consent and can be repeated after a decline, leave or removal (room memberships stay closed). Direct sending requires an accepted, unblocked friendship; old DM history remains readable after unfriend/block. Each user sees only their own block.
- Cup writes carry the revision the client last read; stale writes and invalid state changes return 409.

## Implementation phases

1. **Foundation** — done: models, Alembic migrations, accounts, Google sign-in/linking, profiles and the sports catalogue.
2. **Rooms** — done: discovery (with distance search), creation, approval and open admission, slots, privacy, group-only rooms, host controls and hand-over, the lifecycle worker (inside the app process) and in-memory WebSocket hubs with socket tickets.
3. **Community and after-game** — done: friends, blocks, direct/room/group messages (with edit and delete), groups/teams, consent-based invitations, attendance, ratings and notifications.
4. **Cups** — done: team entries, rosters, locked 4/8/16-team knockout brackets and race results.
5. **Verification** — done: an offline test suite on isolated PostgreSQL/PostGIS runs in CI before every deploy.

**Deployment inputs:** HTTPS, PostgreSQL with PostGIS, `JWT_SECRET` (32+ characters), `CORS_ORIGINS` and optional Google credentials. Realtime hubs, rate limits and the workers live in memory, so the backend runs as one instance with one worker.

**Not built yet:** offline contribution information, calendar export, reconnect snapshots for sockets (clients refetch), automatic slot assignment, waiting lists, email/WhatsApp notices, Arabic, browser push, saved searches, automatic balancing and league/group-stage cups. There is no external sports news.

## Assets and sources

[ERD](assets/diagrams/erd.svg) · [Routes](assets/diagrams/endpoints.svg) · [Components](assets/diagrams/component-hierarchy.svg) · [Main screens](README.md#wireframes)

https://docs.google.com/document/d/146Ux37oZdEJnZHlKk3vzWZATzfPnYqUf0dR-ri5tRlU/edit?usp=sharing

https://excalidraw.com/#json=mm8VWN_xrBNjyhHDay83Q,RyXy2F4vY2rYgb8-3t7_Xw
