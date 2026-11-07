#!/bin/sh
# After installing and upgrading the package: sets up the Icenux package source (the shared APT
# repository of the Icenux applications) so later versions arrive with `apt upgrade`.
# The source files do not belong to the package (several Icenux applications would collide on one
# path): this script writes them, the list only when it is missing, the key always.
set -e
lib=/usr/lib/livem

if [ -d /etc/apt/sources.list.d ] && [ -f "$lib/icenux.asc" ]; then
    install -d /usr/share/keyrings
    install -m 644 "$lib/icenux.asc" /usr/share/keyrings/icenux.asc
    [ -e /etc/apt/sources.list.d/icenux.list ] ||
        install -m 644 "$lib/icenux.list" /etc/apt/sources.list.d/icenux.list
    sed -i 's#luquas95\.github\.io/icenux/#icenux.github.io/icenux/#g' /etc/apt/sources.list.d/icenux.list
fi
exit 0
