# QLD 비중 대시보드 (QQQ 변동성 타깃)

QQQ 20일 변동성으로 2배 레버리지 ETF(QLD) 목표 비중을 매일 계산해 보여주는 개인용 정적 사이트.
GitHub Actions가 매일(한국 시간 화~토 08:10) 데이터를 받아 `data/*.json`을 갱신·커밋하고 GitHub Pages에 배포한다.

## 전략
| 항목 | 계산 |
|---|---|
| 일간 수익률 | r = 오늘 QQQ 수정종가 / 어제 수정종가 − 1 |
| hv | 최근 20개 r의 모집단 표준편차 × √252 |
| TradingView HV(20) | hv × √(365/252) × 100 |
| 목표 QLD 비중 | w = min(100%, 12.5% ÷ hv) ≈ 15 ÷ TV HV (정확히는 15.04) |
| 신호 | 매주 마지막 거래일(보통 금) 종가로 확정 → 다음 거래일 매매 |
| 리밸런싱 | \|실제 − w\| ≥ 10%p 일 때만, 정확히 w로 |
| 참고 | QQQ 종가 vs 250일 단순이동평균 |

## 구조
```
.github/workflows/update.yml  매일 실행: 테스트 → 수집 → 커밋 → Pages 배포
scripts/strategy.py           지표·주간 신호 계산 (표준 라이브러리만)
scripts/fetch_data.py         Yahoo → Stooq 폴백, 둘 다 실패 시 기존 데이터 유지 + stale
rebalance.js                  리밸런싱/적립 계산 (브라우저·Node 테스트 공용)
index.html, app.js            대시보드 (빌드 도구 없음)
data/latest.json, history.json
tests/                        파이썬 unittest + node:test
```

## 로컬 실행
```bash
python3 -m unittest discover -s tests -v
node --test tests/rebalance.test.js
python3 scripts/fetch_data.py         # data/ 갱신
python3 -m http.server 8000           # http://localhost:8000
```

보유 수량은 브라우저 localStorage에만 저장되며 저장소에는 어떤 개인정보·API 키도 없다.

참고용 계산이며 투자 판단은 본인 책임.
