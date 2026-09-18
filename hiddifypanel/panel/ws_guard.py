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
