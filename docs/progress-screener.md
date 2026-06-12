# 智能选股功能 — 开发进度记录

> 最后更新：2026-06-12

## 功能目标

每日扫描 A 股行业板块 → 找到估值被低估的板块 → 从中筛选龙头股 → 一键发起现有单股深度分析。

---

## 已完成

### 后端

| 文件 | 状态 | 说明 |
|------|------|------|
| `tradingagents/dataflows/sector_data.py` | ✅ 新建 | AkShare 数据层：板块列表、成分股、全市场快照、ROE、主力资金流，TTL 缓存 |
| `server/models.py` | ✅ 修改 | 新增三张表：`SectorSnapshot`、`ScreeningRun`、`ScreeningCandidate` |
| `server/screener.py` | ✅ 新建 | 选股引擎：PE+PB历史分位<30%判低估；龙头评分=市值40%+流动性25%+ROE20%+资金流15% |
| `server/tasks.py` | ✅ 修改 | 末尾新增：`launch_analysis()`公共启动器、`run_screening_task` Celery任务、`scheduled_daily_screening` 定时入口 |
| `server/celery_app.py` | ✅ 修改 | 加 Celery Beat：周一至周五 16:00 CST 自动跑批；时区改为 `Asia/Shanghai` |
| `server/routers/screener.py` | ✅ 新建 | REST API（见下方 API 清单）|
| `server/schemas.py` | ✅ 修改 | 新增 `ScreeningRunCreate/Out/DetailOut`、`ScreeningCandidateOut` |
| `server/main.py` | ✅ 修改 | 注册 `screener_router`，路径 `/api/screener` |

#### API 清单

```
POST   /api/screener/run                          创建并分发筛选任务（Celery）
GET    /api/screener/runs                         历史跑批列表
GET    /api/screener/runs/latest                  最新一次跑批详情（含候选股）
GET    /api/screener/runs/{id}                    指定跑批详情
POST   /api/screener/candidates/{id}/analyze      对单只候选股发起分析
POST   /api/screener/runs/{id}/analyze-all        批量对整组/单板块候选股发起分析
```

### 前端

| 文件 | 状态 | 说明 |
|------|------|------|
| `web/src/types.ts` | ✅ 修改 | 新增 `ScreeningCandidate`、`UndervaluedBoard`、`ScreeningSummary`、`ScreeningRun` 接口 |
| `web/src/api/client.ts` | ✅ 修改 | 新增 6 个 screener API 方法：`runScreening / listScreeningRuns / getLatestScreeningRun / getScreeningRun / analyzeCandidate / analyzeAllCandidates` |
| `web/src/pages/Screener.tsx` | ✅ 新建 | 选股页面：板块低估卡片、候选龙头列表、一键分析/批量分析/查看报告 |
| `web/src/components/Sidebar.tsx` | ✅ 修改 | 加「🔍 智能选股」导航项，路由 `/screener` |
| `web/src/components/BottomNav.tsx` | ✅ 修改 | 加「🔍 选股」移动端底部导航 |
| `web/src/App.tsx` | ✅ 修改 | 注册 `/screener` 路由，导入 `Screener` 页面 |

### 验证状态
- ✅ Python 全部文件 `py_compile` 通过
- ✅ 后端模块 `import` 通过（`server.screener`、`server.routers.screener`、`server.tasks`、`server.celery_app`）
- ✅ 前端 TypeScript `tsc --noEmit` 0 错误

---

## 待完成 / 下一步

### 已验证

1. **AkShare 列名验证** ✅（2026-06-12，akshare 1.18.62 实测）
   - `stock_board_industry_name_em`：`板块名称`/`板块代码`/`最新价`/`涨跌幅`/`总市值`/`换手率`/`上涨家数`/`下跌家数` 均匹配。
   - `stock_board_industry_cons_em`：`代码` 匹配。
   - `stock_zh_a_spot_em`：`代码`/`名称`/`最新价`/`涨跌幅`/`成交额`/`市盈率-动态`/`市净率`/`总市值`/`流通市值`/`换手率` 均匹配。
   - `stock_yjbb_em`：`股票代码`/`净资产收益率`（动态查找列名）匹配。
   - `stock_individual_fund_flow_rank`：实际列名为 `今日主力净流入-净额`，代码用 `"主力净流入-净额" in str(c)` 子串匹配，仍可命中，无需改动。
   - 端到端跑通 `sd.get_industry_boards()`（496 个板块）与 `sd.get_market_spot()`（5862 只股票），结构正确。
   - **结论：`sector_data.py` 无需修改。**

2. **Celery Beat 服务** ✅ 已加入 `docker-compose.prod.yml`（新增 `celery-beat` 服务，命令 `celery -A server.celery_app beat --loglevel=info`，复用 `.env.prod` 与 `tradingagents_data` 卷）。

### 优先级高

1. **前端"历史跑批"切换器**（可选 UI 增强）
   - 当前页面只展示最新一次跑批结果，可在页面顶部加下拉选择器切换历史跑批。
   - API `GET /api/screener/runs` 已就绪。

2. **部署**
   ```bash
   # 本地
   git add . && git commit -m "feat(screener): A股智能选股漏斗功能" && git push origin main
   # 服务器
   ssh admin@47.103.133.232
   cd /opt/tradingagents && bash deploy.sh
   ```

---

## 关键设计决策（备忘）

- **估值口径**：PE+PB 同时低于历史分位 30%。历史数据不足 20 个点时退化为同日跨板块横截面分位，`board_valuation_method` 字段标记 `historical` / `cross_section`。
- **龙头评分权重**：市值 40% + 成交额（流动性）25% + ROE 20% + 主力净流入 15%，均在板块内 min-max 归一化。
- **每日数据累积**：每次筛选将当日板块 PE/PB 写入 `sector_snapshots`，随时间积累后历史分位精度提升。
- **自动化**：Celery Beat 每日 16:00 CST 触发，自动分析 Top3 候选股。用户也可在页面手动触发 + 选择是否自动分析。
- **复用现有分析引擎**：候选股分析完全走已有的 `create_analysis` → `run_analysis` Celery 任务，无需重写。
