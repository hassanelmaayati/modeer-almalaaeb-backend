-- Frozen PostgreSQL schema at legacy Alembic head 0a029e480f8f.
-- Do not regenerate this baseline from changing application models.

CREATE TABLE sports (
	id SERIAL NOT NULL, 
	name VARCHAR NOT NULL, 
	formats JSONB, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_sports_id ON sports (id);

CREATE TABLE users (
	id SERIAL NOT NULL, 
	user_name VARCHAR NOT NULL, 
	photo_url VARCHAR, 
	bio TEXT, 
	district VARCHAR, 
	email VARCHAR NOT NULL, 
	password VARCHAR NOT NULL, 
	google_subject VARCHAR, 
	token_version INTEGER DEFAULT '0' NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_users_district CHECK (district IS NULL OR district IN ('capital', 'muharraq', 'northern', 'southern')), 
	UNIQUE (user_name), 
	UNIQUE (email), 
	UNIQUE (google_subject)
);

CREATE INDEX ix_users_id ON users (id);

CREATE TABLE cups (
	id SERIAL NOT NULL, 
	organizer_user_id INTEGER NOT NULL, 
	sport_id INTEGER NOT NULL, 
	name VARCHAR NOT NULL, 
	rules TEXT NOT NULL, 
	team_count INTEGER NOT NULL, 
	roster_limit INTEGER NOT NULL, 
	status VARCHAR DEFAULT 'draft' NOT NULL, 
	registration_closes_at TIMESTAMP WITHOUT TIME ZONE, 
	rosters_locked_at TIMESTAMP WITHOUT TIME ZONE, 
	entries JSONB NOT NULL, 
	fixtures JSONB NOT NULL, 
	revision INTEGER DEFAULT '0' NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_cups_team_count CHECK (team_count >= 2), 
	CONSTRAINT ck_cups_roster_limit CHECK (roster_limit > 0), 
	CONSTRAINT ck_cups_status CHECK (status IN ('draft', 'registration', 'published', 'completed')), 
	FOREIGN KEY(organizer_user_id) REFERENCES users (id), 
	FOREIGN KEY(sport_id) REFERENCES sports (id)
);

CREATE INDEX ix_cups_id ON cups (id);

CREATE TABLE groups (
	id SERIAL NOT NULL, 
	owner_id INTEGER NOT NULL, 
	name VARCHAR NOT NULL, 
	description VARCHAR, 
	photo_url VARCHAR, 
	sports_id INTEGER NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id), 
	FOREIGN KEY(sports_id) REFERENCES sports (id)
);

CREATE INDEX ix_groups_id ON groups (id);

CREATE TABLE rooms (
	id SERIAL NOT NULL, 
	host_id INTEGER NOT NULL, 
	sport_id INTEGER NOT NULL, 
	group_id INTEGER, 
	title VARCHAR NOT NULL, 
	description TEXT, 
	difficulty VARCHAR DEFAULT 'beginners' NOT NULL, 
	starts_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	ends_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	capacity INTEGER NOT NULL, 
	slot_layout JSONB NOT NULL, 
	status VARCHAR DEFAULT 'open' NOT NULL, 
	visibility VARCHAR DEFAULT 'public' NOT NULL, 
	admission_policy VARCHAR DEFAULT 'approval' NOT NULL, 
	district VARCHAR NOT NULL, 
	public_area VARCHAR NOT NULL, 
	venue_details TEXT, 
	distance_km FLOAT, 
	pace_notes VARCHAR, 
	route_notes TEXT, 
	host_generation INTEGER DEFAULT '0' NOT NULL, 
	revision INTEGER DEFAULT '0' NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_rooms_end_after_start CHECK (ends_at > starts_at), 
	CONSTRAINT ck_rooms_capacity_positive CHECK (capacity > 0), 
	CONSTRAINT ck_rooms_status CHECK (status IN ('open', 'started', 'completed', 'cancelled')), 
	CONSTRAINT ck_rooms_visibility CHECK (visibility IN ('public', 'private', 'group')), 
	CONSTRAINT ck_rooms_admission_policy CHECK (admission_policy IN ('approval', 'open')), 
	CONSTRAINT ck_rooms_difficulty CHECK (difficulty IN ('beginners', 'medium', 'advanced')), 
	CONSTRAINT ck_rooms_district CHECK (district IN ('capital', 'muharraq', 'northern', 'southern')), 
	CONSTRAINT ck_rooms_group_visibility_needs_group CHECK (visibility != 'group' OR group_id IS NOT NULL), 
	FOREIGN KEY(host_id) REFERENCES users (id), 
	FOREIGN KEY(sport_id) REFERENCES sports (id), 
	FOREIGN KEY(group_id) REFERENCES groups (id)
);

CREATE INDEX ix_rooms_district_status_starts_at ON rooms (district, status, starts_at);

CREATE INDEX ix_rooms_id ON rooms (id);

CREATE TABLE memberships (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	other_user_id INTEGER, 
	room_id INTEGER, 
	group_id INTEGER, 
	cup_id INTEGER, 
	status VARCHAR NOT NULL, 
	position VARCHAR, 
	attendance VARCHAR, 
	rating INTEGER, 
	requested BOOLEAN, 
	accepted BOOLEAN, 
	user_blocked_other VARCHAR, 
	other_blocked_user VARCHAR, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(other_user_id) REFERENCES users (id), 
	FOREIGN KEY(room_id) REFERENCES rooms (id), 
	FOREIGN KEY(group_id) REFERENCES groups (id), 
	FOREIGN KEY(cup_id) REFERENCES cups (id)
);

CREATE INDEX ix_memberships_id ON memberships (id);

CREATE TABLE messages (
	id SERIAL NOT NULL, 
	sender_id INTEGER, 
	recipient_id INTEGER, 
	room_id INTEGER, 
	type VARCHAR NOT NULL, 
	body TEXT NOT NULL, 
	client_request_id UUID, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_messages_type CHECK (type IN ('room', 'direct', 'system')), 
	CONSTRAINT ck_messages_exactly_one_target CHECK ((room_id IS NOT NULL AND recipient_id IS NULL) OR (room_id IS NULL AND recipient_id IS NOT NULL)), 
	CONSTRAINT ck_messages_type_matches_target CHECK ((type = 'room' AND room_id IS NOT NULL AND sender_id IS NOT NULL) OR (type = 'direct' AND recipient_id IS NOT NULL AND sender_id IS NOT NULL) OR (type = 'system' AND room_id IS NOT NULL AND sender_id IS NULL)), 
	CONSTRAINT ck_messages_no_self_message CHECK (recipient_id IS NULL OR sender_id != recipient_id), 
	CONSTRAINT ck_messages_body_not_blank CHECK (length(trim(body)) > 0), 
	CONSTRAINT uq_messages_sender_request UNIQUE (sender_id, client_request_id), 
	FOREIGN KEY(sender_id) REFERENCES users (id), 
	FOREIGN KEY(recipient_id) REFERENCES users (id), 
	FOREIGN KEY(room_id) REFERENCES rooms (id)
);

CREATE INDEX ix_messages_id ON messages (id);

CREATE INDEX ix_messages_recipient_created ON messages (recipient_id, created_at);

CREATE INDEX ix_messages_room_created ON messages (room_id, created_at);
