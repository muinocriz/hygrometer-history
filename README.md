# 温湿度计历史数据

把温湿度计导出的每小时记录做成可视化网页，部署在 GitHub Pages。

- `index.html`：页面与图表逻辑（ECharts，CDN 引入）
- `data/history.csv`：原始数据，每行一小时：`时间, 最低温度℃, 最低湿度%, 最高温度℃, 最高湿度%`

## 更新数据

用温湿度计新导出的 CSV 覆盖 `data/history.csv` 后提交即可，格式保持不变。

## 本地预览

页面通过 `fetch` 读取 CSV，不能直接双击打开，需要起一个本地服务：

```bash
python -m http.server
# 浏览器打开 http://localhost:8000
```

## 配置

`index.html` 顶部的 `CONFIG`：

- `lat` / `lon` / `tz`：用于计算日出日落阴影的位置（默认上海）
- `minHoursPerDay`：一天有效小时数低于此值视为“数据不足”（默认 12）
