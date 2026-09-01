from flask_babel import lazy_gettext as _
from hiddifypanel.hutils import LazyLoader
requests=LazyLoader("requests")
from packaging.version import Version
import re
import sys

from hiddifypanel.models.config import hconfig, ConfigEnum
from hiddifypanel import __version__ as current_version
from hiddifypanel.cache import cache


to_gig_d = 1000 * 1000 * 1000


def error(str):
    print(str, file=sys.stderr)


@cache.cache(ttl=60000)
def get_latest_release_url(repo):
    latest_url = requests.get(f'{repo}/releases/latest', timeout=3).url.strip()
    version = latest_url.split('tag/')[1].strip()
    return (latest_url, version)


@cache.cache(ttl=86400)
def get_latest_release_version(repo_name):
    try:
        url = f"https://github.com/mn-hacker/{repo_name}/releases/latest"
        response = requests.head(url, allow_redirects=False, timeout=3)

        location_header = response.headers.get("Location")
        if location_header:
            version = re.search(r"/([^/]+)/?$", location_header)
            if version:
                ver = version.group(1).replace('v', '')
                if ver == "latest":
                    return get_latest_release_version(repo_name.replace("-", ""))
                return ver
    except Exception:
        return None

    return None


# watashi: channel aware update detection v12.2.69
def ws_release_channel() -> str:
    """The update channel of this box: 'release', 'beta' or 'develop'.

    Anything unknown, empty or broken falls back to 'release', which is the
    safe side: a release box must never be pushed onto a beta build.
    """
    try:
        pm = hconfig(ConfigEnum.package_mode)
        pm = str(pm or '').strip().lower()
    except Exception:
        return 'release'
    if pm in ('beta', 'develop'):
        return pm
    return 'release'


# watashi: channel aware update detection v12.2.69
def ws_tag_is_pre(tag) -> bool:
    """True when the tag smells of a pre-release build."""
    tag = str(tag or '').strip().lstrip('vV')
    if not tag:
        return False
    try:
        return bool(Version(tag).is_prerelease)
    except Exception:
        pass
    return bool(re.search(r'(b$|beta|dev|alpha)', tag, re.IGNORECASE))


# watashi: channel aware update detection v12.2.69
@cache.cache(ttl=3600)
def ws_latest_version(repo_name, channel='release'):
    """Newest tag of mn-hacker/<repo_name> that belongs to `channel`.

    The tag list is read instead of the release feed, because a beta build is
    published as a tag and never shows up as the latest release. The winner is
    picked by version order, never by list order.
    """
    channel = channel if channel in ('beta', 'develop') else 'release'
    try:
        url = f"https://api.github.com/repos/mn-hacker/{repo_name}/tags"
        response = requests.get(url, timeout=5)
        tags = response.json()
        if not isinstance(tags, list):
            return None
        best = None
        best_raw = None
        for item in tags:
            raw = item.get('name') if isinstance(item, dict) else None
            if not raw:
                continue
            cleaned = str(raw).strip().lstrip('vV')
            if not cleaned:
                continue
            if channel == 'release':
                # two locks, so a beta tag can never leak into a release box
                if ws_tag_is_pre(cleaned):
                    continue
                if re.search(r'(b$|beta|dev|alpha)', cleaned, re.IGNORECASE):
                    continue
            else:
                if not re.search(r'(b$|beta)', cleaned, re.IGNORECASE):
                    continue
            try:
                parsed = Version(cleaned)
            except Exception:
                continue
            if best is None or parsed > best:
                best = parsed
                best_raw = cleaned
        return best_raw
    except Exception as problem:
        print(f'could not read the tag list: {problem}')
    return None


# watashi: channel aware update detection v12.2.69
def ws_newest_for_this_box():
    """The only door the UI should knock on to ask for a newer version."""
    channel = ws_release_channel()
    newest = ws_latest_version('hiddifypanel', channel)
    if newest:
        return newest
    if channel == 'release':
        # deliberate fallback: the stable feed is reliable for a release box.
        # a beta box has no fallback on purpose, so it never lands on release.
        return get_latest_release_version('hiddifypanel')
    return None


def is_panel_outdated() -> bool:
    # watashi v12.2.69: channel aware -- a beta box is compared against beta tags
    try:
        if latest_v := ws_newest_for_this_box():
            if compare_versions(latest_v, current_version) == 1:
                return True
    except Exception as problem:  # watashi v12.2.60: silence hid real failures
        print(f'could not read the latest release: {problem}')
    return False


def compare_versions(version_1: str, version_2: str) -> int:
    """
    Compare two version strings and return an integer based on their relative order.
    Returns:
        int:

        - 1 if version_1 is greater than version_2.
        - 0 if version_1 is equal to version_2.
        - -1 if version_1 is less than version_2.

    Examples:
        >>> compare_versions("10.20.4", "10.20.4")
        0
        >>> compare_versions("10.20.4", "10.20.2")
        1
        >>> compare_versions("10.20.2", "10.20.4")
        -1
    """
    v1 = Version(version_1)
    v2 = Version(version_2)

    if v1 > v2:
        return 1  # version_1 is greater
    elif v2 > v1:
        return -1  # version_2 is greater
    else:
        return 0  # versions are equal
