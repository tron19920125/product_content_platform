# Bundled font sources and redistribution audit

All font binaries in this directory are distributed under the SIL Open Font License 1.1. The full license is retained as `OFL-1.1.txt`. The product bundles these fonts as part of the editor; it does not sell the font files by themselves. Upstream family-specific copyright and license links are also exposed by `/api/fonts`.

| File | Font | Coverage / intended use | Verified upstream |
| --- | --- | --- | --- |
| `NotoSansSC-Variable.ttf` | Noto Sans SC | Simplified Chinese, general copy | `google/fonts/ofl/notosanssc` |
| `NotoSerifSC-Variable.ttf` | Noto Serif SC | Simplified Chinese, editorial copy | `google/fonts/ofl/notoserifsc` |
| `LXGWWenKai-Regular.ttf` | LXGW WenKai | Chinese lifestyle copy | `lxgw/LxgwWenKai` |
| `MaShanZheng-Regular.ttf` | Ma Shan Zheng | Chinese brush headline | `google/fonts/ofl/mashanzheng` |
| `LongCang-Regular.ttf` | Long Cang | Chinese handwriting headline | `google/fonts/ofl/longcang` |
| `LiuJianMaoCao-Regular.ttf` | Liu Jian Mao Cao | Chinese cursive headline | `google/fonts/ofl/liujianmaocao` |
| `ZhiMangXing-Regular.ttf` | Zhi Mang Xing | Chinese running-script headline | `google/fonts/ofl/zhimangxing` |
| `SmileySans-Oblique.ttf` | Smiley Sans | Chinese display headline | `atelier-anchor/smiley-sans` release `v2.0.1` |
| `LXGWMarkerGothic-Regular.ttf` | LXGW Marker Gothic | Chinese advertising headline | `lxgw/LxgwMarkerGothic` |
| `Iansui-Regular.ttf` | Iansui | Chinese natural handwriting | `google/fonts/ofl/iansui` / `ButTaiwan/iansui` |
| `WDXLLubrifontSC-Regular.ttf` | WD-XL Lubrifont SC | Chinese rounded display | `google/fonts/ofl/wdxllubrifontsc` |
| `BebasNeue-Regular.ttf` | Bebas Neue | Latin prices and numbers | `google/fonts/ofl/bebasneue` |
| `Anton-Regular.ttf` | Anton | Latin promotion headline | `google/fonts/ofl/anton` |
| `Bungee-Regular.ttf` | Bungee | Latin street-style display | `google/fonts/ofl/bungee` |
| `BlackOpsOne-Regular.ttf` | Black Ops One | Latin technical numbers | `google/fonts/ofl/blackopsone` |
| `Lobster-Regular.ttf` | Lobster | Latin script headline | `google/fonts/ofl/lobster` |

The three legacy ZCOOL binaries were removed from the shipped catalog because their upstream licensing history has a public ambiguity report (`google/fonts#2698`). Existing documents that reference those IDs fall back to the system font rather than failing to load.
