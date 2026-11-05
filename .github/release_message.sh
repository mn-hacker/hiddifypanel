#!/usr/bin/env bash
# watashi v12.3.40dev: the old project name was taken out of this file (names, paths and links only)
#previous_release=$(curl --silent "https://api.github.com/repos/mn-hacker/watashi-panel/releases/latest" | grep -Po '"tag_name": "\K.*?(?=")')
pip install lastversion gitchangelog pystache >/dev/null 2>&1
previous_release=$(lastversion --at pip watashipanel)
current=$(cat watashipanel/VERSION)
gitchangelog "${previous_release}..v$current" ||echo "Error in change log"