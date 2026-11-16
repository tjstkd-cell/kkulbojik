# -*- coding: utf-8 -*-
"""오늘의 꿀보직 - 공공 채용공고 수집기

공공데이터포털 API 3개에서 진행 중인 공고를 모아 jobs.json 으로 저장합니다.
  1) 재정경제부_공공기관 채용정보 조회서비스  (alio)
  2) 인사혁신처_공공취업정보 조회 서비스      (나라일터)
  3) 한국노인인력개발원 노인 구인정보         (어르신 일자리)

인증키는 환경변수 DATA_GO_KR_KEY 또는 같은 폴더의 .env 파일(DATA_GO_KR_KEY=...)에서 읽습니다.
실행: python fetch_jobs.py
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "jobs.json")
KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime("%Y%m%d")


def load_key():
    key = os.environ.get("DATA_GO_KR_KEY", "").strip()
    env = os.path.join(HERE, ".env")
    if not key and os.path.exists(env):
        with open(env, encoding="utf-8-sig") as f:
            for line in f:
                if line.strip().startswith("DATA_GO_KR_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        sys.exit("인증키가 없습니다. .env 파일에 DATA_GO_KR_KEY=인증키 를 넣어주세요.")
    # 'Encoding' 키를 붙여넣은 경우도 처리
    return urllib.parse.unquote(key)


KEY = load_key()


def get(url, params, tries=3):
    q = urllib.parse.urlencode({"serviceKey": KEY, **params})
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url + "?" + q, headers={"User-Agent": "kkulbojik-fetcher/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # 네트워크 오류 재시도
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"요청 실패: {url} ({last})")


def ymd(s):
    s = "".join(ch for ch in str(s or "") if ch.isdigit())
    return s[:8] if len(s) >= 8 else ""


# ---------------------------------------------------------------- 1) 공공기관 (alio)
def fetch_alio():
    url = "https://apis.data.go.kr/1051000/recruitment/list"
    out, page = [], 1
    while page <= 20:
        txt = get(url, {"numOfRows": 100, "pageNo": page, "ongoingYn": "Y", "resultType": "json"})
        data = json.loads(txt)
        if str(data.get("resultCode")) not in ("200", "0", "00"):
            raise RuntimeError(f"alio 오류: {data.get('resultCode')} {data.get('resultMsg')}")
        rows = data.get("result") or []
        for j in rows:
            out.append({
                "id": f"A{j.get('recrutPblntSn')}",
                "instNm": j.get("instNm", ""),
                "recrutPbancTtl": j.get("recrutPbancTtl", ""),
                "hireTypeNmLst": j.get("hireTypeNmLst", ""),
                "workRgnNmLst": j.get("workRgnNmLst", ""),
                "recrutSeNm": j.get("recrutSeNm", ""),
                "recrutNope": j.get("recrutNope") or 0,
                "pbancBgngYmd": ymd(j.get("pbancBgngYmd")),
                "pbancEndYmd": ymd(j.get("pbancEndYmd")),
                "srcUrl": (j.get("srcUrl") or "").strip()
                or f"https://job.alio.go.kr/recruitview.do?idx={j.get('recrutPblntSn')}",
                "ncsCdNmLst": j.get("ncsCdNmLst", ""),
                "cat": "공공기관",
                "_source": "alio",
            })
        if len(rows) < 100 or len(out) >= int(data.get("totalCount") or 0):
            break
        page += 1
    return out


# ---------------------------------------------------------------- 2) 나라일터
NARA_TYPES = {  # 공고유형 -> (고용형태 표시, 신입/경력)
    "e01": ("공개채용", "신입+경력"),
    "e02": ("경력채용", "경력"),
    "e03": ("계약직", "신입+경력"),
    "e04": ("행정지원인력", "신입+경력"),
}
NARA_INST = {"g01": "국가공무원", "g02": "지방공무원", "g03": "공공기관", "g04": "교육청"}


def xml_items(txt):
    root = ET.fromstring(txt)
    code = (root.findtext(".//resultCode") or "").strip()
    if code and code not in ("00", "0", "0000", "200"):
        raise RuntimeError(f"오류 {code} {root.findtext('.//resultMsg')}")
    total = int((root.findtext(".//totalCount") or "0").strip() or 0)
    items = [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
    return items, total


def fetch_nara():
    url = "https://apis.data.go.kr/1760000/PblJobService/getList"
    begin = (datetime.now(KST) - timedelta(days=45)).strftime("%Y-%m-%d")
    out, seen = [], set()
    for ty, (hire, career) in NARA_TYPES.items():
        page = 1
        while page <= 10:
            txt = get(url, {"pageNo": page, "numOfRows": 100, "Pblanc_ty": ty, "Instt_se": "",
                            "Begin_de": begin, "Sort_order": "DESC"})
            items, total = xml_items(txt)
            for j in items:
                end = ymd(j.get("enddate"))
                if not end or end < TODAY or j.get("idx") in seen:
                    continue
                seen.add(j.get("idx"))
                inst = NARA_INST.get(j.get("type01", ""), "")
                out.append({
                    "id": f"N{j.get('idx')}",
                    "instNm": j.get("insttname", ""),
                    "recrutPbancTtl": j.get("title", ""),
                    "hireTypeNmLst": hire,
                    "workRgnNmLst": j.get("areaname") or "",
                    "recrutSeNm": career,
                    "recrutNope": 0,
                    "pbancBgngYmd": ymd(j.get("regdate")),
                    "pbancEndYmd": end,
                    "srcUrl": f"https://www.gojobs.go.kr/apmView.do?empmnsn={j.get('idx')}",
                    "instKind": inst,
                    "cat": "공공기관" if j.get("type01") == "g03" else "공무원·공무직",
                    "_source": "nara",
                })
            if len(items) < 100 or page * 100 >= total:
                break
            page += 1
    return out


# ---------------------------------------------------------------- 3) 어르신 (노인 구인정보)
SENIOR_HIRE = {"CM0101": "정규직", "CM0102": "계약직", "CM0103": "시간제", "CM0104": "일당직", "CM0105": "기타"}
SIDO = {"서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "광주",
        "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기", "강원도": "강원",
        "강원특별자치도": "강원", "충청북도": "충북", "충청남도": "충남", "전라북도": "전북", "전북특별자치도": "전북",
        "전라남도": "전남", "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주"}


def split_addr(addr):
    """'07591 서울특별시 강서구 양천로 ...' -> ('서울', '서울 강서구')"""
    parts = [p for p in (addr or "").split() if not p.isdigit()]
    if not parts:
        return "", ""
    sido = SIDO.get(parts[0], parts[0][:2])
    gu = parts[1] if len(parts) > 1 and parts[1][-1:] in "시군구" else ""
    return sido, (sido + " " + gu).strip()


def senior_detail(job_id):
    try:
        items, _ = xml_items(get("https://apis.data.go.kr/B552474/SenuriService/getJobInfo", {"id": job_id}))
        return items[0] if items else {}
    except Exception:
        return {}


def fetch_senior():
    from concurrent.futures import ThreadPoolExecutor
    url = "https://apis.data.go.kr/B552474/SenuriService/getJobList"
    rows, page = [], 1
    while page <= 30:  # 최신 공고가 앞쪽에 있음. 진행 중 공고가 없는 페이지가 나오면 중단
        items, total = xml_items(get(url, {"pageNo": page, "numOfRows": 100}))
        open_items = [j for j in items if j.get("deadline") != "마감" and ymd(j.get("toDd")) >= TODAY]
        rows += open_items
        if not items or (page >= 3 and not open_items) or page * 100 >= total:
            break
        page += 1
    with ThreadPoolExecutor(max_workers=6) as ex:
        details = list(ex.map(lambda j: senior_detail(j.get("jobId")), rows))
    out = []
    for j, d in zip(rows, details):
        jid = j.get("jobId", "")
        sido, area = split_addr(d.get("plDetAddr"))
        home = (d.get("homepage") or "").strip()
        if home and not home.startswith("http"):
            home = "http://" + home
        if j.get("stmId") == "B":  # 고용24(워크넷) 등록 공고
            src = ("https://www.work24.go.kr/wk/a/b/1500/empDetailAuthView.do?wantedAuthNo="
                   f"{jid}&infoTypeCd=VALIDATION&infoTypeGroup=tb_workinfoworknet")
        else:
            src = home
        age = (d.get("age") or "").strip()
        out.append({
            "id": f"S{jid}",
            "instNm": d.get("plbizNm") or j.get("oranNm", ""),
            "recrutPbancTtl": d.get("wantedTitle") or j.get("recrtTitle", ""),
            "hireTypeNmLst": SENIOR_HIRE.get(j.get("emplymShp", ""), j.get("emplymShpNm", "")),
            "workRgnNmLst": sido,
            "area": area,
            "recrutSeNm": f"{age}세 이상" if age.isdigit() else "",
            "recrutNope": int(d["clltPrnnum"]) if (d.get("clltPrnnum") or "").isdigit() else 0,
            "pbancBgngYmd": ymd(j.get("frDd")),
            "pbancEndYmd": ymd(j.get("toDd")),
            "srcUrl": src,
            "cat": "어르신",
            "_source": "senior",
        })
    return out


def previous_rows(source):
    """해당 출처가 실패했을 때 어제 저장본에서 아직 마감 안 된 공고를 재사용"""
    try:
        with open(OUT, encoding="utf-8") as f:
            old = json.load(f).get("result", [])
        return [j for j in old if j.get("_source") == source and j.get("pbancEndYmd", "") >= TODAY]
    except Exception:
        return []


def main():
    all_jobs, report = [], {}
    for name, fn in (("alio", fetch_alio), ("nara", fetch_nara), ("senior", fetch_senior)):
        try:
            rows = fn()
            report[name] = len(rows)
            all_jobs += rows
        except Exception as e:
            kept = previous_rows(name)
            all_jobs += kept
            report[name] = f"실패(이전 {len(kept)}건 유지): {e}"
    ok = [v for v in report.values() if isinstance(v, int)]
    print(json.dumps(report, ensure_ascii=False))
    if not ok or sum(ok) == 0:
        sys.exit("모든 출처에서 공고를 못 가져왔습니다. 기존 jobs.json 을 유지합니다.")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    payload = {
        "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "count": len(all_jobs),
        "sources": report,
        "result": all_jobs,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"저장 완료: {OUT} ({len(all_jobs)}건)")


if __name__ == "__main__":
    main()
