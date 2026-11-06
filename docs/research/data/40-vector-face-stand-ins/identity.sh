#!/bin/sh
# Compares each Garmin file with the free file the registry installs for it.
# FONTS is the Garmin font root, FREE the folder `fetch-system-fonts.ts
# --registry` installed into (files named <key>.ttf), PY a Python with fontTools.
set -eu
: "${FONTS:=$HOME/.Garmin/ConnectIQ/Fonts}" "${FREE:?}" "${PY:=python3}"
cd "$(dirname "$0")"
while read garmin key; do
  printf 'sha256 %s %s\n' "$(sha256sum < "$FONTS/$garmin.ttf" | cut -c1-16)" "$(sha256sum < "$FREE/$key.ttf" | cut -c1-16)"
  "$PY" -I identity.py "$FONTS/$garmin.ttf" "$FREE/$key.ttf"
done <<'PAIRS'
Bionic_Bold rajdhani-bold
Bionic_Bold_Number_Only rajdhani-bold
Bionic_semibold rajdhani-semibold
Bionic_Medium rajdhani-medium
Kosugi-Regular kosugi-regular
Kosugi-Regular-2 kosugi-regular
Kosugi-Regular-3 kosugi-regular
Kosugi-Regular-Outdoor kosugi-regular
NotoSansSC-Medium noto-sans-sc-medium
NotoSansSC-Medium-2 noto-sans-sc-medium
NotoSansSC-Medium-3 noto-sans-sc-medium
NotoSansSC-Medium-Outdoor noto-sans-sc-medium
NotoNaskhArabic-Regular noto-naskh-arabic-regular
NotoNaskhArabic-Bold noto-naskh-arabic-bold
NotoSansHebrew-Regular noto-sans-hebrew-regular
NotoSansHebrew-Bold noto-sans-hebrew-bold
NotoSansArmenian-Regular noto-sans-armenian-regular
NotoSansArmenian-Bold noto-sans-armenian-bold
NanumGothic-Regular nanumgothic-regular
NanumGothic-Bold nanumgothic-bold
NanumGothic-ExtraBold nanumgothic-extrabold
Pridi-Regular pridi-regular
Pridi-Regular_Garmin pridi-regular-garmin
Pridi-SemiBold_Garmin pridi-semibold-garmin
RobotoCondensed-Bold roboto-condensed-bold
RobotoCondensed-Regular roboto-condensed-regular
RobotoCondensed-RegularItalic roboto-condensed-italic
Roboto-Regular roboto-regular
Roboto-Italic roboto-italic
Roboto-Medium-Outdoor roboto-medium
Roboto-Black roboto-black
PAIRS
