#!/usr/bin/env bash
# 당근 split APK → debuggable 재패키징(무루팅 run-as 주입/수확용).
# base.apk 만 debuggable=true 로 패치, 4개 split 전부 동일키 재서명(split 세션 서명일치 필수).
# 필요: java(17+). apktool.jar / uber-apk-signer.jar 는 없으면 자동 다운로드.
#
# 사용: bash tools/repackage_karrot.sh
# 입력: out/apk/{base,split_*}.apk   출력: out/apk/signed/*.apk
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APKDIR="$ROOT/out/apk"
TOOLS="$ROOT/out/tools"
WORK="$ROOT/out/work"
OUT="$APKDIR/signed"
mkdir -p "$TOOLS" "$OUT"
rm -rf "$WORK"; mkdir -p "$WORK"

APKTOOL="$TOOLS/apktool.jar"
SIGNER="$TOOLS/uber-apk-signer.jar"
APKTOOL_URL="https://github.com/iBotPeaches/Apktool/releases/download/v2.10.0/apktool_2.10.0.jar"
SIGNER_URL="https://github.com/patrickfav/uber-apk-signer/releases/download/v1.3.0/uber-apk-signer-1.3.0.jar"

[ -f "$APKTOOL" ] || { echo "apktool 다운로드…"; curl -L -o "$APKTOOL" "$APKTOOL_URL"; }
[ -f "$SIGNER" ]  || { echo "uber-apk-signer 다운로드…"; curl -L -o "$SIGNER" "$SIGNER_URL"; }

echo "== base.apk 디코드(소스 생략 -s: 난독dex 우회, manifest/res만) =="
java -jar "$APKTOOL" d -s -f -o "$WORK/base" "$APKDIR/base.apk"

echo "== debuggable=true 패치 =="
MAN="$WORK/base/AndroidManifest.xml"
if grep -q 'android:debuggable' "$MAN"; then
  sed -i '' -E 's/android:debuggable="[^"]*"/android:debuggable="true"/' "$MAN"
else
  # <application 태그에 속성 삽입
  sed -i '' -E 's/(<application )/\1android:debuggable="true" /' "$MAN"
fi
grep -o 'android:debuggable="[^"]*"' "$MAN" | head -1

echo "== 누락 attr 정의 주입(Glance aapt2 링크 우회) =="
cat > "$WORK/base/res/values/apktool_fix_attrs.xml" <<'XML'
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <attr name="glance_isTopLevelLayout" format="boolean" />
</resources>
XML

echo "== base 리빌드 =="
java -jar "$APKTOOL" b -o "$WORK/base-patched.apk" "$WORK/base"

echo "== 서명 대상 모으기(패치된 base + 원본 splits) =="
STAGE="$WORK/tosign"; mkdir -p "$STAGE"
cp "$WORK/base-patched.apk" "$STAGE/base.apk"
for s in "$APKDIR"/split_*.apk; do cp "$s" "$STAGE/"; done

echo "== 동일키 재서명(uber-apk-signer) =="
java -jar "$SIGNER" --apks "$STAGE" --out "$OUT" --allowResign

echo "== 완료 =="
ls -la "$OUT"
echo "다음: bash tools/install_karrot.sh"
