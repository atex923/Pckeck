# Pckeck 右欄標記資料格式

V0.2.5 的「匯出標記資料」會建立 UTF-8 JSON，預設副檔名為 `.pcheckmarks.json`。格式識別值為 `pckeck-right-mark-overlay`，目前 `schema_version` 為 `1`。

## 來源驗證

讀取資料的程式應先以 `source_pdf.sha256` 驗證待疊圖 PDF。`source_pdf.pages` 記錄每頁寬、高，可再用於檢查頁面幾何是否一致。

## 座標系統

- 單位為 PDF point，72 point 等於 1 inch。
- 原點位於頁面左上角，X 軸向右、Y 軸向下。
- `page_index` 從 0 起算，供程式存取；`page_number` 從 1 起算，供畫面顯示。
- 不需套用 Pckeck 畫面的縮放比例或捲動位置。

## 疊圖項目

`overlays` 依序包含右欄的自動差異線與手動標記：

- `kind: underline`：以 `rect` 的底邊附近繪製差異線；Pckeck 使用 `y = rect[3] - 0.8`、線寬 `width_pt`。
- `kind: highlight`：由 `start` 畫至 `end`，使用 `color`、`width_pt` 與 `opacity`，線端採圓頭。
- `kind: double_strike`：由 `start` 至 `end` 繪製兩條平行線。垂直於標記方向的正負位移量為 `width_pt * 1.4 + 1.2` point。

顏色使用 `#rrggbb`。`source` 可區分 `automatic_difference` 與 `manual`；自動標線的 `difference_type` 為 `addition` 或 `modification`。

## 其他欄位

- `page_links`：不同處的舊頁與右頁對應，含顯示頁碼及差異類型。
- `summary`：自動、手動及全部疊圖筆數。
- `created_at`：UTC ISO 8601 匯出時間。
