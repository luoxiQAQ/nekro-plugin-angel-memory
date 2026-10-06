"""生成插件自带的中文字体子集（维护用，不参与运行时）。

背景：上游官方 NekroAgent 镜像**没有安装中文字体**（只有 DejaVu），
PIL 渲染中文卡片时会因找不到字体而静默降级为纯文本。
因此本插件自带一份子集化字体，见 `assets/fonts/`。

重新生成（在带 Noto CJK 字体的容器里跑）：
```bash
python tools/build_fonts.py \
    /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
    /usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc \
    assets/fonts
```

需要 `fonttools`（框架自带 Pillow 环境里通常已有）。

子集范围：ASCII + GB2312 全部汉字（6763）+ 常用标点/符号。
原始 19M+20M 的 TTC → 约 3.1M+3.1M 的 TTF。
"""
from __future__ import annotations

import sys
from pathlib import Path


def build_charset() -> str:
    chars = [chr(c) for c in range(0x20, 0x7F)]  # ASCII 可见字符

    # GB2312 区位：0xA1-0xF7 覆盖符号区与全部汉字
    for hi in range(0xA1, 0xF8):
        for lo in range(0xA1, 0xFF):
            try:
                chars.append(bytes([hi, lo]).decode("gb2312"))
            except UnicodeDecodeError:
                continue

    # 常用补充标点与符号
    chars.append(
        "　、。〃〈〉《》「」『』【】〔〕〖〗〝〞"
        "㈠㈡㈢㈣㈤㈥㈦㈧㈨㈩ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"
        "←↑→↓↔↕■□▲△▼▽◆◇○●◎★☆♠♣♥♦"
        "№℃§±×÷≠≤≥∞∴♂♀°′″‰"
        "—…·•‧～ˉˇ¨〃々"
        "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"
        "⓪⓫⓬⓭⓮⓯⓰⓱⓲⓳⓴"
    )
    # 去重保序
    return "".join(dict.fromkeys(chars))


def subset_one(src: str, dst: str, text: str) -> None:
    from fontTools import subset

    subset.main([
        src,
        f"--text={text}",
        "--output-file=" + dst,
        "--font-number=0",
        "--layout-features=*",
        "--no-hinting",
        "--desubroutinize",
        "--drop-tables+=DSIG",
        "--name-IDs=*",
        "--recalc-bounds",
    ])


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2

    regular_src, bold_src, out_dir = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    out_dir.mkdir(parents=True, exist_ok=True)
    text = build_charset()
    print(f"子集字符数: {len(text)}")

    subset_one(regular_src, str(out_dir / "angel-regular.ttf"), text)
    subset_one(bold_src, str(out_dir / "angel-bold.ttf"), text)

    for name in ("angel-regular.ttf", "angel-bold.ttf"):
        fp = out_dir / name
        print(f"  {name}: {fp.stat().st_size / 1024 / 1024:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
