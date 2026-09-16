# NegotiationArena — 跨語言 LLM 買方議價穩健性實驗（fork）

本 repo 是 [vinid/NegotiationArena](https://github.com/vinid/NegotiationArena)（Bianchi et al., 2024, MIT License）的 fork，用於碩士論文實驗：

> **跨語言 LLM 買方議價之穩健性：中文與英文語境比較**
> Robustness of LLM Buyer Bargaining Across Languages: A Chinese–English Comparison

原框架的 README 見 [README_original.md](README_original.md)。本 repo 只使用 buy-sell 賽局，其餘賽局未修改、未使用。

## 研究問題
- **RQ1** 無施壓條件下，中文與英文語境的 LLM 買方代理人在失守率與首次出價比（FBR）上是否有差異
- **RQ2** 面對賣方施壓戰術時，買方失守率上升多少；幅度是否因語言而異
- **RQ3**（可選）上述效應是否隨買方模型能力層級改變

「穩健性」定義為買方代理人保護買方的能力：不超預算成交、不在無可行價格時成交、保留合理利潤空間。

## 相對原框架的修改
| 位置 | 修改 |
|---|---|
| `games/buy_sell_game_zh/` | 新增，中文版賽局（複製自 `buy_sell_game/`，僅 `prompt.py` 翻譯為繁體中文；XML tag、ZUP、X、Player 名稱保留英文） |
| `negotiationarena/agents/claude.py` | 升級至新版 Anthropic SDK |
| `negotiationarena/agents/scripted_seller.py` | 新增，確定性腳本賣方（線性讓價，不呼叫 API） |
| `experiments/` | 新增：批次 runner、指標計算、語言遵從檢測 |
| `analysis/` | 新增：統計腳本與圖表 |
| `CLAUDE.md` | 開發規範（給 Claude Code 與協作者） |

## 安裝
```bash
git clone https://github.com/<your-account>/NegotiationArena
cd NegotiationArena
python -m venv .venv && source .venv/bin/activate
pip install openai anthropic python-dotenv pandas matplotlib statsmodels
```
不要使用原 `requirements.txt` 中的 `anthropic==0.5.0`。

`.env`：
```
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
NEGOTIATION_LOG_FOLDER=./.logs/
```

## 執行
單局測試（英文）：
```bash
python runner/buysell_main.py
```
批次實驗：
```bash
python experiments/batch_runner.py --lang zh --tactic scripted --buyer haiku45 --n 40
```
計算指標：
```bash
python experiments/metrics.py --logs .logs/ --out analysis/results.csv
```

## 實驗設計
- 因子：語言 {en, zh} × 賣方戰術 {baseline, scripted, (emotional)} × 買方模型 {便宜級, 旗艦級}
- 賽局：buy-sell，回合上限 10，temperature 0.7
- 指標：失守率 A（超預算成交）、B（CI 場景成交）、C（MI 場景 normalized profit）、FBR、語言遵從率
- 統計：mixed-effects（語言 × 戰術為固定效應，模型配對為隨機效應），效應量 Cohen's h / Cliff's δ

## 資料版本
正式資料以 git tag 標記：`pilot-v1`（校準用）、`data-v1`（正式收集）。

## 引用
使用本框架請引用原論文：
```
@inproceedings{bianchi2024llms,
  title={How Well Can LLMs Negotiate? NegotiationArena Platform and Analysis},
  author={Bianchi, Federico and Chia, Patrick John and Yuksekgonul, Mert and Tagliabue, Jacopo and Jurafsky, Dan and Zou, James},
  booktitle={Proceedings of the 41st International Conference on Machine Learning (ICML)},
  year={2024}
}
```

## 授權
MIT License，沿用原專案。
