#!/usr/bin/env bash
# Generate an ORIGINAL test sample (synthetic colour pattern + sine tone, no third-party
# material) in the four-file delivery layout:  OUT/ID/{ID.mp4,cover.jpg,weibo.txt,subtitle.srt}
# Usage: make_test_asset.sh TEST-0001 OUTDIR
set -euo pipefail
ID="$1"; OUT="$2"
case "$ID" in TEST-*) ;; *) echo "test ids must start with TEST-" >&2; exit 2;; esac
D="$OUT/$ID"; mkdir -p "$D"
FONT=$(fc-list ':lang=zh' file 2>/dev/null | head -n1 | cut -d: -f1)  # fc-match falls back to non-CJK fonts
[ -n "$FONT" ] || { echo "no CJK font found (install fonts-noto-cjk)" >&2; exit 2; }
ffmpeg -v error -y -f lavfi -i "testsrc2=size=1920x1080:rate=30:duration=12" \
  -f lavfi -i "sine=frequency=440:sample_rate=48000:duration=12" \
  -vf "drawbox=x=0:y=380:w=1920:h=320:color=black@0.75:t=fill,drawtext=fontfile=$FONT:text='OPC 公开交付 测试样片 $ID':fontsize=96:fontcolor=white:x=(w-tw)/2:y=420,drawtext=fontfile=$FONT:text='TEST ONLY · 非正式视频':fontsize=56:fontcolor=yellow:x=(w-tw)/2:y=560" \
  -c:v libx264 -preset veryfast -crf 26 -pix_fmt yuv420p -profile:v high -c:a aac -b:a 128k -ac 2 \
  -movflags +faststart -metadata title="OPC TEST SAMPLE $ID - NOT A FORMAL DELIVERY" "$D/$ID.mp4"
ffmpeg -v error -y -f lavfi -i "testsrc2=size=1920x1080:rate=1:duration=1" -frames:v 1 \
  -vf "drawbox=x=0:y=380:w=1920:h=320:color=black@0.8:t=fill,drawtext=fontfile=$FONT:text='测试封面 TEST COVER $ID':fontsize=110:fontcolor=white:x=(w-tw)/2:y=470" \
  -q:v 3 "$D/cover.jpg"
printf '【测试文案｜TEST ONLY】这是 OPC 公开交付链路的测试样片 %s，画面为程序生成的测试图案，声音为正弦测试音，不含任何第三方素材，不是正式视频，请勿发布。\n' "$ID" > "$D/weibo.txt"
printf '1\n00:00:00,500 --> 00:00:04,000\n测试字幕：这是测试样片 %s\n\n2\n00:00:04,500 --> 00:00:08,000\nTEST ONLY · 不是正式视频\n\n3\n00:00:08,500 --> 00:00:11,500\n交付链路校验用\n' "$ID" > "$D/subtitle.srt"
echo "$D"
