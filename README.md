# 券商報告知識庫網站

本目錄是獨立的公開網站 repository。網站只從上層 `Processed` 產生經過清理的公開內容；個別報告頁公開「重點摘要」與「主題整理」，但不上傳原始 Markdown、PDF、Excel、來源檔名、雜湊或處理紀錄。

## 建置

```sh
python3 publish.py --build-only
python3 -m http.server 8765 --directory public
```

本機預覽網址為 `http://localhost:8765/`。

正式網站預定網址為 <https://larry890122.github.io/ib-knowledge-base/>。

## 發布

首次完成 GitHub repo 與 Pages 設定後：

```sh
python3 publish.py --deploy
```

發布器會先在暫存目錄建置、檢查首頁順序與敏感資訊，通過後才更新 `public`。若內容沒有變更，不會建立空 commit。
# RV 相對價值

`/rv/` shares the site navigation and publish process. The initial snapshot is 2Y,
dated 2026-08-05, with 92 records and 460 summary values. Normal builds use the
validated `assets/rv-data.json`; private Excel and presentation files are not needed.

To refresh, run `python3 scripts/extract_rv.py --workbooks <Spread> <10Y> <30Y> <10s30s>
--deck <reviewed-deck> --date YYYY-MM-DD --slide-date YYYY-MM-DD --audit <private-audit-path>`.
Arguments are local paths. Keep the audit outside this repository. The slide date
is a human-reviewed data-date attestation, not a file creation date. Review it again
for each new deck; the extractor is scoped to the reviewed 13-slide v2 layout.

Excel numeric caches take priority. Invalid/missing caches may use same-date visible
slide labels (integer bp, displayed as approximate) or the new native percentile
chart. Legacy hidden combo chart caches are stale and excluded. A missing median
has no eligible slide fallback and stays missing. The extractor records full paths,
cells, slide locators, precision and differences only in the private audit; a
comparison difference stops snapshot replacement. It never modifies source files.

Build with `python3 publish.py --build-only`, test with `python3 -m unittest discover
-s tests -v`, then deploy with `python3 publish.py --deploy`. Browser regression is
in `tests/rv-browser.cjs` (Playwright; run against a served `public` directory).
