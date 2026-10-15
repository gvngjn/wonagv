"""한국투자증권 Open API — 모의투자 전용 클라이언트.

실전 서버 주소와 실전 거래 ID(TTTC...)는 이 파일에 일부러 넣지 않았다.
모의투자 서버(openapivts)에만 접속하므로 실제 돈이 오가는 주문은 나갈 수 없다.

필요한 환경변수 (한국투자증권 KIS Developers에서 '모의투자' 앱으로 발급):
  KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT (예: 50012345-01)
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import Bar, Side

MOCK_BASE_URL = "https://openapivts.koreainvestment.com:29443"

TR_BUY = "VTTC0012U"
TR_SELL = "VTTC0011U"
TR_BALANCE = "VTTC8434R"
TR_DAILY_CHART = "FHKST03010100"

# 모의투자 서버는 초당 호출 수 제한이 낮아서 호출 사이에 쉰다
MIN_INTERVAL_SEC = 0.6

# (method, url, headers, body) -> (status, response headers, json body)
Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, dict[str, str], Any]]


class KisError(Exception):
    pass


def urllib_transport(method: str, url: str, headers: dict[str, str], body: bytes | None):
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return res.status, {k.lower(): v for k, v in res.headers.items()}, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"msg1": raw.decode("utf-8", "replace")}
        return e.code, {k.lower(): v for k, v in e.headers.items()}, payload


@dataclass(frozen=True)
class KisConfig:
    app_key: str
    app_secret: str
    account_no: str  # 종합계좌번호 8자리
    account_product: str = "01"  # 계좌상품코드 2자리
    token_path: Path = Path.home() / ".trendbot" / "kis_mock_token.json"

    @classmethod
    def from_env(cls) -> KisConfig:
        missing = [k for k in ("KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT") if not os.environ.get(k)]
        if missing:
            raise KisError("환경변수가 없습니다: " + ", ".join(missing))
        account = os.environ["KIS_ACCOUNT"].replace("-", "")
        if len(account) != 10 or not account.isdigit():
            raise KisError("KIS_ACCOUNT 는 '12345678-01' 형식이어야 합니다")
        return cls(os.environ["KIS_APP_KEY"], os.environ["KIS_APP_SECRET"], account[:8], account[8:])


@dataclass(frozen=True)
class Holding:
    symbol: str
    name: str
    quantity: int
    avg_price: float
    price: float


@dataclass(frozen=True)
class Balance:
    cash: float  # D+2 예수금 (결제 예정 반영)
    holdings: dict[str, Holding]


class KisMockClient:
    def __init__(
        self,
        config: KisConfig,
        transport: Transport = urllib_transport,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.config = config
        self.base_url = MOCK_BASE_URL
        self._transport = transport
        self._sleep = sleep
        self._now = now
        self._token: str | None = None
        self._last_call = 0.0

    # ---- 인증 ---------------------------------------------------------
    def token(self) -> str:
        if self._token:
            return self._token
        cached = self._read_cached_token()
        if cached:
            self._token = cached
            return cached
        body = json.dumps({
            "grant_type": "client_credentials",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
        }).encode()
        status, _, data = self._transport(
            "POST", f"{self.base_url}/oauth2/tokenP", {"content-type": "application/json"}, body
        )
        if status != 200 or "access_token" not in data:
            raise KisError(f"토큰 발급 실패 ({status}): {data.get('error_description') or data.get('msg1') or data}")
        self._token = data["access_token"]
        self._save_token(self._token, data.get("access_token_token_expired", ""))
        return self._token

    def _read_cached_token(self) -> str | None:
        try:
            saved = json.loads(self.config.token_path.read_text())
            expires = datetime.strptime(saved["expires"], "%Y-%m-%d %H:%M:%S")
        except (OSError, ValueError, KeyError):
            return None
        if saved.get("app_key") != self.config.app_key or expires - timedelta(minutes=10) <= self._now():
            return None
        return saved["token"]

    def _save_token(self, token: str, expires: str) -> None:
        if not expires:
            return
        path = self.config.token_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"token": token, "expires": expires, "app_key": self.config.app_key}))
        try:
            path.chmod(0o600)
        except OSError:
            pass

    # ---- 공통 호출 ----------------------------------------------------
    def _call(self, method: str, path: str, tr_id: str, params: dict[str, str], tr_cont: str = ""):
        wait = MIN_INTERVAL_SEC - (time.monotonic() - self._last_call)
        if wait > 0:
            self._sleep(wait)
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.token()}",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
            "tr_id": tr_id,
            "tr_cont": tr_cont,
            "custtype": "P",
        }
        url = f"{self.base_url}{path}"
        body = None
        if method == "GET":
            url += "?" + urllib.parse.urlencode(params)
        else:
            body = json.dumps(params).encode()
        status, res_headers, data = self._transport(method, url, headers, body)
        self._last_call = time.monotonic()
        if status != 200 or str(data.get("rt_cd")) != "0":
            raise KisError(f"{tr_id} 실패 ({status}) {data.get('msg_cd', '')} {data.get('msg1', '')}".strip())
        return res_headers, data

    # ---- 시세 ---------------------------------------------------------
    def daily_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        """수정주가 일봉. 한 번에 최근 100개까지만 오므로 가장 오래된 날짜 앞으로 이어서 받는다."""
        bars: dict[date, Bar] = {}
        chunk_end = end
        for _ in range(100):
            _, data = self._call("GET", "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice", TR_DAILY_CHART, {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": chunk_end.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",
            })
            days = []
            for row in data.get("output2") or []:
                if not row.get("stck_bsop_date"):
                    continue
                bar = Bar(
                    day=datetime.strptime(row["stck_bsop_date"], "%Y%m%d").date(),
                    open=float(row["stck_oprc"]),
                    high=float(row["stck_hgpr"]),
                    low=float(row["stck_lwpr"]),
                    close=float(row["stck_clpr"]),
                    volume=float(row.get("acml_vol") or 0),
                )
                days.append(bar.day)
                if bar.open > 0 and start <= bar.day <= end:  # 거래정지일은 시가 0으로 온다
                    bars[bar.day] = bar
            if not days or min(days) <= start:
                break
            chunk_end = min(days) - timedelta(days=1)
        return [bars[d] for d in sorted(bars)]

    # ---- 계좌 ---------------------------------------------------------
    def balance(self) -> Balance:
        holdings: dict[str, Holding] = {}
        cash = 0.0
        fk = nk = tr_cont = ""
        for _ in range(20):
            res_headers, data = self._call("GET", "/uapi/domestic-stock/v1/trading/inquire-balance", TR_BALANCE, {
                "CANO": self.config.account_no,
                "ACNT_PRDT_CD": self.config.account_product,
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "00",
                "CTX_AREA_FK100": fk,
                "CTX_AREA_NK100": nk,
            }, tr_cont)
            for row in data.get("output1") or []:
                qty = int(float(row.get("hldg_qty") or 0))
                if qty > 0:
                    holdings[row["pdno"]] = Holding(
                        row["pdno"], row.get("prdt_name", ""), qty,
                        float(row.get("pchs_avg_pric") or 0), float(row.get("prpr") or 0),
                    )
            summary = (data.get("output2") or [{}])[0]
            cash = float(summary.get("prvs_rcdl_excc_amt") or summary.get("dnca_tot_amt") or 0)
            if res_headers.get("tr_cont") not in ("M", "F"):
                break
            fk, nk, tr_cont = data.get("ctx_area_fk100", ""), data.get("ctx_area_nk100", ""), "N"
        return Balance(cash, holdings)

    def market_order(self, symbol: str, side: Side, quantity: int) -> str:
        """시장가 주문. 장 시작 전(08:30~)에 내면 시초가로 체결된다. 주문번호를 돌려준다."""
        if quantity <= 0:
            raise KisError("주문 수량은 1주 이상이어야 합니다")
        _, data = self._call("POST", "/uapi/domestic-stock/v1/trading/order-cash", TR_BUY if side is Side.BUY else TR_SELL, {
            "CANO": self.config.account_no,
            "ACNT_PRDT_CD": self.config.account_product,
            "PDNO": symbol,
            "ORD_DVSN": "01",
            "ORD_QTY": str(quantity),
            "ORD_UNPR": "0",
            "EXCG_ID_DVSN_CD": "KRX",
            "SLL_TYPE": "01" if side is Side.SELL else "",
            "CNDT_PRIC": "",
        })
        return str((data.get("output") or {}).get("ODNO", ""))
