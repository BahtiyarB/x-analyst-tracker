#!/usr/bin/env bash
# fetch_analysts.sh — analysts.yaml'daki her analist için jawond-bird ile
# "user-tweets <handle>" çalıştırır ve sonucu out/tweets_<handle>_<tarih>.json'a
# yazar. (Önceden "search from:<handle>" kullanılıyordu; user-tweets daha
# sağlam/doğrudan bir komut olduğu için tercih edildi — bkz. README "X
# kırılganlığı" bölümü.)
#
# Kullanım:
#   ./fetch_analysts.sh [TARIH]
#   TARIH verilmezse bugünün tarihi (YYYYMMDD) kullanılır.
#
# Auth: Canlı X cookie'si Chrome tarayıcısından okunur (--chrome-profile).
# Profil adı CHROME_PROFILE env değişkeniyle değiştirilebilir, varsayılan
# "Profile 2"dir (operatörün canlı X oturumu bu profilde).
#
#   CHROME_PROFILE="Profile 2" ./fetch_analysts.sh
#
# Cookie okunamazsa jawond hata verir; bu script o hatayı loglar ve diğer
# analistlerle devam eder (hata toleranslı).
#
# Bağımlılık YOK: PyYAML varsa onu kullanır, yoksa analysts.yaml'ı basit bir
# regex ile ayrıştırır (yalnızca bu dosyadaki sade "key: value" yapısını
# çözer; iç içe/karmaşık YAML için yeterli değildir).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/analysts.yaml"
JAWOND_BIN="${SCRIPT_DIR}/jawond-bird/dist/index.js"
OUT_DIR="${SCRIPT_DIR}/out"
DATE_TAG="${1:-$(date +%Y%m%d)}"
CHROME_PROFILE="${CHROME_PROFILE:-Profile 2}"

mkdir -p "${OUT_DIR}"

if [ ! -f "${CONFIG_FILE}" ]; then
  echo "HATA: analysts.yaml bulunamadi: ${CONFIG_FILE}" >&2
  exit 1
fi

if [ ! -f "${JAWOND_BIN}" ]; then
  echo "HATA: jawond-bird derlenmemis: ${JAWOND_BIN} yok. Once 'cd jawond-bird && npm install && npm run build' calistirin." >&2
  exit 1
fi

# analysts.yaml'i ayristirip "handle count" satirlari uretir (bir python
# one-liner ile). PyYAML varsa kullanir, yoksa basit bir dusme (fallback)
# parser'a gecer.
PARSE_PY=$(cat <<'PYEOF'
import re
import sys

path = sys.argv[1]

def fallback_parse(text):
    default_count = 50
    m = re.search(r'^default_count:\s*(\d+)', text, re.MULTILINE)
    if m:
        default_count = int(m.group(1))
    handles = re.findall(r'^\s*-\s*handle:\s*([A-Za-z0-9_]+)', text, re.MULTILINE)
    return default_count, handles

try:
    import yaml
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    default_count = data.get("default_count", 50)
    handles = [a["handle"] for a in data.get("analysts", []) if a.get("handle")]
except Exception:
    with open(path, "r") as f:
        text = f.read()
    default_count, handles = fallback_parse(text)

for h in handles:
    print(f"{h} {default_count}")
PYEOF
)

HANDLE_LIST=$(python3 -c "${PARSE_PY}" "${CONFIG_FILE}")

if [ -z "${HANDLE_LIST}" ]; then
  echo "HATA: analysts.yaml icinde handle bulunamadi." >&2
  exit 1
fi

TOTAL=0
FAILED=0

while read -r HANDLE COUNT; do
  [ -z "${HANDLE}" ] && continue
  TOTAL=$((TOTAL + 1))
  OUT_FILE="${OUT_DIR}/tweets_${HANDLE}_${DATE_TAG}.json"
  echo "==> ${HANDLE} (n=${COUNT}) -> ${OUT_FILE}"

  if node "${JAWOND_BIN}" user-tweets "${HANDLE}" -n "${COUNT}" --json --chrome-profile "${CHROME_PROFILE}" > "${OUT_FILE}.tmp" 2> "${OUT_DIR}/tweets_${HANDLE}_${DATE_TAG}.err"; then
    mv "${OUT_FILE}.tmp" "${OUT_FILE}"
    echo "    OK: ${OUT_FILE}"
  else
    FAILED=$((FAILED + 1))
    rm -f "${OUT_FILE}.tmp"
    echo "    HATA: ${HANDLE} icin cekim basarisiz. Detay: ${OUT_DIR}/tweets_${HANDLE}_${DATE_TAG}.err" >&2
  fi
done <<< "${HANDLE_LIST}"

echo "---"
echo "Toplam analist: ${TOTAL}, basarisiz: ${FAILED}"

# Bireysel analist hatalari script'i durdurmaz; ancak hicbiri basariliysa
# TOTAL==FAILED oldugunda cikis kodu 1 dondurur (CI/izleme icin sinyal).
if [ "${FAILED}" -gt 0 ] && [ "${FAILED}" -eq "${TOTAL}" ]; then
  exit 1
fi
exit 0
