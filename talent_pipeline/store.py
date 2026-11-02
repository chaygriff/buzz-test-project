"""Local append-only observations and content-addressed raw evidence."""
import hashlib
import fcntl
import json
import os
import tempfile
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from talent_pipeline.network import canonical_url


def now():
    return datetime.now(timezone.utc).isoformat()


def stable_id(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def valid_snapshot_status(status):
    """Snapshots represent either no response (0) or an HTTP response code."""
    return type(status) is int and (status == 0 or 100 <= status <= 599)


def validate_observation_provenance(job, snapshot, kind, payload, expected_attempt=None):
    """Bind every observation to its exact retained response and request job."""
    if kind not in {'candidate', 'claim', 'review', 'policy'} or not isinstance(payload, dict):
        raise ValueError('Invalid observation payload provenance')
    try:
        source_url = payload['source_url']
        if source_url != canonical_url(source_url) or source_url != snapshot['url']:
            raise ValueError
        if kind == 'policy':
            request_url = payload['request_url']
            result_url = payload['result_url']
            redirects = payload['redirects']
            attempt = payload['attempt']
            if (request_url != canonical_url(request_url) or request_url != job['url']
                    or result_url != canonical_url(result_url) or result_url != snapshot['url']
                    or type(attempt) is not int or not 1 <= attempt <= job['attempts']
                    or expected_attempt is not None and attempt != expected_attempt
                    or not isinstance(redirects, list)
                    or any(type(url) is not str or url != canonical_url(url) for url in redirects)
                    or result_url != request_url and (not redirects or redirects[-1] != result_url)):
                raise ValueError
        elif (kind in {'candidate', 'claim'}
              and (not isinstance(payload.get('evidence_text'), str)
                   or not payload['evidence_text'].strip())
              or kind in {'candidate', 'claim', 'review'}
              and (not isinstance(payload.get('locator'), str)
                   or not payload['locator'].strip())):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError('Invalid observation source URL provenance') from None


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = (self.root / '.writer.lock').open('a')
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock.close()
            raise RuntimeError('Another writer owns this ledger') from None
        self.db = sqlite3.connect(self.root / 'ledger.sqlite3')
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS snapshots (
            id TEXT PRIMARY KEY, url TEXT NOT NULL, sha256 TEXT NOT NULL,
            path TEXT NOT NULL, status INTEGER NOT NULL, content_type TEXT NOT NULL,
            retrieved_at TEXT NOT NULL)''')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                inputs TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                seed_id TEXT NOT NULL, kind TEXT NOT NULL, url TEXT NOT NULL,
                payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0, reason TEXT,
                snapshot_id TEXT REFERENCES snapshots(id), updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS observations (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                job_id TEXT NOT NULL REFERENCES jobs(id),
                snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
                kind TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS job_snapshots (
                job_id TEXT NOT NULL REFERENCES jobs(id),
                snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
                attempt INTEGER NOT NULL,
                PRIMARY KEY (job_id, snapshot_id),
                UNIQUE (job_id, attempt));
            CREATE TRIGGER IF NOT EXISTS done_job_snapshot_insert
                BEFORE INSERT ON jobs
                WHEN NEW.status = 'done' AND (NEW.snapshot_id IS NULL OR NOT EXISTS (
                    SELECT 1 FROM snapshots
                    WHERE id = NEW.snapshot_id AND status BETWEEN 200 AND 299
                ))
                BEGIN SELECT RAISE(ABORT, 'done job requires successful snapshot'); END;
            CREATE TRIGGER IF NOT EXISTS done_job_snapshot_update
                BEFORE UPDATE OF status, snapshot_id ON jobs
                WHEN NEW.status = 'done' AND (NEW.snapshot_id IS NULL OR NOT EXISTS (
                    SELECT 1 FROM snapshots
                    WHERE id = NEW.snapshot_id AND status BETWEEN 200 AND 299
                ))
                BEGIN SELECT RAISE(ABORT, 'done job requires successful snapshot'); END;
            DROP TRIGGER IF EXISTS observation_snapshot_matches_job_insert;
            DROP TRIGGER IF EXISTS job_snapshot_matches_observations_update;
            CREATE TRIGGER observation_snapshot_matches_job_insert
                BEFORE INSERT ON observations
                WHEN NOT EXISTS (
                    SELECT 1 FROM job_snapshots
                    WHERE job_id = NEW.job_id AND snapshot_id = NEW.snapshot_id
                )
                BEGIN SELECT RAISE(ABORT, 'observation snapshot must match job'); END;
            CREATE TRIGGER job_snapshot_matches_observations_update
                BEFORE UPDATE OF snapshot_id ON jobs
                WHEN (NEW.snapshot_id IS NULL AND EXISTS (
                    SELECT 1 FROM observations WHERE job_id = NEW.id
                )) OR (NEW.snapshot_id IS NOT NULL
                    AND NOT (NEW.status = 'done' AND NOT EXISTS (
                        SELECT 1 FROM snapshots
                        WHERE id = NEW.snapshot_id AND status BETWEEN 200 AND 299
                    ))
                    AND NOT EXISTS (
                        SELECT 1 FROM job_snapshots
                        WHERE job_id = NEW.id AND snapshot_id = NEW.snapshot_id
                    ))
                BEGIN SELECT RAISE(ABORT, 'observation snapshot must match job'); END;
        ''')
        for table in ('snapshots', 'observations', 'job_snapshots', 'runs'):
            for operation in ('UPDATE', 'DELETE'):
                self.db.execute(f'''CREATE TRIGGER IF NOT EXISTS immutable_{table}_{operation}
                    BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'Evidence ledger is append-only'); END''')
        self.db.commit()

    def open_run(self, inputs, *, new_run=False):
        encoded = json.dumps(inputs, sort_keys=True, ensure_ascii=False, allow_nan=False)
        fingerprint = stable_id(encoded)
        if not new_run:
            row = self.db.execute('SELECT id FROM runs WHERE fingerprint=? ORDER BY rowid DESC LIMIT 1', (fingerprint,)).fetchone()
            if row:
                return row['id']
        run_id = uuid.uuid4().hex
        self.db.execute('INSERT INTO runs VALUES (?,?,?,?)', (run_id, fingerprint, encoded, now()))
        self.db.commit()
        return run_id

    def enqueue(self, run_id, seed_id, kind, url, payload=None, *, commit=True):
        payload = payload or {}
        job_id = stable_id(run_id, seed_id, kind, url, payload.get('subject_id'))
        self.db.execute('''INSERT OR IGNORE INTO jobs
            (id,run_id,seed_id,kind,url,payload,updated_at) VALUES (?,?,?,?,?,?,?)''',
            (job_id, run_id, seed_id, kind, url, json.dumps(payload, sort_keys=True), now()))
        if commit:
            self.db.commit()
        return job_id

    def recover(self, run_id):
        self.db.execute("UPDATE jobs SET status='pending',reason='recovered_interruption' WHERE run_id=? AND status='running'", (run_id,))
        self.db.commit()

    def claim(self, run_id):
        row = self.db.execute("SELECT * FROM jobs WHERE run_id=? AND status='pending' ORDER BY rowid LIMIT 1", (run_id,)).fetchone()
        if row is None:
            return None
        self.db.execute("UPDATE jobs SET status='running',attempts=attempts+1,updated_at=? WHERE id=?", (now(), row['id']))
        self.db.commit()
        result = dict(row)
        result['attempts'] += 1
        result['payload'] = json.loads(result['payload'])
        return result

    def finish(self, job_id, status, reason=None, snapshot_id=None, observations=(), children=()):
        if status not in {'done', 'blocked', 'failed', 'unsupported', 'budget', 'pending'}:
            raise ValueError('Invalid job status')
        job = self.db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if job is None:
            raise ValueError('Unknown job')
        if status == 'done':
            snapshot = self.db.execute('SELECT status FROM snapshots WHERE id=?',
                                       (snapshot_id,)).fetchone()
            if snapshot is None or not 200 <= snapshot['status'] <= 299:
                raise ValueError('A done job requires a valid 2xx snapshot')
        snapshot = self.db.execute('SELECT * FROM snapshots WHERE id=?',
                                   (snapshot_id,)).fetchone() if snapshot_id else None
        for kind, payload in observations:
            if snapshot is None:
                raise ValueError('An observation requires retained evidence')
            validate_observation_provenance(job, snapshot, kind, payload, job['attempts'])
        with self.db:
            if snapshot_id is not None:
                self.db.execute('INSERT OR IGNORE INTO job_snapshots VALUES (?,?,?)',
                                (job_id, snapshot_id, job['attempts']))
            self.db.execute('UPDATE jobs SET status=?,reason=?,snapshot_id=?,updated_at=? WHERE id=?',
                            (status, reason, snapshot_id, now(), job_id))
            for kind, payload in observations:
                encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False)
                self.db.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)',
                                (stable_id(job_id, kind, encoded), job['run_id'], job_id, snapshot_id, kind, encoded))
            for child in children:
                self.enqueue(job['run_id'], job['seed_id'], commit=False, **child)

    def rows(self, table, run_id):
        if table not in {'jobs', 'observations'}:
            raise ValueError('Unknown run table')
        result = [dict(r) for r in self.db.execute(f'SELECT * FROM {table} WHERE run_id=? ORDER BY id', (run_id,))]
        for row in result:
            row['payload'] = json.loads(row['payload'])
        return result

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()
        self._lock.close()

    def count(self, table):
        if table != 'snapshots':
            raise ValueError('Unknown table')
        return self.db.execute('SELECT count(*) FROM snapshots').fetchone()[0]

    def snapshot(self, url, body, status, content_type):
        if not valid_snapshot_status(status):
            raise ValueError('Invalid snapshot status')
        digest = hashlib.sha256(body).hexdigest()
        relative = Path('raw') / digest[:2] / (digest + '.bin')
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError('Raw evidence hash mismatch')
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        record = dict(id=uuid.uuid4().hex, url=url, sha256=digest,
                      path=str(relative), status=status, content_type=content_type,
                      retrieved_at=now())
        self.db.execute('INSERT INTO snapshots VALUES (:id,:url,:sha256,:path,:status,:content_type,:retrieved_at)', record)
        self.db.commit()
        return record
