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
