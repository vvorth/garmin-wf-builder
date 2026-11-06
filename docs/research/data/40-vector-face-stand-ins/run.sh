#!/bin/sh
# Regenerates every comparison in this folder. FONTS is the Garmin font root
# (the SDK Manager's ConnectIQ/Fonts), CAND the folder the candidates were
# downloaded into (file names as below), PY a Python with Pillow+raqm and
# fontTools. Its tables are in comparisons.txt (run.sh > comparisons.txt).
set -eu
: "${FONTS:=$HOME/.Garmin/ConnectIQ/Fonts}" "${CAND:?}" "${PY:=python3}"
cd "$(dirname "$0")"
B="0123456789 10:08 ABCXYZ"
c() { "$PY" -I compare.py "$@"; }
c bionic-bold.png "Bionic Bold (BionicBold, 43 devices)" "$B" H \
  "Bionic Bold (Garmin, real)=$FONTS/Bionic_Bold.ttf" "Rajdhani Bold=$CAND/Rajdhani-Bold.ttf" \
  "Roboto Condensed Bold=$CAND/RobotoCondensed-Bold.ttf" "Saira Semi Condensed Bold=$CAND/SairaSemiCondensed-Bold.ttf" \
  "Barlow Semi Condensed Bold=$CAND/BarlowSemiCondensed-Bold.ttf" "Khand Bold=$CAND/Khand-Bold.ttf" \
  "Teko SemiBold=$CAND/Teko-600.ttf" "Roboto Black=$CAND/Roboto-Black.ttf"
c bionic-semibold.png "Bionic SemiBold (BionicSemiBold, 6 devices)" "$B" H \
  "Bionic SemiBold (Garmin, real)=$FONTS/Bionic_semibold.ttf" "Rajdhani SemiBold=$CAND/Rajdhani-SemiBold.ttf" \
  "Roboto Condensed Bold=$CAND/RobotoCondensed-Bold.ttf" "Saira Semi Condensed SemiBold=$CAND/SairaSemiCondensed-SemiBold.ttf" \
  "Barlow Semi Condensed SemiBold=$CAND/BarlowSemiCondensed-SemiBold.ttf" "Khand SemiBold=$CAND/Khand-SemiBold.ttf" \
  "Teko SemiBold=$CAND/Teko-600.ttf"
c bionic-medium.png "Bionic Medium (BionicMedium, 14 devices)" "$B" H \
  "Bionic Medium (Garmin, real)=$FONTS/Bionic_Medium.ttf" "Rajdhani Medium=$CAND/Rajdhani-Medium.ttf" \
  "Roboto Condensed Bold=$CAND/RobotoCondensed-Bold.ttf" "Saira Semi Condensed SemiBold=$CAND/SairaSemiCondensed-SemiBold.ttf" \
  "Barlow Semi Condensed SemiBold=$CAND/BarlowSemiCondensed-SemiBold.ttf" "Teko Medium=$CAND/Teko-500.ttf"
A="الثلاثاء ١٠:٠٨ 10:08"
c sakkal-majalla-roman.png "Sakkal Majalla Roman (SakkalMajallaRoman, 21 devices)" "$A" ا \
  "Sakkal Majalla (Garmin, real)=$FONTS/sakkal_majalla_roman.ttf" "Noto Naskh Arabic Regular=$CAND/NotoNaskhArabic-Regular.ttf" \
  "Amiri Regular=$CAND/Amiri-Regular.ttf" "Scheherazade New Regular=$CAND/ScheherazadeNew-Regular.ttf" \
  "Lateef Regular=$CAND/Lateef-Regular.ttf" "Noto Sans Arabic Regular=$CAND/NotoSansArabic-Regular.ttf"
c sakkal-majalla-bold.png "Sakkal Majalla Bold (SakkalMajallaBold, 21 devices)" "$A" ا \
  "Sakkal Majalla Bold (Garmin, real)=$FONTS/sakkal_majalla_bold.ttf" "Noto Naskh Arabic Bold=$CAND/NotoNaskhArabic-Bold.ttf" \
  "Amiri Bold=$CAND/Amiri-Bold.ttf" "Scheherazade New Bold=$CAND/ScheherazadeNew-Bold.ttf" \
  "Lateef Bold=$CAND/Lateef-Bold.ttf" "Noto Sans Arabic Bold=$CAND/NotoSansArabic-Bold.ttf"
H="יום שלישי 10:08 Tue ABCxyz"
c swiss-721-regular.png "Swiss 721 Hebrew Regular (Swiss721Regular, 21 devices)" "$H" ה \
  "Swis721Hebrew BT Roman (Garmin, real)=$FONTS/swiss_721_reg.ttf" "Arimo Regular=$CAND/Arimo-Regular.ttf" \
  "Noto Sans Hebrew Regular=$CAND/NotoSansHebrew-Regular.ttf" "Heebo Regular=$CAND/Heebo-400.ttf" \
  "Assistant Regular=$CAND/Assistant-400.ttf" "Rubik Regular=$CAND/Rubik-400.ttf"
c swiss-721-bold.png "Swiss 721 Hebrew Bold (Swiss721Bold, 21 devices)" "$H" ה \
  "Swis721Hebrew BT Bold (Garmin, real)=$FONTS/swiss_721_bd.ttf" "Arimo Bold=$CAND/Arimo-Bold.ttf" \
  "Noto Sans Hebrew Bold=$CAND/NotoSansHebrew-Bold.ttf" "Heebo Bold=$CAND/Heebo-700.ttf" \
  "Assistant Bold=$CAND/Assistant-700.ttf" "Rubik Bold=$CAND/Rubik-700.ttf"
