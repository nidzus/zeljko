PRAGMA foreign_keys = ON;

-- Who owns what. A personal database has exactly one account, the owner,
-- with no sign-in. The shared database has one per invited friend. Everything
-- below belongs to an account through its person.
CREATE TABLE IF NOT EXISTS account (
    id               INTEGER PRIMARY KEY,
    email            TEXT UNIQUE,          -- NULL for the owner of a personal database
    display_name     TEXT,
    is_owner         INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL,        -- invited | active | disabled
    invite_hash      TEXT,                 -- fingerprint of the one-time invite code
    invite_expires   TEXT,
    -- the account's data key, wrapped; never stored in the clear (see vault.py)
    key_by_password  TEXT,
    key_by_recovery  TEXT,
    created_at       TEXT NOT NULL,
    last_seen_at     TEXT
);

-- A profile an account manages. Not itself a login.
CREATE TABLE IF NOT EXISTS person (
    id          INTEGER PRIMARY KEY,
    account_id  INTEGER REFERENCES account(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    relation    TEXT,                 -- "self", "partner", ...
    notes       TEXT,
    created_at  TEXT NOT NULL
);

-- A computed nativity. Charts are VERSIONED, never edited in place: a
-- rectified birth time is a new row pointing back at the original, so the
-- reasoning behind a change is always recoverable.
CREATE TABLE IF NOT EXISTS chart (
    id                   INTEGER PRIMARY KEY,
    person_id            INTEGER NOT NULL REFERENCES person(id) ON DELETE CASCADE,

    -- exactly what was entered, preserved verbatim
    birth_date           TEXT NOT NULL,     -- YYYY-MM-DD, local
    birth_time           TEXT NOT NULL,     -- HH:MM:SS, local wall clock
    place_name           TEXT NOT NULL,
    latitude             REAL NOT NULL,
    longitude            REAL NOT NULL,

    -- how the local reading became an instant, kept auditable
    timezone_name        TEXT NOT NULL,
    utc_offset_hours     REAL NOT NULL,
    iana_offset_hours    REAL NOT NULL,
    used_local_mean_time INTEGER NOT NULL,
    julian_day_ut        REAL NOT NULL,
    time_ambiguous       INTEGER NOT NULL DEFAULT 0,
    time_nonexistent     INTEGER NOT NULL DEFAULT 0,

    time_confidence      TEXT NOT NULL,     -- TimeConfidence enum name
    ayanamsa             TEXT NOT NULL DEFAULT 'LAHIRI',

    is_active            INTEGER NOT NULL DEFAULT 1,
    derived_from_id      INTEGER REFERENCES chart(id),
    rectification_note   TEXT,
    created_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chart_person ON chart(person_id, is_active);

-- Dated events. Useful immediately as context the advisor can reason from,
-- and later as the input rectification tests candidate birth times against.
CREATE TABLE IF NOT EXISTS life_event (
    id           INTEGER PRIMARY KEY,
    person_id    INTEGER NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    happened_on  TEXT NOT NULL,           -- YYYY-MM-DD
    precision    TEXT NOT NULL,           -- day | month | year
    category     TEXT,                    -- career, relationship, health, ...
    title        TEXT NOT NULL,
    description  TEXT,
    significance INTEGER NOT NULL DEFAULT 3,   -- 1..5, weights rectification
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_person ON life_event(person_id, happened_on);

CREATE TABLE IF NOT EXISTS conversation (
    id          INTEGER PRIMARY KEY,
    person_id   INTEGER NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    title       TEXT,
    started_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS message (
    id               INTEGER PRIMARY KEY,
    conversation_id  INTEGER NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    role             TEXT NOT NULL,       -- user | assistant
    content          TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_message_conv ON message(conversation_id, id);

-- The first-class object. A chat log ages badly; this does not.
CREATE TABLE IF NOT EXISTS decision (
    id                  INTEGER PRIMARY KEY,
    person_id           INTEGER NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    chart_id            INTEGER NOT NULL REFERENCES chart(id),
    conversation_id     INTEGER REFERENCES conversation(id) ON DELETE SET NULL,

    asked_at            TEXT NOT NULL,
    question            TEXT NOT NULL,
    question_type       TEXT,             -- career, relationship, ...
    houses_consulted    TEXT,             -- JSON [10, 1]

    verdict             TEXT,
    confidence          TEXT,             -- the advisor's own hedge
    window_opens        TEXT,             -- when conditions turn favourable
    window_closes       TEXT,

    -- what the sky looked like when asked, frozen so it can be revisited
    astral_snapshot     TEXT,             -- JSON: dasha chain, live transits
    reliability         TEXT,             -- JSON: what the gate permitted

    chose               TEXT,             -- filled in when you decide
    chose_at            TEXT,
    outcome             TEXT,             -- filled in much later
    outcome_at          TEXT,
    outcome_rating      INTEGER           -- -2..+2, for reviewing the advice
);
CREATE INDEX IF NOT EXISTS idx_decision_person ON decision(person_id, asked_at);

-- Every interpretive claim points at the computed fact underneath it.
-- Without this, traceability is a promise; with it, it is a join.
CREATE TABLE IF NOT EXISTS citation (
    id           INTEGER PRIMARY KEY,
    decision_id  INTEGER NOT NULL REFERENCES decision(id) ON DELETE CASCADE,
    claim        TEXT NOT NULL,
    fact_kind    TEXT NOT NULL,     -- position | dasha | transit | event
    fact         TEXT NOT NULL      -- JSON, as returned by the tool
);
CREATE INDEX IF NOT EXISTS idx_citation_decision ON citation(decision_id);

CREATE TABLE IF NOT EXISTS setting (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
