#!/usr/bin/env python3
"""Discover publicly listed Dart Lions away league fixtures via Darthelfer's v2 API.

No browser, login, or write access to Darthelfer required.
Only distinct teams I, II, III are accepted; the opponent is the home side.
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

API = 'https://www.darthelfer.de/api/public/tournaments/v2'
OUT = Path('auswaerts-events.json')
TODAY = dt.datetime.now(ZoneInfo('Europe/Berlin')).date()
UUID = re.compile(r'^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$', re.I)
# Require an explicit team number to avoid confusing the three squads.
OWN = re.compile(r'^\s*(?:TSV\s*09\s*)?Dart\s*Lions(?:\s*(?:TSV\s*09))?\s*Gr[aä]fenberg\s*(I{1,3}|[123])\s*$', re.I)
VS = re.compile(r'\s+vs\.?\s+', re.I)


def read_old():
    try:
        data = json.loads(OUT.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def process(rows):
    matches = {}
    for e in rows:
        if not isinstance(e, dict) or str(e.get('turniersystem', '')).upper() != 'LIGASPIELTAG':
            continue
        title = ' '.join(str(e.get('bezeichnung') or '').split())
        sides = VS.split(title, maxsplit=1)
        if len(sides) != 2:
            continue
        home, away = (x.strip() for x in sides)
        # An away fixture: Dart Lions must be named on the right.
        own = OWN.fullmatch(away)
        if not own or OWN.fullmatch(home):
            continue
        day_str = str(e.get('beginnString') or '')
        try:
            day = dt.datetime.strptime(day_str, '%d.%m.%Y').date()
        except ValueError:
            continue
        # Future fixtures (60d) and a short post-match window for continuity.
        if not (-2 <= (day - TODAY).days <= 60):
            continue
        id_ = str(e.get('id') or '').lower()
        if not UUID.fullmatch(id_):
            continue
        matches[id_] = {'id': id_, 'day': day.isoformat(), 'opponent': home}
        print(f'FOUND {day}: {home} vs. {away} ({id_})')
    return sorted(matches.values(), key=lambda x: (x['day'], x['id']))


def main():
    old = read_old()
    try:
        req = Request(API, headers={'Accept': 'application/json', 'User-Agent': 'DartLions-LiveArena/1.0'})
        with urlopen(req, timeout=35) as r:
            data = json.load(r)
        if not isinstance(data, dict) or not isinstance(data.get('tournaments'), list):
            raise ValueError('Unexpected response: missing tournaments array')
        rows = list(data['tournaments'])
        live = data.get('liveTournaments', [])
        if isinstance(live, list):
            rows += live
        print(f'API returned {len(rows)} tournament records')
        events = process(rows)
        print(f'Verified upcoming/recent away fixtures: {len(events)}')
        status = 'ok'
    except Exception as exc:
        print(f'ERROR fetching Darthelfer API: {exc}', file=sys.stderr)
        # Never wipe known good fixtures because the API is temporarily down.
        events = old.get('events', []) if isinstance(old.get('events'), list) else []
        status = 'search_error'

    payload = {'status': status, 'events': events}
    # Do not create a new git commit if nothing meaningful changed.
    if payload != {'status': old.get('status'), 'events': old.get('events')}:
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'Updated {OUT}')
    else:
        print(f'No changes to {OUT}')
    if status != 'ok':
        sys.exit(1)


if __name__ == '__main__':
    main()
