"""Reconcile transport metrics with durable mail and provider input observations."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3


def audit(directory):
    directory = Path(directory)
    metrics = json.loads((directory/'result.json').read_text())
    with sqlite3.connect(directory/'sessions'/'_agent_runtime'/'runs.sqlite3') as db:
        mail = db.execute("SELECT session,recipient,text,state FROM mailbox WHERE text LIKE 'MAIL-%'").fetchall()
        assert len(mail) == metrics['messages']
        assert len({(s, r, t) for s, r, t, _ in mail}) == len(mail)
        assert all(state == 'delivered' for _, _, _, state in mail)
        active = db.execute("SELECT count(*) FROM agents WHERE state IN ('running','cancelling')").fetchone()[0]
        assert active == 0
        attempts = dict(db.execute('SELECT state,count(*) FROM attempts GROUP BY state'))
        assert sum(attempts.values()) == metrics['attempts']
        outstanding = db.execute("SELECT recipient,state,count(*) FROM mailbox WHERE state <> 'delivered' GROUP BY recipient,state").fetchall()
        assert all(recipient == 'parent' and state == 'queued' for recipient, state, _ in outstanding), outstanding
        final_states = dict(db.execute('SELECT state,count(*) FROM agents GROUP BY state'))
    records = [json.loads(line) for line in (directory/'model.jsonl').read_text().splitlines()]
    observed = set()
    for record in records:
        key = record['key']
        if key == 'auxiliary':
            continue
        token, _, slot = key.partition('/')
        for message in record['mail']:
            assert message.startswith(('MAIL-'+token+'-', 'UP-'+token+'-')), (key, message)
            if slot and message.startswith('MAIL-'):
                assert message == f'MAIL-{token}-slot{slot}', (key, message)
                observed.add(message)
    assert observed == {t for _, _, t, _ in mail}
    resources = [json.loads(line) for line in (directory/'events.jsonl').read_text().splitlines()]
    samples = [r for r in resources if 'rss_bytes' in r]
    result = dict(status='passed', unique_mail_rows=len(mail), provider_observed_unique_mail=len(observed),
        mail_state=dict(Counter(state for *_, state in mail)), cross_session_mail_violations=0,
        active_agents=active, final_agent_states=final_states, attempts=attempts,
        parent_outstanding=outstanding, provider_requests=len(records),
        max_rss_bytes=max(r['rss_bytes'] for r in samples), max_handles=max(r['handles'] for r in samples),
        resource_scope='samples from periodically restarted backends; not proof of unbounded lifetime stability')
    (directory/'audit.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('directory')
    print(json.dumps(audit(parser.parse_args().directory)))
