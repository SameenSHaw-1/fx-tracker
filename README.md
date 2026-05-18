# 汇率追踪 FX Tracker

一个部署在 GitHub Pages 上的静态网页应用，实时追踪多种货币对人民币(CNY)的汇率。

## 功能特性

- **多银行数据**：中国银行(BOC)、工商银行(ICBC)、农业银行(ABC)
- **多货币支持**：EUR、USD、THB、JPY、KRW → CNY
- **价格类型**：现汇买入、现汇卖出、中间价
- **实时刷新**：每 5 分钟自动更新
- **历史走势**：支持查看今日 / 近7天 / 近1月 / 近3月 / 近6月走势图
- **涨跌警示**：对比昨日中间价，涨跌幅 ≥0.5% 时自动红/绿高亮
- **暗色金融风格**：专业的深色 UI 设计

## 部署步骤

### 1. 创建 GitHub 仓库

```bash
# 创建一个新的 public 仓库，例如 fx-tracker
# 将本项目的文件推送到该仓库
git init
git remote add origin https://github.com/YOUR_USERNAME/fx-tracker.git
git add .
git commit -m "Initial commit: FX Tracker"
git push -u origin main
```

### 2. 启用 GitHub Pages

1. 进入仓库 **Settings → Pages**
2. Source 选择 **GitHub Actions**（推荐）或 **Deploy from a branch**
3. 如果选择 Deploy from a branch：
   - Branch: `main`
   - Folder: `/ (root)`

### 3. 启用 GitHub Actions

1. 进入仓库 **Settings → Actions → General**
2. 选择 **Allow all actions and reusable workflows**
3. 确保 `workflow_dispatch` 和 `schedule` 事件被允许

### 4. 配置定时任务

GitHub Actions 的 `fetch-rates.yml` 已配置为每 5 分钟运行一次：

```yaml
schedule:
  - cron: '*/5 * * * *'
```

> **注意：** GitHub 免费计划对 public 仓库有每分钟 2,000 分钟/月的 Actions 额度。每5分钟执行一次约消耗 8,640 分钟/月，**建议根据实际情况调整频率**（如每30分钟或每小时）。

### 5. 预填历史数据（可选）

如果需要初始的历史数据来展示走势图，运行 bootstrap 脚本：

```bash
# 安装依赖
pip install requests

# 运行 bootstrap（预填最近180天）
python scripts/bootstrap_history.py
```

这将从 [frankfurter.app](https://www.frankfurter.app/) 获取历史汇率数据并写入 `data/history/` 目录。

```bash
git add data/history/
git commit -m "Bootstrap 180 days of history"
git push
```

### 6. 手动触发数据更新

如果需要立即刷新数据（不等待定时任务）：

1. 进入仓库 **Actions** 标签
2. 选择 **Fetch Exchange Rates** workflow
3. 点击 **Run workflow** → **Run workflow**

## 项目结构

```
.
├── .github/
│   └── workflows/
│       └── fetch-rates.yml    # GitHub Actions 定时任务
├── scripts/
│   ├── fetch_rates.py          # 爬取银行汇率数据
│   └── bootstrap_history.py    # 从 frankfurter.app 预填历史数据
├── data/
│   ├── rates.json              # 当前汇率数据（自动生成）
│   └── history/                # 每日历史数据（自动生成）
│       └── .gitkeep
├── index.html                  # 主页面
├── style.css                   # 样式表
├── app.js                      # 前端逻辑
└── README.md                   # 说明文档
```

## 数据格式

### data/rates.json

```json
{
  "updated_at": "2026-05-18T15:30:00Z",
  "source": "bank_scrape",
  "rates": {
    "BOC": {
      "status": "ok",
      "EUR": { "buy": 780.12, "sell": 783.45, "mid": 781.78 },
      ...
    }
  }
}
```

### data/history/YYYY-MM-DD.json

```json
[
  {
    "time": "09:30",
    "source": "bank_scrape",
    "BOC_EUR_mid": 781.78,
    "BOC_EUR_buy": 780.12,
    "BOC_EUR_sell": 783.45,
    ...
  }
]
```

## 技术栈

- **前端**：HTML + CSS + JavaScript (Chart.js 4.x)
- **后端**：Python 3.11 + requests + BeautifulSoup4
- **CI/CD**：GitHub Actions
- **数据源**：中国银行、工商银行、农业银行、Frankfurter API

## 注意事项

1. **银行网站可能变化**：爬虫代码依赖银行网站的 HTML 结构，如果网站改版需要更新爬虫逻辑
2. **频率限制**：GitHub Actions 有运行次数和时长限制，建议根据实际需求调整 cron 频率
3. **CORS**：`data/rates.json` 和 `data/history/` 是静态 JSON 文件，直接通过 GitHub Pages 的 `fetch()` 访问，无需额外配置
4. **免责声明**：数据仅供参考，不构成任何交易建议

## License

MIT
