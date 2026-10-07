<img src="assets/branding/logo.svg" width="96" alt="Modeer Almalaaeb logo" />

# Modeer Almalaaeb

Modeer Almalaaeb is a community sports website for people in Bahrain to organize activities, meet players, build groups and chat. Its English-first, responsive React website works on desktop and mobile browsers. This repository contains the FastAPI backend, relational database models and realtime services.

![Modeer Almalaaeb homepage in light mode](assets/previews/homepage-light.jpg)

## Features

- Browse activities and find public rooms by activity, schedule, area and distance.
- Create and edit scheduled rooms, manage join requests and invitations, choose player slots and coordinate through live chat.
- Sign up and sign in with JWT authentication, optionally use Google sign-in, and manage personal profiles.
- Create groups, invite members, connect with friends and send room, group or direct messages; senders can edit and delete their own messages.
- Organize cups with team rosters, knockout brackets or race results, with full create/read/update/delete operations; deletion is available for unpublished draft cups.
- Record attendance, rate players after completed activities and receive realtime notifications.

The seeded catalogue contains **10 activities**: football, basketball, padel, swimming, walking, running, cycling, handball, billiards and kayak. Walking, running and cycling support participant lists with optional distance, pace and route notes.

The database has **nine application tables**: `users`, `sports`, `rooms`, `memberships`, `messages`, `groups`, `cups`, `notifications` and `player_ratings`.

## Getting started

