"""watashi v12.2.130n: the one way to reach the backup guard.

The guard is a single file with no web needs, but it lives inside
panel/admin/, and importing anything from that package runs
panel/admin/__init__.py first. That imports DomainAdmin, and DomainAdmin
translates a validator message while its class body runs, which needs babel.
In the panel that is fine, babel is registered. In a command line run
(hiddify-panel-cli backup, called by backup.sh before every update) and in the
restore worker there is no babel, so the import died with KeyError: 'babel'—
the secrets were dropped from the backup and the restore stopped before it had
read a single row.

So the file is loaded from its own path and the package is left asleep.
"""
import importlib.util
import os

_cache = {}


def guard_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, 'admin', 'ws_backup_guard.py')


def load_guard():
    """The guard module, with no side effects on the admin package."""
    if _cache.get('mod') is not None:
        return _cache['mod']
    path = guard_path()
    if os.path.exists(path):
        spec = importlib.util.spec_from_file_location('ws_backup_guard_solo', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _cache['mod'] = module
        return module
    # a panel installed as a package still has it in the usual place
    from hiddifypanel.panel.admin import ws_backup_guard as fallback
    _cache['mod'] = fallback
    return fallback


def can_write(folder) -> bool:
    """A real write. os.access lies about group and setgid bits."""
    probe = os.path.join(folder, '.watashi-write-probe')
    try:
        with open(probe, 'w') as fh:
            fh.write('ok')
        os.remove(probe)
        return True
    except Exception:
        return False


def panel_base() -> str:
    """Where the panel lives, as this process sees it."""
    base = os.environ.get('HIDDIFY_CONFIG_PATH', '/opt/hiddify-manager/')
    try:
        from flask import current_app
        base = current_app.config.get('HIDDIFY_CONFIG_PATH', base)
    except Exception:
        pass
    return base


def pick_backup_root(base=None, note=None) -> str:
    """watashi v12.2.130o: the backup folder, or the best place we may write.

    The panel service runs as hiddify-panel while /opt/hiddify-manager
    belongs to root at 755, so on a server whose install never prepared
    this folder nothing there can be created. The nightly backup and the
    snapshot taken before a restore both ask here, so the answer can
    never differ between them again.

    note is an optional callable for the one sentence we may need to say.
    """
    import tempfile
    base = base or panel_base()
    first = os.path.join(base, 'backup')
    tried = []
    for folder in (first,
                   os.path.join(base, 'hiddify-panel', 'backup'),
                   os.path.join(base, 'log', 'backup'),
                   os.path.join(tempfile.gettempdir(), 'watashi-backup')):
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception as problem:
            tried.append('%s (%s)' % (folder, problem))
            continue
        if can_write(folder):
            if folder != first and note:
                note('watashi: %s cannot be written, %s is used instead'
                     % (first, folder))
            return folder
        tried.append('%s (nothing can be written in it)' % folder)
    if note:
        note('watashi: no folder can hold the backups: %s' % '; '.join(tried))
    return first
