# ManipDaily · 机器人操作每日精选

每天早上 8:30（北京时间）自动从 arXiv cs.RO 抓取最新论文，按 **5 条研究路线关键词 × 顶级课题组白名单 × 顶会发表去向** 打分，选出 **5 篇** 发布到静态网站。当天好论文不足 5 篇时，自动补充经典文献（TRO / IJRR / RSS / CoRL / Science Robotics 级别）。支持已读标记、笔记归档、阅读记录导出。

## 为什么不是 zotero-arxiv-daily

`zotero-arxiv-daily`（本项目原 fork 的上游）走的是"Zotero 库 embedding 相似度 → 邮件推送"，需要 Zotero API、SMTP 邮箱等一堆 secret，且没有网站、没有归档、没有经典兜底。本目录是一套独立实现，和 Zotero 完全解耦，fork 里的原有工作流互不影响。

## 文件结构

```
manipdaily/
├── index.html                        # 网站（纯静态，无后端）
├── data/
│   ├── papers.json                   # 每日精选数据（Action 每天追加，保留 45 天）
│   └── classics.json                 # 经典文献库（手工精选，可自行增删）
├── scripts/
│   └── fetch_papers.py               # 抓取+打分脚本（纯标准库，无 pip 依赖）
└── .github/workflows/daily-papers.yml
```

## 部署到你的 GitHub（3 步）

1. **把 `manipdaily/` 目录内容推到你名下的一个仓库**（可以直接推进 `zotero-arxiv-daily` 这个仓库根目录，或新建一个空仓库，推荐后者，干净）：

   ```bash
   cd manipdaily
   git init && git add -A && git commit -m "ManipDaily init"
   git remote add origin git@github.com:afterglow777777/<新仓库名>.git
   git push -u origin main
   ```

   > 注意：若推到已有仓库的子目录，需调整 workflow 路径；推根目录最省事。

2. **开启 GitHub Pages**：仓库 `Settings → Pages → Build and deployment → Source` 选 **GitHub Actions**。

3. **手动触发一次测试**：仓库 `Actions → daily-papers → Run workflow`。跑完后访问
   `https://afterglow777777.github.io/<仓库名>/` 就是公开网站，链接可以直接发给同学。

### 可选：中文"方法与贡献"总结

默认用启发式规则抽取摘要里的贡献句（英文原文）。如果你想让每篇显示两句中文总结：
仓库 `Settings → Secrets and variables → Actions → New repository secret`，名字填 `DEEPSEEK_API_KEY`，值填你的 DeepSeek key。脚本会自动调用 `deepseek-flash` 生成，失败时自动回退到启发式，不会中断流程。

## 打分逻辑（scripts/fetch_papers.py）

- **来源**：arXiv cs.RO 最新 200 条提交（每页 100 条，礼貌间隔 3s）。
- **相关度门槛**：5 条路线关键词命中总数 ≥ 2，或标题直接命中 ≥ 1，否则丢弃。
- **分数** = `2 × 关键词命中 + 标题命中 + 3 × 顶级 PI 命中 + 1.5 × 顶级机构命中(封顶2) + 2.5 × 顶会 comment 命中`
  - 顶级 PI 白名单：Levine / Abbeel / Goldberg / Finn / Shuran Song / Tedrake / Kragic / Huazhe Xu / Cewu Lu / Yuke Zhu 等
  - 顶级机构：词边界匹配摘要里的 affiliation（Stanford / Berkeley / CMU / MIT / ETH / 清华 / 上交 / HKUST / DeepMind / PI / NVIDIA 等）
  - 顶会正则：CoRL / RSS / ICRA / IROS / NeurIPS / ICLR / CVPR / T-RO / IJRR / RA-L / Science Robotics 等（来自 arXiv comment 字段）
- **去重**：按 arXiv ID 全库去重；不足 5 篇时网站自动按日期轮换补充经典文献。

## 改成你自己的口味

- **调路线/关键词/白名单**：直接改 `scripts/fetch_papers.py` 顶部的 `ROUTES / TOP_PIS / TOP_ORGS`，同时同步 `index.html` 里的 `ROUTE_META`（显示用）。
- **加经典文献**：往 `data/classics.json` 的 `papers` 数组加条目即可（链接不确定的用 Google Scholar 检索页，别编 DOI）。
- **每天篇数**：改 `DAILY_PICK`。

## 本地调试

```bash
python scripts/fetch_papers.py     # 重新抓取（幂等，会去重合并）
python -m http.server 8000         # 然后浏览器打开 http://localhost:8000
```

注意：直接双击 `index.html`（file:// 协议）读不到 JSON，必须走 HTTP。