- [Open the deployed website](https://modeer-almalaaeb-frontend.vercel.app).
- [Explore the deployed API documentation](https://modeer-almalaaeb-backend.onrender.com/docs).
- [Frontend repository](https://github.com/hassanelmaayati/modeer-almalaaeb-frontend) · [Backend repository](https://github.com/hassanelmaayati/modeer-almalaaeb-backend).
- [Original project proposal](https://docs.google.com/document/d/146Ux37oZdEJnZHlKk3vzWZATzfPnYqUf0dR-ri5tRlU/edit?usp=sharing) · [Original editable wireframes](https://excalidraw.com/#json=mm8VWN_xrBNjyhHDay83Q,RyXy2F4vY2rYgb8-3t7_Xw).
- [Implementation phases](plan.md) and the planning materials below record the project's design process; older diagrams are explicitly labelled as historical.

Visitors can explore activities and public rooms. Create an account to organize rooms, join activities, manage groups and use messaging.

## Technologies used

| Area | Technologies and purpose |
| --- | --- |
| API | Python 3.14, FastAPI and Uvicorn; Pydantic validates request and response data |
| Database | PostgreSQL with PostGIS; SQLAlchemy models, Alembic migrations and psycopg2 connectivity |
| Location | GeoAlchemy2 and Shapely for venue points and nearby room searches |
| Authentication | PyJWT, Passlib/bcrypt and optional Google Auth for sign-in and account linking |
| Realtime | WebSockets for messages, room state, lobby events and notifications; lifecycle and retention workers run inside the application process |
| Testing | pytest, HTTPX, pytest-cov and pytest-timeout; offline tests use a temporary PostgreSQL/PostGIS database |
| Tooling and deployment | Pipenv, Docker, GitHub Actions, Render and Supabase PostgreSQL |

The companion frontend uses React/Vite, React Router, Leaflet and CSS. See its README for the frontend technology details.

## Team portfolio

All three contributors worked across the frontend and backend. These are representative backend contributions; features were developed and reviewed collaboratively.

| Contributor | Features contributed | Technologies used |
| --- | --- | --- |
| [Hassan El Maayati](https://github.com/hassanelmaayati) | JWT authentication, Google account linking, cups, player ratings and attendance | FastAPI, PyJWT, Google Auth, SQLAlchemy, PostgreSQL |
| [Ahmed Tarek](https://github.com/ctarek2015-wq) | Groups and memberships, friendships, realtime messaging and notifications, migrations, tests and deployment | FastAPI, SQLAlchemy, Alembic, WebSockets, pytest, Docker |
| [FatimaHubail](https://github.com/FatimaHubail) | Room creation and scheduling, nearby searches, messaging, activity lifecycle and lobby events | FastAPI, PostgreSQL/PostGIS, GeoAlchemy2, WebSockets |

## Future enhancements

- Add a sports news feature.
- Build a dedicated mobile app.

## Attributions

The backend uses the following open source projects. Source and license links credit their authors and contributors:

| Resource | Use | License |
| --- | --- | --- |
| [FastAPI](https://github.com/fastapi/fastapi), [Pydantic](https://github.com/pydantic/pydantic), [Uvicorn](https://github.com/Kludex/uvicorn) | API framework, validation and ASGI server | [FastAPI MIT](https://github.com/fastapi/fastapi/blob/master/LICENSE), [Pydantic MIT](https://github.com/pydantic/pydantic/blob/main/LICENSE), [Uvicorn BSD-3-Clause](https://github.com/Kludex/uvicorn/blob/main/LICENSE.md) |
| [PostgreSQL](https://www.postgresql.org), [PostGIS](https://github.com/postgis/postgis) | Relational data and spatial queries | [PostgreSQL License](https://www.postgresql.org/about/licence/), [PostGIS GPL](https://github.com/postgis/postgis/blob/master/COPYING) |
| [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy), [Alembic](https://github.com/sqlalchemy/alembic), [psycopg2](https://github.com/psycopg/psycopg2) | Models, migrations and database driver | [SQLAlchemy MIT](https://github.com/sqlalchemy/sqlalchemy/blob/main/LICENSE), [Alembic MIT](https://github.com/sqlalchemy/alembic/blob/main/LICENSE), [psycopg2 LGPL with exceptions](https://github.com/psycopg/psycopg2/blob/master/LICENSE) |
| [GeoAlchemy2](https://github.com/geoalchemy/geoalchemy2), [Shapely](https://github.com/shapely/shapely) | Spatial types and geometry | [GeoAlchemy2 MIT](https://github.com/geoalchemy/geoalchemy2/blob/main/COPYING.rst), [Shapely BSD-3-Clause](https://github.com/shapely/shapely/blob/main/LICENSE.txt) |
| [PyJWT](https://github.com/jpadilla/pyjwt), [Google Auth](https://github.com/googleapis/google-auth-library-python) | JWT and Google identity verification | [PyJWT MIT](https://github.com/jpadilla/pyjwt/blob/master/LICENSE), [Google Auth Apache-2.0](https://github.com/googleapis/google-auth-library-python/blob/main/LICENSE) |
| [pytest](https://github.com/pytest-dev/pytest), [HTTPX](https://github.com/encode/httpx) | Automated tests and HTTP clients | [pytest MIT](https://github.com/pytest-dev/pytest/blob/main/LICENSE), [HTTPX BSD-3-Clause](https://github.com/encode/httpx/blob/master/LICENSE.md) |

The homepage preview shows the companion website. Its fonts and mapping resources, including Fontsource fonts, Leaflet and OpenStreetMap, are credited with their source and license links in the [frontend Attributions](https://github.com/hassanelmaayati/modeer-almalaaeb-frontend#attributions). All direct backend dependencies are listed in [Pipfile](Pipfile), with resolved versions in [Pipfile.lock](Pipfile.lock).

## Local development

Install Python 3.14, Pipenv and PostgreSQL with PostGIS, then create a dedicated empty local database. Copy [.env.example](.env.example) to `.env`, set `DATABASE_URL` to that local database, choose a private `JWT_SECRET`, and set `CORS_ORIGINS` to the frontend development origin (normally `http://localhost:5173`). Optional Google sign-in requires matching backend and frontend client IDs.

```bash
cp .env.example .env
# Edit .env before starting the API.
PIPENV_DONT_LOAD_ENV=1 pipenv sync --dev

# Replace this example with the SAME local database URL configured in .env.
export DATABASE_URL='postgresql+psycopg2://postgres:YOUR_PASSWORD@localhost:5432/modeer'
pipenv run python -m migrations.initialize --database-url "$DATABASE_URL"
pipenv run python -m scripts.import_sports
pipenv run python seed.py  # optional demo data, local development only

pipenv run python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

The local API documentation is available at `http://127.0.0.1:8000/docs`. Initialization applies the schema and enables PostGIS; the database role needs permission to create the extension, or a database administrator must enable it first.

`migrations.initialize` only accepts an empty schema. Its optional `--reset-existing` flag drops application tables and is only appropriate for an expendable local database. `seed.py` imports the sports and adds demo users, groups, cups and rooms only when there are no users; it exits with status 1 on failure. Demo accounts are `user1@example.com` to `user4@example.com` with password `password123`.

### Tests

Run the same offline test command as CI:

```bash
PIPENV_DONT_LOAD_ENV=1 pipenv run python -m tests.run_offline
```

The test runner uses an isolated temporary PostgreSQL/PostGIS database and does not need production credentials.

## Deployment

In Render, connect this repository with **New → Blueprint**. `render.yaml`
builds the Dockerfile on the Free plan in Frankfurt and deploys commits to
`main` after required CI checks pass. Keep the Docker command unchanged: it binds Render's `PORT` and starts
`main:app` with one worker. Use one backend instance for the in-memory socket hubs.

Supply `DATABASE_URL` (Supabase session pooler, port 5432, `sslmode=require`),
a stable private `JWT_SECRET`, and `CORS_ORIGINS` (the exact Vercel frontend
origin, without a path or trailing slash). `.env.example` documents these
settings. `LIFECYCLE_WORKER` is enabled by the Blueprint; Google sign-in is
optional and requires matching backend and frontend client IDs.
`HOST_AWAY_GRACE_SECONDS` (default 18000, five hours) is how long a started
room's host may stay offline before a connected player takes over.

The app refuses to start if `DATABASE_URL` or `JWT_SECRET` is missing, and warns
if `JWT_SECRET` is shorter than 32 characters. `/health` never touches the
database; `/health/ready` pings it (200 or 503).

Use the already initialized database. Startup does not migrate or import data.
Do not run `seed.py`, reset commands, or empty-database initialization against
an existing project. Apply new Alembic migrations separately after a backup with
`DATABASE_URL=... pipenv run alembic upgrade head`; run
`pipenv run python -m scripts.import_sports` separately in a configured development environment for deliberate catalogue updates.
Check `/health`, `/health/ready` and `/api/v1/sports` after deployment.

## User stories

- As a visitor, I want to browse activities and rooms so I can find a suitable game or outing.
- As a player, I want an account and profile so others can recognize me.
- As a host, I want to schedule rooms and approve players so I can organize my activity.
- As an admitted player, I want a slot, readiness and room chat so we can coordinate.
- As a completion host, I want to record attendance and rate attended players so history reflects participation.
- As a player, I want accepted friendships and direct messages so I can coordinate privately.
- As a group owner/member, I want invitations and reusable groups so we can meet again.
- As a captain/organizer, I want cups with accepted rosters, knockout brackets or races so teams can compete.

## Planning materials

### Wireframes

These historical planning screens describe the original journeys. The homepage screenshot above shows the current implementation; the layouts below are design references, not current application captures.

#### Discover

**Home**

![Home page](assets/previews/home-desktop.png)

**Browse and filter rooms**

![Room discovery and filters](assets/previews/room-list-desktop.png)

#### Create and join

**Create and open a scheduled activity**

![Room creation and preview](assets/previews/create-room-desktop.png)

**Admitted player: choose a slot and coordinate**

![Team lobby with slots, readiness and chat](assets/previews/room-desktop.png)

#### Walk, run or cycle

**Admitted player: mobile roster and meeting details**

![Mobile lobby for walking, running and cycling](assets/previews/room-pool-mobile.png)

#### After the activity

**Completion host: attendance, ratings and group invitations**

![After-game attendance and ratings](assets/previews/after-game-desktop.png)

[Original editable wireframes in Excalidraw](https://excalidraw.com/#json=mm8VWN_xrBNjyhHDay83Q,RyXy2F4vY2rYgb8-3t7_Xw).

## Database models

| Model | Stores |
| --- | --- |
| User | Accounts, profiles, home district and optional Google link (no roles); names are unique ignoring case |
| Sport | Activities and format presets; each sport's cup format comes from the server |
| Room | Schedule, privacy, admission policy, capacity, slot layout, venue point (PostGIS), cancellation and host hand-over state |
| Membership | Room/group members, friend connections and cup rosters |
| Message | Room chat, group chat, direct messages and system notices; senders can edit or soft-delete their own |
| Group | Social groups and persistent teams |
| Cup | Entries, knockout bracket or race results |
| Notification | Per-user notices and read state; read ones expire after 30 days and all after 90 |
| Player rating | A final 1–5 star rating from one player to another for one completed room |

Membership has no `kind` column: the row type follows from which target is set
(`room_id`, `group_id`, `cup_id` with `group_id`, or `other_user_id` for friends).
Friend rows carry one block flag per side (`user_blocked_other`, `other_blocked_user`). Room memberships record when a player was admitted (`accepted_at`). Room slots (`{"slots": [...]}` or `{"teams": [...]}`) and cup
entries/fixtures are JSON validated by the server.

![ERD](assets/previews/erd.png)

[Historical editable ERD](assets/diagrams/erd.svg). This planning diagram predates notifications, player ratings, the room venue, cancellation and host fields, message edit/delete times and `memberships.accepted_at`. The nine-model table above describes the current schema.

## Routes/endpoints

Use `/api/v1` before the API paths shown below. Frontend paths use parameters such as `:roomId`; FastAPI paths use `{room_id}`. The deployed [interactive API documentation](https://modeer-almalaaeb-backend.onrender.com/docs) contains the full request and response contracts.

| Model / feature | Main frontend routes | Main API endpoints |
| --- | --- | --- |
| User | `/sign-in`, `/sign-up`, `/users/:userId`, `/settings` | `POST /auth/signup`, `/auth/login`, `/auth/logout`<br>`POST /auth/google`, `/auth/google/link`<br>`GET /users?limit=&offset=` or `?ids=1,2,3`, `GET /users/{user_id}`, `GET /users/{user_id}/rating`<br>`GET/PUT /users/me` |
| Sport | `/`, `/sports` | `GET /sports`, `GET /sports/{sport_id}` |
| Room | `/`, `/rooms/new`, `/rooms/:roomId`, `/rooms/:roomId/edit`, `/my-rooms`, `/joined-rooms` | `GET /rooms?limit=&offset=&group_id=&near_lat=&near_lng=&radius_km=`, `POST /rooms`<br>`GET /rooms/mine`, `GET /rooms/joined`<br>`GET/PUT /rooms/{room_id}`<br>`POST /rooms/{room_id}/cancel`, `POST /rooms/{room_id}/transfer-host` |
| Membership | Room/after-game pages, `/friends`, group/cup pages | `GET/POST /rooms/{room_id}/members`, `PATCH /rooms/{room_id}/members/{user_id}`, `DELETE /rooms/{room_id}/members/me`<br>`GET/POST /friends`, `PATCH /friends/{user_id}`<br>`GET/POST /groups/{group_id}/members`, `PATCH /groups/{group_id}/members/{user_id}`<br>`GET/POST /cups/{cup_id}/roster`, `PATCH /cups/{cup_id}/roster/{user_id}` |
| Message | Room chat, `/messages`, `/messages/:type/:id` | `GET/POST /messages`, `PATCH/DELETE /messages/{message_id}`, `GET /messages/conversations` |
| Group | `/groups` with creation/detail dialogs; `/groups?group_id=ID` | `GET /groups?limit=&offset=`, `POST /groups`<br>`GET /groups/mine`<br>`GET/PUT /groups/{group_id}` |
| Cup | `/cups`, `/cups/new`, `/cups/:cupId` | `GET /cups?status=&limit=&offset=`, `POST /cups`<br>`GET/PATCH/DELETE /cups/{cup_id}`<br>`POST /cups/{cup_id}/entries`, `PUT /cups/{cup_id}/entries/{group_id}` |
| Notification | Header bell, `/notifications` | `GET /notifications`, `PATCH /notifications`, `PATCH /notifications/{notification_id}` |
| Player rating | After-game page, profiles | `POST /rooms/{room_id}/ratings`, `GET /rooms/{room_id}/ratings/mine`<br>`GET /users/{user_id}/rating` (public) |
| Realtime | Shared provider | `POST /socket-ticket`, then `WS /ws?ticket=`; public `WS /ws/lobby` |

### Behaviour notes

- **Scheduling:** rooms must start between 1 hour and 14 days from now. API timestamps use UTC (`+00:00`); the frontend displays local Bahrain time.
- **Lists:** `GET /rooms`, `/groups`, `/cups` and `/users` page with `limit` (default 50, max 100) and `offset`, return plain lists and report the total in the `X-Total-Count` header.
- **Errors:** cup, entry and room writes send the `revision` they last read; a stale one returns 409. Invalid state changes return 409; invalid input returns 400 or 422. Login and signup are rate limited (429 with `Retry-After`).
- **Rooms:** public rooms are listed until 15 minutes before the start, when joining closes and schedule/venue/capacity freeze. Private rooms, and group-only rooms for people outside the group, answer 404 exactly like a missing room on every route. Group members can see, list (`?group_id=`) and join their group's rooms.
- **Joining:** with `admission_policy: "approval"` a request waits for the host; with `"open"` it is accepted at once when a place is free. Invitations always wait for the invitee. Positions must be a slot from the room's `slot_layout` (numbered places 1..capacity when it has none).
- **Distance search:** `?near_lat=&near_lng=&radius_km=` (1–50) sorts rooms by distance and adds `km_away` in whole kilometres. Distances are measured to a coarse area point (about 2 km), never the private venue pin.
- **Ratings:** players rate each other 1–5 stars once per room after it completes (host and accepted members take part, no-shows do not); ratings are final and only the rater can list theirs. The host rates through attendance, once per present accepted player, after completion. A profile average counts both kinds, and the host rating is only visible to the host.
- **Host hand-over:** the host can transfer a room to an accepted player. If a started room's host has no realtime connection for the grace period, the longest-admitted connected player takes over (notices, a chat message and the `room.host_changed` event follow). The old host stays as a player.
- **Messages:** senders can edit or delete their own messages while they could still send in that chat; a deleted message keeps its row, its text is erased and responses show `deleted: true`. Edits and deletes are pushed as `message.updated` and `message.deleted`.
- **Realtime:** WebSockets deliver room, message and notification updates; hubs live in memory, so run one instance with one worker.

[Historical route planning diagram](assets/diagrams/endpoints.svg). Use the table above and API documentation for current paths and methods.

## Component hierarchy

The companion React frontend uses shared account/live providers for room pages, friends, groups, messaging and cups. This hierarchy is a historical planning reference; the frontend source describes the current component structure.

![Compact React component hierarchy](assets/previews/component-hierarchy.png)

[Historical editable component hierarchy](assets/diagrams/component-hierarchy.svg)
