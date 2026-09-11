# IB Knowledge Base 維運手冊

## 邊界

- 本 repository 只負責 `https://larry890122.github.io/ib-knowledge-base/`。
- RV 網站由獨立的 `rv-dashboard` repository 負責；本 repo 不得修改或發布 RV 程式與資料。
- 導覽直接連至 `https://larry890122.github.io/rv-dashboard/`；舊 `/rv/` 僅保留轉址。

## 每次開始網站工作

1. `git fetch origin`，從 `origin/main` 建立 `codex/<task>` branch 或 Codex worktree。
2. 完整閱讀本文件與上層 `AGENTS.MD`。
3. 執行 `python3 peer_status.py`，記錄 RV 最後穩定版本。
4. 確認 `git status` 沒有不屬於本任務的變更，且修改範圍只在本 repository。

## 建置、測試與發布

```sh
python3 publish.py --build-only
python3 -m unittest discover -s tests -v
python3 peer_status.py
```

- 上層 `Processed` 是內容來源；本地建置完成後，把必要的公開輸出與程式修改加入同一個 `codex/<task>` PR。
- PR 測試通過後才合併 `main`；GitHub Pages 僅部署 `main`。
- 發布後確認首頁、舊 `/rv/` 轉址與 `integration-manifest.json`。
- 發布失敗時修正原 PR，或用 `git revert <merge-commit>` 建立回復 PR，不得修改 RV repo。

## 跨站契約

- manifest schema 目前為 v1；新增欄位可向後相容，刪除、改名或型別變更需建立 `COORD-YYYYMMDD-NN` 成對 PR。
- 先更新讀取方接受新舊 schema，再更新輸出方，最後才能移除舊格式。
- peer 暫時離線只警告，不阻止本站內容建置；每日 health workflow 必須失敗並通知。
- manifest 只代表最後已部署版本；未合併進度以 branch／PR 為準。
