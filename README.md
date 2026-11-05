<!-- watashi v12.3.40dev: rewritten for the new name; the old upstream text and links are gone -->
# watashi-panel

The web panel of [Watashi Manager](https://github.com/mn-hacker/Watashi-Manager): users, domains,
proxies, settings, backups and the Watashi theme. It is installed and updated together with the
manager; it is not published as a separate package.

The panel lives inside the manager repository as the `watashi-panel/src` submodule, and the
installer builds it from that source:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/mn-hacker/Watashi-Manager/main/common/download.sh)
```

## Working on the panel

```bash
git clone --recurse-submodules https://github.com/mn-hacker/Watashi-Manager.git
cd Watashi-Manager/watashi-panel/src
```

On a server the package is `watashipanel` inside `/opt/watashi-manager/.venv313`, and the command
line tool is `watashi-panel-cli` (for example `watashi-panel-cli admin-links`).

Website: https://watashi.cyou

## Credit

Watashi panel started as a fork of the panel of the Hiddify Manager project and keeps its license
(see `LICENSE.md`).
