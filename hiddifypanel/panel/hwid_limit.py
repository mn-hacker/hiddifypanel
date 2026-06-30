"""Device (HWID) limit enforcement (ported from PasarGuard). Fully toggleable."""
from flask import request, g

from hiddifypanel.models import hconfig, ConfigEnum
from hiddifypanel.models import hwid as hwid_model

H_HWID = 'x-hwid'
H_DEVICE_OS = 'x-device-os'
H_VER_OS = 'x-ver-os'
H_DEVICE_MODEL = 'x-device-model'

R_ACTIVE = 'x-hwid-active'
R_LIMIT = 'x-hwid-limit'
R_NOT_SUPPORTED = 'x-hwid-not-supported'
R_MAX_REACHED = 'x-hwid-max-devices-reached'

MAX_HWID_LEN = 256


def is_enabled():
    return bool(hconfig(ConfigEnum.hwid_limit_enable))


def is_forced():
    return bool(hconfig(ConfigEnum.hwid_forced))


def is_local_request():
    try:
        if request.remote_addr != '127.0.0.1':
            return False
        if 'X-Forwarded-For' in request.headers:
            return False
        return True
    except Exception:
        return False


def is_enabled_for_user(user):
    if is_local_request():
        return False
    if user is not None and getattr(user, 'hwid_disabled', False):
        return False
    return is_enabled()


def get_effective_limit(user):
    per_user = getattr(user, 'hwid_limit', 0) or 0
    if per_user and per_user > 0:
        return int(per_user)
    try:
        return int(hconfig(ConfigEnum.hwid_limit_default) or 0)
    except (TypeError, ValueError):
        return 0


def read_headers():
    h = request.headers
    
    # Try multiple common HWID headers
    hwid = h.get(H_HWID)
    if not hwid:
        hwid = h.get('v2box-device-id') or h.get('x-device-id') or h.get('device-id') or h.get('hardware-id') or request.args.get('hwid') or request.args.get('device_id') or ''

    return dict(
        hwid=hwid.strip()[:MAX_HWID_LEN],
        device_os=(h.get(H_DEVICE_OS) or '').strip(),
        ver_os=(h.get(H_VER_OS) or '').strip(),
        device_model=(h.get(H_DEVICE_MODEL) or '').strip(),
    )


def enforce(user):
    g.hwid_active = False
    g.hwid_limit = 0
    g.hwid_not_supported = False
    g.hwid_max_reached = False
    if user is None or not is_enabled_for_user(user):
        return True
    g.hwid_active = True
    limit = get_effective_limit(user)
    g.hwid_limit = limit
    info = read_headers()
    hwid = info['hwid']
    if not hwid:
        if is_forced():
            g.hwid_not_supported = True
            return False
        return True
    existing = hwid_model.get_user_hwid_by_value(user.id, hwid)
    if existing is not None:
        hwid_model.register_user_hwid(user.id, hwid, device_os=info['device_os'], ver_os=info['ver_os'], device_model=info['device_model'], commit=True)
        return True
    if limit and limit > 0:
        if hwid_model.get_user_hwid_count(user.id) >= limit:
            g.hwid_max_reached = True
            return False
    hwid_model.register_user_hwid(user.id, hwid, device_os=info['device_os'], ver_os=info['ver_os'], device_model=info['device_model'], commit=True)
    return True


def apply_response_headers(resp):
    try:
        if getattr(g, 'hwid_active', False):
            resp.headers[R_ACTIVE] = '1'
            resp.headers[R_LIMIT] = str(getattr(g, 'hwid_limit', 0))
        if getattr(g, 'hwid_not_supported', False):
            resp.headers[R_NOT_SUPPORTED] = '1'
        if getattr(g, 'hwid_max_reached', False):
            resp.headers[R_MAX_REACHED] = '1'
    except Exception:
        pass
    return resp
