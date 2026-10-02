# Modeer Almalaaeb — simple plan

Build an English-first desktop/mobile website for activities in Bahrain. This package plans the application; implementation comes next.

The shared idea and wireframes remain the sources. This revised plan uses **six core models plus Cup** and includes friends, groups, direct messages and external news.

## Models: six + Cup

1. **User:** accounts, profiles and roles.
2. **Sport:** activities and format presets.
3. **Room:** schedule, venue/privacy, capacity and JSON slot layout.
4. **Membership:** room/group members, friend connections and cup rosters.
5. **Message:** room chat or direct message to a user.
6. **Group:** social group or persistent cup team.
7. **Cup:** registration, team snapshots, bracket, fixtures and results.

Membership uses typed targets and consent rules. A friend row stores one canonical user pair; room/group/cup rows reference their resource. Room slots and cup fixtures are JSON data, validated inside locked transactions. **News comes from an external API; there is no News model.**

## Rules to keep

- Include football, basketball, padel, tennis, volleyball, badminton, walking together, running and cycling. Outings use pools with optional distance, pace and route notes.
- Public browsing; accounts for participation. Verify Google server-side and authenticate the existing account before linking.
- Accepted room members, including the host, count toward capacity. Pending requests reserve nothing; approval comes before slot selection.
- Require start/end times, starting 1 hour–7 days ahead. Store UTC; display Bahrain time.
- At 15 minutes before start, remove discovery listings and reject all admission. Freeze schedule/venue/capacity changes and ordinary cancellation. Emergency cancellation needs a reason and participant notice.
- Start/end automatically. Assign unslotted accepted players in admission order, then team/slot order; pools use ordinal. Readiness never blocks starting.
- Completion is not attendance. The frozen completion host records it and rates present players once per session; no self-rating. Games played and rating count are separate.
- Protect exact meeting/booking details across previews, messages and calendar exports. Group membership or invitations never bypass room admission rules.
- After all host connections disappear, wait 30 seconds and promote the oldest connected admitted player. Returning former hosts remain players.
- Friend/group/cup invitations require consent. Direct sending requires an accepted, unblocked friendship; old DM history remains readable after unfriend/block.

## Implementation phases

1. **Foundation**
   - Create seven models, migrations, accounts/Google linking, profiles, roles and nine activities.
   - **Done:** sign-in, profiles and the activity catalogue work.

2. **Rooms**
   - Build discovery, creation, approval, slots/pools, privacy and host controls. Add offline contribution information and authorized calendar export from room fields.
   - Scan overdue rooms with a worker; catch up lifecycle before mutations. Add WebSockets, Redis tickets/presence and reconnect snapshots.
   - **Done:** capacity, cutoff, automatic scheduling and migration work.

3. **Community and after-game**
   - Add friends, blocks, direct/room messages, groups/teams and consent-based invitations.
   - Store readiness, attendance and ratings on Membership; derive reputation from these records.
   - **Done:** consent, privacy and after-game journeys work.

4. **Cups and news**
   - Register persistent team groups, accept player rosters, publish a locked 4/8/16-team bracket and record fixtures/results in Cup.
   - Connect the server to a configured external news API; keep credentials server-side and show unavailable/stale states.
   - **Done:** complete a cup and display attributed news.

5. **Verification**
   - Test simultaneous admissions/slot claims, cutoff/cancellation races, worker recovery, host tabs and reconnects.
   - Verify typed membership targets, friend/group consent, DM privacy, attendance/rating authority, JSON references and cup roster locks.
   - **Done:** these checks and desktop/mobile review pass. Application tests are future work.

**Deployment inputs:** HTTPS, PostgreSQL/Redis, worker hosting, signing/Google credentials, photo storage and news-provider configuration. The worker scans stored rooms; tickets/presence use Redis. These seven tables cover the first build; inbox views are derived from messages.

**Later:** waiting lists, notification history/email/WhatsApp, richer operational auditing, Arabic, browser push, saved searches, automatic balancing and league/group-stage cups.

## Assets and sources

[ERD](assets/diagrams/erd.svg) · [Routes](assets/diagrams/endpoints.svg) · [Components](assets/diagrams/component-hierarchy.svg) · [Main screens](readme.md#wireframes)

https://docs.google.com/document/d/146Ux37oZdEJnZHlKk3vzWZATzfPnYqUf0dR-ri5tRlU/edit?usp=sharing

https://excalidraw.com/#json=mm8VWN_xrBNjyhHDay83Q,RyXy2F4vY2rYgb8-3t7_Xw
