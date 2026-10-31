# 温湿度计历史数据

把温湿度计导出的每小时记录做成可视化网页，部署在 GitHub Pages。

在线访问：https://muinocriz.github.io/hygrometer-history/

## 想法与参考来源

图表的思路参考了 WeatherSpark 的气候页面，把同样的展示方式用到自己温湿度计的实测数据上：

- [WeatherSpark · 上海虹桥国际机场全年平均天气](https://weatherspark.com/y/149263/Average-Weather-at-Shanghai-Hongqiao-International-Airport-China-Year-Round)

页面包含：

- 温度、湿度折线图：按日 / 月 / 年切换，显示最高、最低、平均值
- 月内日变化叠加：当月每天的 24 小时曲线叠在一起，阴影为范围、折线为平均，可勾选显示项
- 每小时平均温度瓦片图：按体感区间着色，叠加日出日落与民用晨昏蒙影阴影
- 湿度舒适等级：用 Magnus 公式由温湿度计算露点，按露点分级统计每天的时间占比

缺失数据用虚线连接；一天有效小时数不足时标记为“数据不足”且不计入统计。

## 特别鸣谢

感谢 [@zhoulin12138](https://github.com/zhoulin12138) 为项目提供设备协助。

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
