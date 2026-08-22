# MinOS-WJ 工作台

这是一个无需构建步骤的 GitHub Pages 静态站点。

## 部署

1. 将仓库推送到 GitHub。
2. 在 Settings → Pages 中选择 Deploy from a branch。
3. 选择默认分支和 / (root) 目录。
4. 等待 Pages 发布完成。

站点使用相对路径，支持发布到用户站点或项目站点；.nojekyll 用于避免 Jekyll 改写静态目录。

AI 工具和新闻阅读需要浏览器网络权限；AI API Key 只在当前页面内存中使用，不会写入仓库。

模型能力排行榜使用仓库内的 `page/ai/model-data.json`，不在浏览器中直接抓取第三方接口。维护者可在有网络的环境运行 `python scripts/update_model_data.py --source aitier`，批量刷新 AITier 的通用、编码、数学、科学、推理、Agents、多模态、图像生成、文生视频、图生视频和音频 11 个公开榜单。脚本不会请求 `/api/` 或 `/_next/`，遇到 Cloudflare 限制时只回退到公开页面文本代理。

AITier 输出使用 `minos-ai-rankings/v2`：`models` 保持前端兼容，`rankings` 按榜单保留公开页面中的全部原始单元格、来源代码、榜单类别、分数原文、价格状态与单位、基准说明、数据更新时间、总记录数、分页抓取情况和错误。默认不截断，并会在页面公开总记录数时继续请求后续页；可用 `--max-pages` 控制安全上限，用 `--strict` 在任何榜单或分页不完整时拒绝写入。

常用命令：

- `python scripts/update_model_data.py --source aitier --dry-run`：抓取并打印，不写文件。
- `python scripts/update_model_data.py --source aitier --domains coding reasoning agents`：只刷新指定榜单。
- `python scripts/update_model_data.py --source aitier --transport jina`：只使用公开页面文本代理。
- `$env:JINA_API_KEY='jina_...'` 后再运行脚本：当前出口被 Jina 匿名访问策略返回 401/403 时使用认证请求。
- `python scripts/update_model_data.py --source aitier --input snapshots`：离线解析目录中的 `general.md`、`audio-page-2.html` 等快照。
- `python scripts/update_model_data.py --source hf` 或 `python scripts/update_model_data.py --source lmsys`：使用其他公开来源。

运行后提交 `page/ai/model-data.json` 即可发布新数据。脚本在没有有效评分时会拒绝写入；网络不稳定时会按榜单复用现有 v2 快照。若所有实时请求均失败，默认保留原文件并正常退出，不会用空数据覆盖；`--no-cache` 可禁用回退，`--strict` 可让缓存回退、缺榜或分页不完整直接失败。部分刷新会在 JSON 中记录 `partial`、`errors`、`warnings` 和 `cachedDomains`。
