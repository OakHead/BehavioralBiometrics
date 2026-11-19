"""Independent JSON profiles, including the original data/profile.json file."""
import json
import math
from pathlib import Path
import uuid


def validate_profile(profile):
    if not isinstance(profile, dict):
        raise ValueError('Invalid profile')
    for key, length in (('salt', 32), ('password', 64)):
        value = profile.get(key)
        if not isinstance(value, str) or len(value) != length:
            raise ValueError('Invalid profile credentials')
        try:
            bytes.fromhex(value)
        except ValueError as exc:
            raise ValueError('Invalid profile credentials') from exc
    for kind, dimensions in (('keyboard', (3,)), ('mouse', (3, 4)), ('mouse_enrollment', (4,))):
        rows = profile.get(kind, [])
        if not isinstance(rows, list):
            raise ValueError('Invalid enrollment samples')
        size = len(rows[0]) if rows and isinstance(rows[0], list) else None
        for row in rows:
            if (not isinstance(row, list) or len(row) not in dimensions or len(row) != size
                    or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in row)):
                raise ValueError('Invalid enrollment samples')
    if 'keyboard' not in profile or 'mouse' not in profile:
        raise ValueError('Missing enrollment samples')
    for key in ('mouse_speed_limit', 'mouse_peak_learning', 'key_hold_approved_max',
                'key_dwell_max_ms', 'key_dwell_learning_max_ms'):
        value = profile.get(key, 0)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError('Invalid saved detection limit')
    holds = profile.get('key_hold_samples', [])
    if not isinstance(holds, list) or len(holds) > 1000 or any(
            not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in holds):
        raise ValueError('Invalid saved key hold times')
    rates = profile.get('typing_speed_samples', [])
    if not isinstance(rates, list) or len(rates) > 240 or any(
            not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 for value in rates):
        raise ValueError('Invalid saved typing speeds')
    if not isinstance(profile.get('pause_mouse_while_typing', True), bool):
        raise ValueError('Invalid mouse-check setting')
    for field in ('heatmaps', 'approved_heatmaps', 'current_heatmaps'):
        maps = profile.get(field, {})
        if not isinstance(maps, dict):
            raise ValueError('Invalid saved mouse maps')
        from metrics import MouseHeatmap
        for key, data in maps.items():
            heatmap = MouseHeatmap.from_dict(data)
            if key != heatmap.layout.identifier:
                raise ValueError('Invalid mouse-map screen layout')
    if 'training' in profile:
        training = profile['training']
        if not isinstance(training, dict):
            raise ValueError('Invalid learning timer')
        for key in ('duration_seconds', 'elapsed_seconds'):
            value = training.get(key)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('Invalid learning time')
        if not 10 <= training['duration_seconds'] <= 3600 or not isinstance(training.get('complete'), bool):
            raise ValueError('Invalid learning timer')
    return profile


class ProfileStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path(self, identifier):
        if identifier == 'legacy':
            return self.directory/'profile.json'
        if len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
            raise ValueError('Invalid profile identifier')
        return self.directory/'profiles'/f'{identifier}.json'

    def selected_profile(self):
        try:
            identifier = json.loads((self.directory/'settings.json').read_text(encoding='utf-8')).get('selected_profile')
            if identifier is not None:
                self.path(identifier)
            return identifier
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    def remember_selected(self, identifier):
        if identifier is not None:
            self.path(identifier)
        temporary = self.directory/'settings.tmp'
        temporary.write_text(json.dumps({'selected_profile': identifier}), encoding='utf-8')
        temporary.replace(self.directory/'settings.json')

    def entries(self):
        paths = sorted((self.directory/'profiles').glob('*.json'))
        legacy = self.path('legacy')
        if legacy.exists():
            paths.insert(0, legacy)
        result = []
        for path in paths:
            identifier = 'legacy' if path == legacy else path.stem
            try:
                self.path(identifier)
            except ValueError:
                continue
            try:
                content = json.loads(path.read_text(encoding='utf-8'))
                name = str(content.get('name') or ('Original profile' if identifier == 'legacy' else identifier[:8]))
            except (OSError, ValueError, AttributeError):
                name = 'Unreadable profile '+identifier[:8]
            result.append((identifier, name))
        return result

    def load(self, identifier):
        return validate_profile(json.loads(self.path(identifier).read_text(encoding='utf-8')))

    def save(self, identifier, profile):
        validate_profile(profile)
        target = self.path(identifier)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(profile), encoding='utf-8')
        temporary.replace(target)

    def create(self, profile):
        name = str(profile.get('name', '')).strip()
        if not name or len(name) > 40:
            raise ValueError('Choose a profile name of 1 to 40 characters')
        if any(existing.casefold() == name.casefold() for _, existing in self.entries()):
            raise ValueError('A profile with this name already exists')
        identifier = uuid.uuid4().hex
        self.save(identifier, profile)
        return identifier

    def delete(self, identifier):
        self.path(identifier).unlink(missing_ok=True)
